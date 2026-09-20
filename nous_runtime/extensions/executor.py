"""The sole Runtime entry point for executing an admitted extension tool."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from jsonschema import ValidationError, validate

from nous_runtime.extensions.models import ToolSpec
from nous_runtime.extensions.registry import ExtensionRegistry


class ExtensionExecutionError(RuntimeError):
    pass


class KernelExecutionClient(Protocol):
    async def authorize_extension_execution(
        self, execution: dict[str, Any], idempotency_key: str = ""
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExtensionInvocation:
    extension_id: str
    content_digest: str
    operation: str
    protocol: str
    capability: str
    scope: tuple[str, ...]
    arguments: dict[str, Any]
    package_root: Path


@dataclass(frozen=True)
class AdapterResult:
    success: bool
    output: Any = None
    error_code: str = ""
    duration_ms: int = 0
    output_bytes: int = 0
    verification_status: str = "unverified_executor_report"


class GovernedExtensionAdapter(Protocol):
    async def execute(
        self, invocation: ExtensionInvocation, *, permit_id: str
    ) -> AdapterResult: ...


@dataclass(frozen=True)
class ExtensionExecutionReceipt:
    schema_version: int
    receipt_id: str
    operation_id: str
    permit_id: str
    actor: str
    source: dict[str, str]
    target: dict[str, str]
    extension_id: str
    content_digest: str
    operation: str
    capability: str
    requested_capabilities: tuple[str, ...]
    granted_capabilities: tuple[str, ...]
    input_digest: str
    parameter_hash: str
    success: bool
    result: str
    policy_version: str
    executor: str
    started_at_us: int
    finished_at_us: int
    effect_digest: str
    output_digest: str
    result_digest: str
    error_code: str
    duration_ms: int
    output_bytes: int
    verification_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtensionExecutionResult:
    output: Any
    receipt: ExtensionExecutionReceipt


class UnifiedExtensionExecutor:
    """Fail closed unless Kernel grants an exact, parameter-bound permit."""

    def __init__(
        self,
        registry: ExtensionRegistry,
        kernel: KernelExecutionClient,
        adapters: dict[str, GovernedExtensionAdapter] | None = None,
    ):
        self.registry = registry
        self.kernel = kernel
        self.adapters = dict(adapters or {})

    def register_adapter(
        self, protocol: str, adapter: GovernedExtensionAdapter
    ) -> None:
        if not protocol or protocol in self.adapters:
            raise ValueError("extension protocol adapter is empty or already registered")
        self.adapters[protocol] = adapter

    async def execute_tool(
        self,
        extension_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> ExtensionExecutionResult:
        manifest, record, admission = self._authorized_extension(extension_id)
        tools = list(manifest.tools)
        if manifest.source_format == "mcp-config":
            try:
                tools.extend(
                    ToolSpec(**item)
                    for item in self.registry.read_discovered_tools(extension_id)
                )
            except (TypeError, ValueError) as exc:
                raise ExtensionExecutionError(f"MCP tool catalog is invalid: {exc}") from exc
        tool = next((item for item in tools if item.name == tool_name), None)
        if tool is None:
            raise ExtensionExecutionError(f"extension tool is not declared: {tool_name}")
        try:
            validate(instance=arguments, schema=tool.input_schema)
        except ValidationError as exc:
            raise ExtensionExecutionError(
                f"tool arguments do not match declared schema: {exc.message}"
            ) from exc
        protocol = tool.protocol or "native"
        capability = (
            _mcp_capability(manifest)
            if protocol == "mcp"
            else _execution_capability(protocol, tool.effect)
        )
        return await self._execute_authorized(
            extension_id,
            manifest,
            record,
            admission,
            operation=tool.operation or tool.name,
            protocol=protocol,
            capability=capability,
            arguments=arguments,
            idempotency_key=idempotency_key,
        )

    async def discover_mcp_tools(
        self, extension_id: str, *, idempotency_key: str
    ) -> tuple[ToolSpec, ...]:
        manifest, record, admission = self._authorized_extension(extension_id)
        if manifest.source_format != "mcp-config" or len(manifest.entry_points) != 1:
            raise ExtensionExecutionError(
                "MCP discovery currently requires one normalized MCP server"
            )
        result = await self._execute_authorized(
            extension_id,
            manifest,
            record,
            admission,
            operation="tools/list",
            protocol="mcp",
            capability=_mcp_capability(manifest),
            arguments={},
            idempotency_key=idempotency_key,
        )
        raw_tools = result.output.get("tools") if isinstance(result.output, dict) else None
        if not isinstance(raw_tools, list):
            raise ExtensionExecutionError("MCP discovery returned no tool catalog")
        tools: list[ToolSpec] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                raise ExtensionExecutionError("MCP discovery returned an invalid tool")
            tool = ToolSpec(
                name=str(item.get("name") or ""),
                description=str(item.get("description") or ""),
                input_schema=dict(item.get("input_schema") or {}),
                output_schema=dict(item.get("output_schema") or {}),
                effect="unknown",
                protocol="mcp",
                operation=f"tools/call:{item.get('name') or ''}",
            )
            errors = tool.validate()
            if errors:
                raise ExtensionExecutionError("invalid discovered MCP tool: " + "; ".join(errors))
            tools.append(tool)
        self.registry.record_discovered_tools(
            extension_id,
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "output_schema": tool.output_schema,
                    "effect": tool.effect,
                    "protocol": tool.protocol,
                    "operation": tool.operation,
                }
                for tool in tools
            ],
            discovery_receipt_id=result.receipt.receipt_id,
        )
        return tuple(tools)

    def _authorized_extension(self, extension_id):
        try:
            manifest = self.registry.verify(extension_id)
        except (OSError, ValueError) as exc:
            raise ExtensionExecutionError(f"extension integrity check failed: {exc}") from exc
        record = self.registry.get_record(extension_id)
        admission = self.registry.read_admission(extension_id)
        if record is None or admission is None:
            raise ExtensionExecutionError("extension is not Kernel-authorized")
        if record.get("authority") != "kernel_grant":
            raise ExtensionExecutionError("extension has no Kernel-granted authority")
        return manifest, record, admission

    async def _execute_authorized(
        self,
        extension_id,
        manifest,
        record,
        admission,
        *,
        operation: str,
        protocol: str,
        capability: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> ExtensionExecutionResult:
        if not idempotency_key.strip():
            raise ExtensionExecutionError("idempotency key is required")
        if not isinstance(arguments, dict):
            raise ExtensionExecutionError("tool arguments must be an object")
        adapter = self.adapters.get(protocol)
        if adapter is None:
            raise ExtensionExecutionError(
                f"no governed executor is registered for protocol: {protocol}"
            )
        granted = set(record.get("granted_capabilities") or ())
        if capability not in granted:
            raise ExtensionExecutionError(
                f"Kernel has not granted required capability: {capability}"
            )
        assert manifest.provenance is not None
        parameter_hash = _digest(arguments)
        executor = str(manifest.kernel_projection().get("executor") or "")
        operation_material = {
            "extension_id": extension_id,
            "content_digest": manifest.provenance.digest,
            "operation": operation,
            "parameter_hash": parameter_hash,
            "idempotency_key_digest": _digest(idempotency_key),
        }
        operation_id = f"extension-operation-{_digest(operation_material)[7:31]}"
        capability_request = next(
            item for item in manifest.capabilities if item.capability == capability
        )
        execution_request = {
            "schema_version": 1,
            "operation_id": operation_id,
            "extension_id": extension_id,
            "content_digest": manifest.provenance.digest,
            "authorization_receipt_id": str(admission.get("receipt_id") or ""),
            "capability": capability,
            "operation": operation,
            "parameter_hash": parameter_hash,
            "executor": executor,
            "scope": list(capability_request.scope),
        }
        try:
            raw_permit = await self.kernel.authorize_extension_execution(
                execution_request,
                f"extension:{extension_id}:{manifest.provenance.digest}:execute:{idempotency_key}",
            )
        except Exception as exc:
            raise ExtensionExecutionError(
                f"Kernel execution authorization unavailable or denied: {exc}"
            ) from exc
        permit = _validate_permit(raw_permit, execution_request)
        permit_id = str(permit["permit_id"])
        invocation = ExtensionInvocation(
            extension_id=extension_id,
            content_digest=manifest.provenance.digest,
            operation=operation,
            protocol=protocol,
            capability=capability,
            scope=capability_request.scope,
            arguments=dict(arguments),
            package_root=(
                self.registry.objects
                / manifest.provenance.digest.removeprefix("sha256:")
                / "package"
            ),
        )
        try:
            self.registry.claim_execution(
                extension_id,
                operation_id,
                {
                    "schema": "nous.extension-execution-claim/v1",
                    "state": "claimed",
                    "operation_id": operation_id,
                    "permit_id": permit_id,
                    "content_digest": manifest.provenance.digest,
                    "input_digest": parameter_hash,
                },
            )
        except (OSError, ValueError) as exc:
            raise ExtensionExecutionError(str(exc)) from exc
        started = time.monotonic()
        started_at_us = time.time_ns() // 1_000
        try:
            adapter_result = await adapter.execute(invocation, permit_id=permit_id)
        except Exception as exc:
            adapter_result = AdapterResult(
                success=False,
                error_code=type(exc).__name__,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        if not isinstance(adapter_result, AdapterResult):
            raise ExtensionExecutionError("governed executor returned an invalid result")
        if adapter_result.verification_status not in {
            "unverified_executor_report",
            "protocol_and_schema_validated",
            "independently_verified",
        }:
            raise ExtensionExecutionError(
                "governed executor returned an invalid verification status"
            )
        finished_at_us = time.time_ns() // 1_000
        output_digest = _digest(adapter_result.output)
        result = "succeeded" if adapter_result.success else "failed"
        receipt = ExtensionExecutionReceipt(
            schema_version=1,
            receipt_id=f"extension-execution-{operation_id.removeprefix('extension-operation-')}",
            operation_id=operation_id,
            permit_id=permit_id,
            actor=str(permit["actor"]),
            source={
                "type": "extension",
                "id": extension_id,
                "digest": manifest.provenance.digest,
            },
            target={"protocol": protocol, "operation": operation},
            extension_id=extension_id,
            content_digest=manifest.provenance.digest,
            operation=invocation.operation,
            capability=capability,
            requested_capabilities=tuple(
                item.capability for item in manifest.capabilities
            ),
            granted_capabilities=tuple(
                str(item) for item in record.get("granted_capabilities") or ()
            ),
            input_digest=parameter_hash,
            parameter_hash=parameter_hash,
            success=adapter_result.success,
            result=result,
            policy_version=str(permit["policy_version"]),
            executor=executor,
            started_at_us=started_at_us,
            finished_at_us=finished_at_us,
            effect_digest=_digest(
                {
                    "operation_id": operation_id,
                    "result": result,
                    "output_digest": output_digest,
                    "error_code": adapter_result.error_code,
                    "verification_status": adapter_result.verification_status,
                }
            ),
            output_digest=output_digest,
            result_digest=output_digest,
            error_code=adapter_result.error_code,
            duration_ms=adapter_result.duration_ms
            or int((time.monotonic() - started) * 1000),
            output_bytes=adapter_result.output_bytes,
            verification_status=adapter_result.verification_status,
        )
        self.registry.record_execution_receipt(extension_id, receipt.to_dict())
        self.registry.complete_execution_claim(
            extension_id, operation_id, receipt.receipt_id
        )
        if not receipt.success:
            raise ExtensionExecutionError(
                f"extension execution failed ({receipt.error_code or 'EXECUTOR_FAILURE'}); "
                f"receipt={receipt.receipt_id}"
            )
        return ExtensionExecutionResult(adapter_result.output, receipt)


def _execution_capability(protocol: str, effect: str) -> str:
    if protocol == "python-plugin":
        return "process.execute"
    if protocol in {"openapi", "mcp"}:
        return "network.connect"
    return {
        "read": "filesystem.read",
        "write": "filesystem.write",
        "execute": "process.execute",
        "network": "network.connect",
    }.get(effect, "tool.invoke")


def _mcp_capability(manifest) -> str:
    if len(manifest.entry_points) != 1:
        raise ExtensionExecutionError(
            "MCP execution currently requires one normalized server"
        )
    return (
        "process.execute"
        if manifest.entry_points[0].kind == "process"
        else "network.connect"
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_permit(raw: Any, request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw.get("allowed"):
        raise ExtensionExecutionError("Kernel denied extension execution")
    for response_key, request_key in (
        ("operation_id", "operation_id"),
        ("extension_id", "extension_id"),
        ("content_digest", "content_digest"),
        ("authorization_receipt_id", "authorization_receipt_id"),
        ("capability", "capability"),
        ("operation", "operation"),
        ("parameter_hash", "parameter_hash"),
        ("executor", "executor"),
    ):
        if raw.get(response_key) != request[request_key]:
            raise ExtensionExecutionError(
                f"Kernel execution permit binding mismatch: {response_key}"
            )
    permit_id = str(raw.get("permit_id") or "")
    if not permit_id:
        raise ExtensionExecutionError("Kernel execution permit is missing its identifier")
    if not str(raw.get("actor") or "").strip():
        raise ExtensionExecutionError("Kernel execution permit is missing its actor")
    if not str(raw.get("policy_version") or "").strip():
        raise ExtensionExecutionError("Kernel execution permit is missing its policy version")
    if int(raw.get("issued_at_us") or 0) <= 0:
        raise ExtensionExecutionError("Kernel execution permit has an invalid timestamp")
    return raw

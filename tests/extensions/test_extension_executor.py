from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import validate

from nous_runtime.extensions.admission import ExtensionAdmissionService
from nous_runtime.extensions.executor import (
    AdapterResult,
    ExtensionExecutionError,
    UnifiedExtensionExecutor,
)
from nous_runtime.extensions.permissions import ExtensionPermissionService
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.store import GovernanceStore


def make_openapi(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Execution Service", "version": "1.0.0"},
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {
                    "/items/{id}": {
                        "get": {
                            "operationId": "getItem",
                            "parameters": [
                                {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string"},
                                }
                            ],
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def decision_for(request: dict, grants=(), receipt="admission-execution") -> dict:
    requested = [item["capability"] for item in request["capability_requests"]]
    return {
        "admitted": True,
        "extension_id": request["extension_id"],
        "normalized_digest": request["content_digest"],
        "requested_capabilities": requested,
        "granted_capabilities": list(grants),
        "denied_capabilities": [],
        "approval_required": len(grants) != len(requested),
        "executor_constraints": {
            "authority": "kernel_grant" if grants else "none",
            "executor": request["executor"],
        },
        "scope_constraints": {
            item["capability"]: item["scope"]
            for item in request["capability_requests"]
        },
        "policy_version": "extension-authorization-v1",
        "decision_reason": "fixture",
        "receipt_id": receipt,
    }


class FakeKernel:
    def __init__(self):
        self.execution_calls = []
        self.mutate_permit = None

    async def admit_extension(self, admission, idempotency_key=""):
        return decision_for(admission)

    async def authorize_extension(self, authorization, idempotency_key=""):
        return decision_for(
            authorization["admission"],
            authorization["approved_capabilities"],
            "authorization-execution",
        )

    async def authorize_extension_execution(self, execution, idempotency_key=""):
        self.execution_calls.append((execution, idempotency_key))
        permit = {
            "allowed": True,
            "operation_id": execution["operation_id"],
            "actor": "test-principal",
            "extension_id": execution["extension_id"],
            "content_digest": execution["content_digest"],
            "authorization_receipt_id": execution["authorization_receipt_id"],
            "capability": execution["capability"],
            "operation": execution["operation"],
            "parameter_hash": execution["parameter_hash"],
            "executor": execution["executor"],
            "policy_version": "extension-execution-v1",
            "decision_reason": "fixture",
            "issued_at_us": 1,
            "permit_id": "extension-permit-fixture",
        }
        return self.mutate_permit(permit) if self.mutate_permit else permit


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result or AdapterResult(True, {"value": "ok"}, output_bytes=14)
        self.error = error
        self.calls = []

    async def execute(self, invocation, *, permit_id):
        self.calls.append((invocation, permit_id))
        if self.error:
            raise self.error
        return self.result


def authorized_executor(tmp_path: Path, adapter: FakeAdapter):
    source = tmp_path / "openapi.json"
    make_openapi(source)
    registry = ExtensionRegistry(tmp_path / "registry")
    extension_id = registry.install(source).extension_id
    kernel = FakeKernel()
    admission = ExtensionAdmissionService(registry, kernel)
    asyncio.run(admission.admit(extension_id))
    permissions = ExtensionPermissionService(
        registry,
        admission,
        ApprovalBroker(GovernanceStore(tmp_path / "governance")),
    )
    context = AuthorizationContext(
        subject_type="user",
        subject_id="local-user",
        authn_method="cli_os_user",
        authn_confidence=1.0,
    )
    _, request = permissions.request(extension_id, context)
    asyncio.run(permissions.approve(extension_id, request.request_id, "admin"))
    return (
        registry,
        kernel,
        extension_id,
        UnifiedExtensionExecutor(registry, kernel, {"openapi": adapter}),
    )


def test_unified_executor_requires_parameter_bound_kernel_permit(tmp_path: Path):
    adapter = FakeAdapter()
    registry, kernel, extension_id, executor = authorized_executor(tmp_path, adapter)
    result = asyncio.run(
        executor.execute_tool(
            extension_id, "getItem", {"id": "42"}, idempotency_key="call-1"
        )
    )
    assert result.output == {"value": "ok"}
    request, key = kernel.execution_calls[0]
    assert request["capability"] == "network.connect"
    assert request["scope"] == ["api.example.test"]
    assert request["parameter_hash"].startswith("sha256:")
    assert "call-1" in key
    assert adapter.calls[0][1] == "extension-permit-fixture"
    receipt_path = (
        registry.objects
        / request["content_digest"].removeprefix("sha256:")
        / "executions"
        / f"{result.receipt.receipt_id}.json"
    )
    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_schema = json.loads(
        (
            Path(__file__).parents[2]
            / "spec"
            / "extensions"
            / "v1"
            / "extension-operation-receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    validate(stored, receipt_schema)
    assert stored["success"] is True
    assert stored["actor"] == "test-principal"
    assert stored["operation_id"].startswith("extension-operation-")
    assert stored["requested_capabilities"] == ["network.connect"]
    assert stored["granted_capabilities"] == ["network.connect"]
    assert stored["policy_version"] == "extension-execution-v1"
    assert stored["result"] == "succeeded"
    assert stored["started_at_us"] <= stored["finished_at_us"]
    assert stored["effect_digest"].startswith("sha256:")
    assert stored["verification_status"] == "unverified_executor_report"
    assert "output" not in stored

    with pytest.raises(ExtensionExecutionError, match="already claimed"):
        asyncio.run(
            executor.execute_tool(
                extension_id, "getItem", {"id": "42"}, idempotency_key="call-1"
            )
        )
    assert len(adapter.calls) == 1


def test_tampered_kernel_permit_never_reaches_adapter(tmp_path: Path):
    adapter = FakeAdapter()
    _, kernel, extension_id, executor = authorized_executor(tmp_path, adapter)
    kernel.mutate_permit = lambda permit: {**permit, "operation": "other"}
    with pytest.raises(ExtensionExecutionError, match="binding mismatch"):
        asyncio.run(
            executor.execute_tool(
                extension_id, "getItem", {"id": "42"}, idempotency_key="call-2"
            )
        )
    assert adapter.calls == []


def test_invalid_adapter_verification_status_is_rejected(tmp_path: Path):
    adapter = FakeAdapter(
        AdapterResult(True, {"value": "ok"}, verification_status="verified-by-claim")
    )
    _, _, extension_id, executor = authorized_executor(tmp_path, adapter)
    with pytest.raises(ExtensionExecutionError, match="verification status"):
        asyncio.run(
            executor.execute_tool(
                extension_id, "getItem", {"id": "42"}, idempotency_key="bad-status"
            )
        )


def test_executor_failure_produces_failure_receipt(tmp_path: Path):
    adapter = FakeAdapter(error=TimeoutError("private details"))
    registry, _, extension_id, executor = authorized_executor(tmp_path, adapter)
    with pytest.raises(ExtensionExecutionError, match="TimeoutError") as failed:
        asyncio.run(
            executor.execute_tool(
                extension_id, "getItem", {"id": "42"}, idempotency_key="call-3"
            )
        )
    receipt_id = str(failed.value).split("receipt=", 1)[1]
    manifest = registry.get(extension_id)
    path = (
        registry.objects
        / manifest.provenance.digest.removeprefix("sha256:")
        / "executions"
        / f"{receipt_id}.json"
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["success"] is False
    assert stored["error_code"] == "TimeoutError"
    assert "private details" not in path.read_text(encoding="utf-8")


def test_unapproved_extension_cannot_request_execution_permit(tmp_path: Path):
    source = tmp_path / "openapi.json"
    make_openapi(source)
    registry = ExtensionRegistry(tmp_path / "registry")
    extension_id = registry.install(source).extension_id
    kernel = FakeKernel()
    asyncio.run(ExtensionAdmissionService(registry, kernel).admit(extension_id))
    adapter = FakeAdapter()
    executor = UnifiedExtensionExecutor(registry, kernel, {"openapi": adapter})
    with pytest.raises(ExtensionExecutionError, match="no Kernel-granted authority"):
        asyncio.run(
            executor.execute_tool(
                extension_id, "getItem", {"id": "42"}, idempotency_key="call-4"
            )
        )
    assert kernel.execution_calls == []
    assert adapter.calls == []

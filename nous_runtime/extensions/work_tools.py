"""Bind reviewed extension tools to the existing Work catalog and executor."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import os
from pathlib import Path
from typing import Any

from nous_runtime.extensions.executor import UnifiedExtensionExecutor
from nous_runtime.extensions.models import ToolSpec
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.events import RunState


class WorkExtensionTools:
    """No discovery egress, package execution, or authority creation at startup."""

    def __init__(self, root: Path, snapshot, *, executor=None):
        self.registry = ExtensionRegistry(root / ".nous" / "extensions")
        self.snapshot = snapshot
        self.executor = executor
        self._work_reader = None
        self.bindings: dict[str, tuple[str, str]] = {}
        self.tool_ids: dict[tuple[str, str], str] = {}

    def register(self, catalog) -> None:
        if bool(self.snapshot.execution_options.get("read_only", False)):
            return
        # Current authorization is rechecked on every invocation. An installed
        # package, its effect annotations, and an enabled flag are not authority.
        for record in self.registry.list():
            if (
                record.get("work_enabled") is not True
                or record.get("authority") != "kernel_grant"
            ):
                continue
            extension_id = record["extension_id"]
            try:
                self._register_package(catalog, record)
            except (OSError, ValueError, TypeError) as error:
                from nous_runtime.tools import ToolDefinition

                catalog.register(
                    ToolDefinition(
                        tool_id="extension_blocked_"
                        + hashlib.sha256(extension_id.encode()).hexdigest()[:16],
                        description=f"Extension {extension_id} is blocked: {str(error)[:256]}",
                        input_schema={"type": "object"},
                        category="extension",
                        effect_class="unknown",
                        availability="unavailable",
                        source=f"extension:{extension_id}",
                        approval_policy="kernel_required",
                        metadata={"authority": "none", "extension_id": extension_id},
                    ),
                    executor=None,
                )

    def _register_package(self, catalog, record):
        extension_id = record["extension_id"]
        manifest = self.registry.verify(extension_id)
        tools = list(manifest.tools)
        if manifest.source_format == "mcp-config":
            tools.extend(
                ToolSpec(**item)
                for item in self.registry.read_discovered_tools(extension_id)
            )
        tools = [
            replace(tool, effect="unknown")
            for tool in tools
            if tool.protocol in {"mcp", "openapi"}
        ]
        if tools:
            self.bindings[extension_id] = (record["digest"], record["version"])
            catalog.register_extension_tools(extension_id, tools, executor=self.execute)
            for item in catalog.discover():
                metadata = item.get("metadata", {})
                if metadata.get("extension_id") == extension_id:
                    self.tool_ids[(extension_id, metadata["source_tool_name"])] = item[
                        "tool_id"
                    ]

    def _current(self, extension_id: str) -> None:
        self.registry.verify(extension_id)
        record = self.registry.get_record(extension_id) or {}
        if (
            record.get("work_enabled") is not True
            or record.get("authority") != "kernel_grant"
            or (record.get("digest"), record.get("version"))
            != self.bindings.get(extension_id)
        ):
            raise PermissionError(
                "Extension disabled, revoked, removed or changed; reload its reviewed tools"
            )

    def execute(self, extension_id: str, name: str, arguments) -> dict[str, Any]:
        from nous_runtime.work.loop import AgentLoop
        from nous_runtime.work.runtime import WorkHarness

        self._current(extension_id)
        # Assembly and run/resume load different snapshots. Read the original
        # durable dispatch instead of the earlier component-factory snapshot.
        if self._work_reader is None:
            self._work_reader = WorkHarness(self.registry.root.parent.parent)
        current = self._work_reader.require(self.snapshot.run_id)
        action = current.pending_action or {}
        if (
            current.state is not RunState.EXECUTING
            or bool(current.execution_options.get("read_only", False))
            or current.terminal
            or not action
            or not self.snapshot.run_id
            or type(action.get("action_sequence")) is not int
            or action["action_sequence"] < 1
            or action.get("tool") != self.tool_ids.get((extension_id, name))
            or action.get("arguments_digest") != AgentLoop._arguments_digest(arguments)
        ):
            raise PermissionError("An original dispatched Work action is required")
        key = f"work:{self.snapshot.run_id}:action:{action['action_sequence']}"
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "Synchronous Work tools must run on the existing Work worker"
            )
        try:
            result = asyncio.run(
                self._invoke(extension_id, name, dict(arguments), key, dict(action))
            )
        except Exception as error:
            # A claim may already exist. Keep the original Work unresolved; never
            # create another key or silently replay a potentially completed call.
            # PermissionError can come from receipt persistence after an effect.
            return {
                "ok": False,
                "state": "UNKNOWN",
                "recovery_required": True,
                "error": str(error),
                "extension_id": extension_id,
            }
        receipt = result.receipt.to_dict()
        return {
            "ok": result.receipt.success,
            "result": result.output,
            "extension_id": extension_id,
            "tool": name,
            "receipt": receipt,
            "recovery_required": not result.receipt.success,
            "verification": result.receipt.verification_status,
        }

    async def _invoke(self, extension_id, name, arguments, key, original_action):
        def before_execute():
            self._current(extension_id)
            current = self._work_reader.require(self.snapshot.run_id)
            if (
                current.state is not RunState.EXECUTING
                or current.pending_action != original_action
                or bool(current.execution_options.get("read_only", False))
            ):
                raise PermissionError(
                    "Original Work action changed or stopped before execution"
                )

        if self.executor is not None:
            self._current(extension_id)
            return await self.executor.execute_tool(
                extension_id,
                name,
                arguments,
                idempotency_key=key,
                before_execute=before_execute,
            )
        from compat.nki_client import DEFAULT_ENDPOINT, NKIClient
        from nous_runtime.extensions.mcp_sdk import McpSdkExecutionAdapter
        from nous_runtime.extensions.openapi import OpenApiExecutionAdapter

        client = await asyncio.wait_for(
            NKIClient.connect(
                os.environ.get("NOUS_KERNEL_ENDPOINT", DEFAULT_ENDPOINT),
                principal_id="agent.apeir.work",
            ),
            timeout=10,
        )
        try:
            self._current(extension_id)
            executor = UnifiedExtensionExecutor(
                self.registry,
                client,
                {
                    "mcp": McpSdkExecutionAdapter(),
                    "openapi": OpenApiExecutionAdapter(),
                },
            )
            return await executor.execute_tool(
                extension_id,
                name,
                arguments,
                idempotency_key=key,
                before_execute=before_execute,
            )
        finally:
            await client.close()


def register_work_extensions(catalog, root, snapshot) -> None:
    WorkExtensionTools(Path(root), snapshot).register(catalog)


def work_extension_records(root: Path) -> dict[str, Any]:
    """Read installed metadata only; enabled does not assert live executability."""
    registry = ExtensionRegistry(root / ".nous" / "extensions")
    records, diagnostics = [], []
    for record in registry.list():
        extension_id = record["extension_id"]
        try:
            manifest = registry.verify(extension_id)
            if not manifest.tools and manifest.source_format != "mcp-config":
                continue
            if len(records) >= 64:
                raise ValueError("Work extension view exceeds 64 packages")
            tools = list(manifest.tools)
            if manifest.source_format == "mcp-config":
                tools.extend(
                    ToolSpec(**item)
                    for item in registry.read_discovered_tools(extension_id)
                )
            supported = [tool for tool in tools if tool.protocol in {"mcp", "openapi"}]
            records.append(
                {
                    "extension_id": extension_id,
                    "version": record["version"],
                    "digest": record["digest"],
                    "enabled": record.get("work_enabled", False),
                    "state": record["state"],
                    "authority": record.get("authority", "none"),
                    "status": "REVOKED"
                    if record["state"] == "revoked"
                    else "NEEDS_AUTHORIZATION"
                    if record.get("authority") != "kernel_grant"
                    else "NEEDS_DISCOVERY"
                    if not tools
                    else "UNSUPPORTED"
                    if not supported
                    else "KERNEL_CHECK_REQUIRED"
                    if record.get("work_enabled")
                    else "DISABLED",
                    "tools": [
                        {"name": tool.name, "protocol": tool.protocol}
                        for tool in supported[:128]
                    ],
                    "verification": "NOT_PHYSICAL_VERIFICATION",
                }
            )
        except (ValueError, TypeError, OSError) as error:
            diagnostics.append(
                {
                    "extension_id": extension_id,
                    "state": "BLOCKED",
                    "reason": str(error)[:256],
                }
            )
    return {"records": records, "diagnostics": diagnostics[:512]}

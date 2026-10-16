"""Official MCP transport over the existing authenticated Runtime HTTP owners.

The stdio bridge owns no Runtime state, identity store, approval or worker.
Runtime HTTP authenticates every call and applies current Governance. Tool
discovery is not permission. The initial Work surface is bounded and read-only.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit

from nous_runtime.api.responses import err_response, ok_response
from nous_runtime.core.redaction import redact_sensitive_data, register_sensitive_value

_TOOLS = frozenset(
    {
        "apeir.nodes.list",
        "apeir.devices.inspect",
        "apeir.work.submit",
        "apeir.work.status",
        "apeir.evidence.read",
    }
)
_MAX_RESPONSE = 1_048_576


def _identifier(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9_.:-]{1,192}", value) is None
    ):
        raise ValueError("A bounded original resource identifier is required")
    return value


def _scope_request(context, tool, resource):
    from nous_runtime.governance.permission import PermissionRequest

    return PermissionRequest(
        context.subject_id,
        tool,
        resource,
        {
            "subject_type": context.subject_type,
            "locality": context.session_locality,
            "device": context.session_device,
            "action_type": "mcp.call",
        },
    )


def _admit(gate, context, tool, resource, arguments):
    from nous_runtime.compat.capability import get_capability, register_capability
    from nous_runtime.governance import ActionProposal

    if context is None or context.subject_type != "service":
        raise PermissionError("An authenticated service identity is required")
    if gate.permission_engine is None:
        raise PermissionError("Explicit current MCP scope policy is required")
    if not gate.permission_engine.check(
        _scope_request(context, tool, resource)
    ).allowed:
        raise PermissionError("Current MCP resource scope is denied")
    if get_capability(tool) is None:
        register_capability(
            tool,
            category="software",
            executor_type="runtime",
            side_effect_class="local_write"
            if tool == "apeir.work.submit"
            else "read_only",
            reversibility="partially_reversible"
            if tool == "apeir.work.submit"
            else "reversible",
            model_uncertainty=0.0,
            idempotent=True,
        )
    decision = gate.evaluate(
        ActionProposal(
            action_type="mcp.call",
            capability_id=tool,
            params={
                "arguments_sha256": hashlib.sha256(
                    json.dumps(arguments, sort_keys=True, allow_nan=False).encode()
                ).hexdigest()
            },
            affected_resources=(resource,),
            required_permissions=(tool,),
            side_effect_class="local_write"
            if tool == "apeir.work.submit"
            else "read_only",
            reversibility="partially_reversible"
            if tool == "apeir.work.submit"
            else "reversible",
            retry_behavior="idempotent",
            data_classification="internal",
            created_at="",
        ),
        context,
    )
    if decision.action_mode != "EXECUTE" or decision.allowed is not True:
        raise PermissionError("Governance did not admit the MCP request")
    return decision


def handle_mcp_call(body, *, authorization_context=None):
    """Called only through the existing Runtime HTTP authentication boundary."""
    audit_gate = None
    resource = ""
    tool = ""
    try:
        if not isinstance(body, dict) or set(body) != {"tool", "arguments"}:
            raise ValueError("Only tool and arguments are accepted")
        tool, arguments = body["tool"], body["arguments"]
        if tool not in _TOOLS or not isinstance(arguments, dict):
            raise ValueError("Unsupported MCP tool or arguments")
        if (
            authorization_context is None
            or authorization_context.subject_type != "service"
        ):
            raise PermissionError("MCP cannot acquire human authority")
        # This authenticated execution boundary already owns the configured
        # service credential. Protect it in the existing matcher memory, never
        # ordinary tool arguments, Work, audit or returned provider errors.
        credential = os.environ.get("NOUS_API_TOKEN") or os.environ.get(
            "NOUS_AUTH_TOKEN"
        )
        if credential:
            register_sensitive_value(credential)
        if redact_sensitive_data(arguments) != arguments:
            raise ValueError("Sensitive material is not ordinary MCP input")
        from nous_runtime.control_plane.operations import get_operations
        from nous_runtime.governance import get_gate
        from nous_runtime.api.desktop_routes import (
            _workspace,
            handle_work_inspect,
            handle_work_submit,
        )
        from pathlib import Path

        root = Path(_workspace()).resolve()
        plane = get_operations()
        gate = get_gate()
        if (
            plane.root != root
            or Path(plane.gate.store.db_path).resolve()
            != Path(gate.store.db_path).resolve()
        ):
            raise PermissionError("Runtime workspace authority differs")
        audit_gate = gate
        if tool == "apeir.nodes.list":
            if arguments:
                raise ValueError("Node listing takes no target overrides")
            resource = "workspace:" + hashlib.sha256(str(root).encode()).hexdigest()
        elif tool == "apeir.devices.inspect":
            if set(arguments) != {"device_id"}:
                raise ValueError("Only device_id is accepted")
            resource = "device:" + _identifier(arguments["device_id"])
        elif tool == "apeir.work.submit":
            if set(arguments) != {"objective", "idempotency_key"}:
                raise ValueError("Only objective and idempotency_key are accepted")
            objective = arguments["objective"]
            if (
                not isinstance(objective, str)
                or not objective.strip()
                or len(objective) > 8192
            ):
                raise ValueError("A nonempty bounded objective is required")
            if redact_sensitive_data(objective) != objective:
                raise ValueError("Sensitive material is not ordinary Work input")
            key = arguments["idempotency_key"]
            if (
                not isinstance(key, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", key) is None
            ):
                raise ValueError("A bounded original idempotency_key is required")
            resource = "workspace:" + hashlib.sha256(str(root).encode()).hexdigest()
        else:
            if set(arguments) not in ({"run_id"}, {"run_id", "owner"}):
                raise ValueError("Only the original run_id and owner are accepted")
            owner = arguments.get("owner", "work-harness")
            if owner not in {"work-harness", "distributed"}:
                raise ValueError("An explicit canonical Work owner is required")
            resource = (
                "work:" if owner == "work-harness" else "distributed-work:"
            ) + _identifier(arguments["run_id"])
        decision = _admit(gate, authorization_context, tool, resource, arguments)
        if tool == "apeir.nodes.list":
            result = ok_response(
                {"nodes": plane.controller().controller_status()["nodes"]}
            )
        elif tool == "apeir.devices.inspect":
            from nous_runtime.reality import DeviceRegistry

            device = DeviceRegistry(plane.device_state).get(arguments["device_id"])
            if device is None:
                return err_response("NOUS_NOT_FOUND", "Device is not registered")
            result = ok_response({"device": device.to_dict()})
        elif tool == "apeir.work.submit":
            from nous_runtime.api.routes import _authorize_mutation_route

            request = {**arguments, "read_only": True, "max_iterations": 8}
            # MCP scope permits proposing bounded Work, never approving it.
            # Preserve the original API mutation Gate and its human approval.
            result = _authorize_mutation_route(
                "POST",
                "/api/v1/work",
                request,
                {},
                authorization_context,
                surface="api",
            )
            if result is None:
                # Approval is not a replacement for current MCP scope. The
                # original mutation Gate may have waited or reloaded policy.
                if not gate.permission_engine.check(
                    _scope_request(authorization_context, tool, resource)
                ).allowed:
                    raise PermissionError("MCP scope changed before Work submission")
                result = handle_work_submit(
                    request, authorization_context=authorization_context
                )
        elif arguments.get("owner", "work-harness") == "distributed":
            controller = plane.controller()
            work = (
                controller.work_store.get(arguments["run_id"])
                if controller.work_store is not None
                else None
            )
            if work is None:
                return err_response(
                    "NOUS_NOT_FOUND", "Original Distributed Work is absent"
                )
            if tool == "apeir.evidence.read":
                result = ok_response(
                    {
                        "run_id": work.work_id,
                        "owner": "distributed",
                        "state": work.state.value,
                        "artifacts": list(work.output_artifacts),
                        "evidence_refs": list(work.evidence_refs),
                        "result_summary": dict(work.result_summary),
                        "effect_verification": dict(work.effect_verification),
                        "provenance": dict(work.provenance),
                        "authority": "DistributedWorkStore",
                        "receipt_is_observation": False,
                    }
                )
            else:
                result = ok_response({"work": work.to_dict(), "owner": "distributed"})
        else:
            if not (root / ".nous" / "checkpoints.db").is_file():
                return err_response(
                    "NOUS_NOT_FOUND", "Original Work checkpoint is absent"
                )
            result = handle_work_inspect(arguments["run_id"])
            if result.get("ok") and tool == "apeir.evidence.read":
                from nous_runtime.events import EventStream

                events = EventStream(str(root)).load_events(arguments["run_id"])
                work = result["data"]["work"]
                result = ok_response(
                    {
                        "run_id": arguments["run_id"],
                        "state": work["state"],
                        "artifacts": work["artifacts"],
                        "observations": work["observations"],
                        "events": [
                            {
                                "event_id": e.event_id,
                                "event_type": e.event_type,
                                "sequence": e.sequence,
                            }
                            for e in events[-128:]
                        ],
                        "events_partial": len(events) > 128,
                        "authority": "WorkHarness checkpoint + EventStream",
                        "receipt_is_observation": False,
                    }
                )
        if not gate.permission_engine.check(
            _scope_request(authorization_context, tool, resource)
        ).allowed:
            raise PermissionError("MCP scope changed before result delivery")
        with gate.store.operation_transaction() as db:
            gate.store.append_operation_audit(
                db,
                "mcp.call.result",
                {
                    "tool": tool,
                    "resource_id": resource,
                    "actor_id": authorization_context.subject_id,
                    "authorization_context_id": authorization_context.context_id,
                    "decision_id": decision.decision_id,
                    "ok": result.get("ok") is True,
                    "work_id": ((result.get("data") or {}).get("work") or {}).get(
                        "run_id", arguments.get("run_id", "")
                    ),
                },
            )
        safe = redact_sensitive_data(result)
        if len(json.dumps(safe).encode()) > _MAX_RESPONSE:
            return err_response(
                "MCP_OUTPUT_LIMIT",
                "Inspect the original Runtime record; result exceeds the MCP bound",
            )
        return safe
    except PermissionError:
        if audit_gate is not None:
            try:
                with audit_gate.store.operation_transaction() as db:
                    audit_gate.store.append_operation_audit(
                        db,
                        "mcp.call.denied",
                        {
                            "tool": tool,
                            "resource_id": resource,
                            "actor_id": authorization_context.subject_id,
                            "authorization_context_id": authorization_context.context_id,
                        },
                    )
            except Exception:
                return err_response(
                    "MCP_BACKEND_UNAVAILABLE", "Denied MCP request audit is unavailable"
                )
        return err_response(
            "NOUS_FORBIDDEN",
            "Current service identity, resource scope or Governance admission is denied",
        )
    except (ValueError, TypeError):
        return err_response(
            "NOUS_INVALID_REQUEST", "Invalid MCP tool arguments or original binding"
        )
    except Exception:
        return err_response(
            "MCP_BACKEND_UNAVAILABLE",
            "Original Runtime evidence is unavailable; do not assume success or replay effects",
        )


def create_mcp_server(runtime_url, token):
    """Build the official stdio server; credentials travel only to one origin."""
    import anyio
    import httpx2
    from mcp.server import MCPServer
    from mcp.types import CallToolResult, TextContent, ToolAnnotations

    if not isinstance(runtime_url, str) or not isinstance(token, str):
        raise ValueError("Controller origin and credential must be strings")
    try:
        parts = urlsplit(runtime_url)
        port = parts.port
    except ValueError:
        raise ValueError("Controller origin is invalid") from None
    try:
        loopback = ipaddress.ip_address(parts.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or (parts.scheme == "http" and not loopback)
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or port == 0
        or any(ord(c) < 33 or ord(c) == 127 for c in runtime_url)
        or "\\" in runtime_url
        or not token
        or token.startswith("hums_")
    ):
        raise ValueError(
            "A trusted Controller origin and delegated service credential are required"
        )
    register_sensitive_value(token)
    endpoint = runtime_url.rstrip("/") + "/api/v1/mcp/call"

    async def forward(tool, arguments):
        if redact_sensitive_data(arguments) != arguments:
            result = err_response(
                "NOUS_INVALID_REQUEST", "Sensitive material is not ordinary MCP input"
            )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structured_content=result,
                is_error=True,
            )
        try:
            # A per-read timeout alone does not bound a stalled/dripping reply.
            # Cancellation closes this request; it never cancels or reissues the
            # original Runtime Work that may already have been admitted.
            with anyio.fail_after(10):
                async with httpx2.AsyncClient(
                    follow_redirects=False, timeout=10, trust_env=True
                ) as client:
                    async with client.stream(
                        "POST",
                        endpoint,
                        json={"tool": tool, "arguments": arguments},
                        headers={
                            "Authorization": "Bearer " + token,
                            "Accept-Encoding": "identity",
                        },
                    ) as response:
                        if 300 <= response.status_code < 400:
                            raise ValueError(
                                "Controller redirects are not credential delegation"
                            )
                        if (
                            response.headers.get("Content-Encoding", "identity").lower()
                            != "identity"
                        ):
                            raise ValueError(
                                "Compressed Runtime responses are not admitted"
                            )
                        raw = bytearray()
                        async for chunk in response.aiter_raw(chunk_size=65536):
                            raw.extend(chunk)
                            if len(raw) > _MAX_RESPONSE:
                                raise ValueError("MCP response exceeds its bound")
                        result = json.loads(raw)
                        if not isinstance(result, dict) or not isinstance(
                            result.get("ok"), bool
                        ):
                            raise ValueError("Invalid Runtime response")
                        if not 200 <= response.status_code < 300 and result["ok"]:
                            raise ValueError(
                                "HTTP failure cannot certify a successful tool"
                            )
            result = redact_sensitive_data(result)
        except (httpx2.HTTPError, TimeoutError, OSError, ValueError, RecursionError):
            result = err_response(
                "MCP_RESPONSE_UNKNOWN",
                "Query original Work evidence; this transport never retries a submission",
            )
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))],
            structured_content=result,
            is_error=result.get("ok") is not True,
        )

    from nous_runtime._version import __version__

    server = MCPServer("APEIR Runtime", version=__version__)
    read = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True
    )

    @server.tool(name="apeir.nodes.list", annotations=read)
    async def nodes_list():
        """Read canonical Node/trust/connection facts for the authorized workspace."""
        return await forward("apeir.nodes.list", {})

    @server.tool(name="apeir.devices.inspect", annotations=read)
    async def device_inspect(device_id: str):
        """Inspect one registered Device by stable ID; this is not a fresh physical observation."""
        return await forward("apeir.devices.inspect", {"device_id": device_id})

    @server.tool(
        name="apeir.work.submit",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    async def work_submit(objective: str, idempotency_key: str):
        """Propose bounded read-only Work; original human approval is still required.

        Reuse the exact key and inputs after a lost response to query the original
        Work. Never invent a new key to blindly repeat an uncertain operation.
        """
        return await forward(
            "apeir.work.submit",
            {"objective": objective, "idempotency_key": idempotency_key},
        )

    @server.tool(name="apeir.work.status", annotations=read)
    async def work_status(
        run_id: str, owner: Literal["work-harness", "distributed"] = "work-harness"
    ):
        """Read original Work from its explicit owner; never resume or execute it."""
        return await forward("apeir.work.status", {"run_id": run_id, "owner": owner})

    @server.tool(name="apeir.evidence.read", annotations=read)
    async def evidence_read(
        run_id: str, owner: Literal["work-harness", "distributed"] = "work-harness"
    ):
        """Read original evidence/state references; receipts do not prove observed effects."""
        return await forward("apeir.evidence.read", {"run_id": run_id, "owner": owner})

    return server


def serve_mcp(runtime_url):
    token = os.environ.get("APEIR_MCP_API_TOKEN", "")
    server = create_mcp_server(runtime_url, token)
    asyncio.run(server.run_stdio_async())

"""Official MCP wire -> authenticated HTTP -> existing Runtime and Governance."""

import asyncio
import http.client
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from nous_runtime.api.server import create_server
from nous_runtime.control_plane.operations import OperationsPlane
from nous_runtime.extensions.mcp_server import create_mcp_server
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.reality import Device, DeviceRegistry
from nous_runtime.work import WorkSupervisor
from tests.work.test_work_submission import components

TOKEN = "fake.runtime.mcp.delegation"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_API_TOKEN", TOKEN)
    monkeypatch.setenv("NOUS_API_SUBJECT", "mcp-consumer")
    permissions = PermissionEngine((PermissionRule("mcp-consumer", "apeir.*", "*"),))
    permissions.add(
        PermissionRule(_build_context().subject_id, "governance.approve", "*")
    )
    gate = ExecutionAuthorizationGate(
        GovernanceStore(tmp_path / ".nous"), permission_engine=permissions
    )
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", gate)
    monkeypatch.setattr(
        "nous_runtime.governance.broker._broker", ApprovalBroker(gate.store)
    )
    relay = NodeRelayServer(state_dir=tmp_path / ".nous" / "relay")
    plane = OperationsPlane(tmp_path, gate=gate, controller=relay)
    monkeypatch.setattr("nous_runtime.control_plane.operations._operations", plane)
    DeviceRegistry(plane.device_state).register(
        Device("device-original", "fixture", "stable-original", "simulated")
    )
    calls = []
    supervisor = WorkSupervisor(tmp_path, component_factory=components(calls))
    monkeypatch.setattr("nous_runtime.work.get_work_supervisor", lambda *_: supervisor)
    server = create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def post(tool, arguments, token=TOKEN, **claims):
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        try:
            connection.request(
                "POST",
                "/api/v1/mcp/call",
                json.dumps({"tool": tool, "arguments": arguments, **claims}),
                {
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            return json.loads(response.read())
        finally:
            connection.close()

    try:
        yield dict(
            root=tmp_path,
            url=url,
            post=post,
            gate=gate,
            permissions=permissions,
            calls=calls,
            supervisor=supervisor,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        supervisor.close()
        assert not thread.is_alive()


def test_real_http_identity_scope_and_revocation(runtime):
    post, permissions = runtime["post"], runtime["permissions"]
    assert not post("apeir.nodes.list", {}, token="invalid")["ok"]
    assert post("apeir.nodes.list", {}) == {"ok": True, "data": {"nodes": []}}
    device = post("apeir.devices.inspect", {"device_id": "device-original"})
    assert device["ok"], device
    assert device["data"]["device"]["stable_identity"] == "stable-original"
    permissions.add(
        PermissionRule(
            "mcp-consumer", "apeir.devices.inspect", "device:device-original", "deny"
        )
    )
    assert not post("apeir.devices.inspect", {"device_id": "device-original"})["ok"]
    # Discovery cannot grant a missing scope, even when Governance exists.
    runtime["gate"].permission_engine = None
    assert not post("apeir.nodes.list", {})["ok"]


@pytest.mark.parametrize(
    "tool,arguments,claims",
    [
        ("apeir.approve", {}, {}),
        (
            "apeir.work.submit",
            {"objective": "Read", "idempotency_key": "same", "read_only": False},
            {},
        ),
        ("apeir.nodes.list", {"workspace": "/"}, {}),
        ("apeir.nodes.list", {}, {"authorization_context": {"subject_type": "user"}}),
        ("apeir.devices.inspect", {"device_id": "../outside"}, {}),
        ("apeir.work.submit", {"objective": "Read", "idempotency_key": ""}, {}),
    ],
)
def test_arguments_and_authority_claims_fail_closed(runtime, tool, arguments, claims):
    result = runtime["post"](tool, arguments, **claims)
    assert not result["ok"], result
    assert not runtime["calls"]


def test_submission_waits_for_real_approval_and_retries_original_only(runtime):
    post, gate = runtime["post"], runtime["gate"]
    request = {
        "objective": "Explain the original result",
        "idempotency_key": "original",
    }
    waiting = post("apeir.work.submit", request)
    assert not waiting["ok"], waiting
    assert waiting["error"]["code"] == "NOUS_APPROVAL_REQUIRED", waiting
    assert not runtime["calls"]
    ApprovalBroker(gate.store).respond_legacy(
        waiting["error"]["details"]["approval_request_id"],
        "approve",
        _build_context(),
        gate=gate,
    )
    admitted = post("apeir.work.submit", request)
    assert admitted["ok"], admitted
    run_id = admitted["data"]["work"]["run_id"]
    runtime["supervisor"].wait(run_id, timeout=5)
    repeated = post("apeir.work.submit", request)
    assert repeated["ok"] and repeated["data"]["work"]["run_id"] == run_id, repeated
    status = post("apeir.work.status", {"run_id": run_id})
    assert status["ok"] and status["data"]["work"]["run_id"] == run_id
    evidence = post("apeir.evidence.read", {"run_id": run_id})
    assert evidence["ok"], evidence
    assert evidence["data"]["receipt_is_observation"] is False
    assert evidence["data"]["events"]
    assert runtime["calls"] == [run_id]
    records = gate.store.operation_audit()
    assert any(row["event_type"] == "mcp.call.result" for row in records)
    assert TOKEN not in json.dumps(records)


def test_official_sdk_stdio_calls_actual_runtime_http(runtime):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    import tempfile

    error_log = tempfile.TemporaryFile(mode="w+")

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "nous_runtime.cli.main",
                "extension",
                "serve-mcp",
                "--runtime-url",
                runtime["url"],
            ],
            env={"PATH": os.environ["PATH"], "APEIR_MCP_API_TOKEN": TOKEN},
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        async with stdio_client(params, errlog=error_log) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                initialized = await client.initialize()
                assert initialized.server_info.name == "APEIR Runtime"
                listed = await client.list_tools()
                assert {tool.name for tool in listed.tools} == {
                    "apeir.nodes.list",
                    "apeir.devices.inspect",
                    "apeir.work.submit",
                    "apeir.work.status",
                    "apeir.evidence.read",
                }
                result = await client.call_tool(
                    "apeir.devices.inspect", {"device_id": "device-original"}
                )
                assert not result.is_error, result
                assert (
                    result.structured_content["data"]["device"]["stable_identity"]
                    == "stable-original"
                )
                denied = await client.call_tool(
                    "apeir.work.submit",
                    {"objective": "Explain state", "idempotency_key": "stdio-original"},
                )
                assert denied.is_error
                assert (
                    denied.structured_content["error"]["code"]
                    == "NOUS_APPROVAL_REQUIRED"
                )

    try:
        asyncio.run(scenario())
        error_log.seek(0)
        assert TOKEN not in error_log.read()
    finally:
        error_log.close()
    assert not runtime["calls"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "http://127.0.0.1:0",
        "https://user:password@example.test",
        "https://example.test/other",
        "https://example.test?token=x",
        "https://example.test#x",
        "https://example.test:bad",
        "https://example.test\\@127.0.0.1",
    ],
)
def test_credential_origin_is_fixed_and_validated(url):
    with pytest.raises(ValueError):
        create_mcp_server(url, TOKEN)


@pytest.mark.parametrize(
    "mode", ["redirect", "lost", "invalid", "http_failure", "oversize", "redact"]
)
def test_bridge_never_retries_or_forwards_credential_and_redacts_outputs(mode):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.path, self.headers.get("Authorization")))
            self.rfile.read(int(self.headers["Content-Length"]))
            if mode == "lost":
                self.close_connection = True
                return
            self.send_response(
                302 if mode == "redirect" else 503 if mode == "http_failure" else 200
            )
            if mode == "redirect":
                self.send_header("Location", "/credential-must-not-follow")
            payload = (
                b"not-json"
                if mode == "invalid"
                else b"x" * 1_048_577
                if mode == "oversize"
                else json.dumps(
                    {"ok": True, "data": {"provider_error": TOKEN}}
                ).encode()
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        bridge = create_mcp_server(f"http://127.0.0.1:{server.server_port}", TOKEN)
        result = asyncio.run(bridge.call_tool("apeir.nodes.list", {}))
        assert calls == [("/api/v1/mcp/call", "Bearer " + TOKEN)]
        assert TOKEN not in json.dumps(result.model_dump())
        if mode == "redact":
            assert not result.is_error
        else:
            assert result.is_error
            assert result.structured_content["error"]["code"] == "MCP_RESPONSE_UNKNOWN"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


def test_rotated_runtime_credential_and_changed_scope_do_not_reuse_trust(
    runtime, monkeypatch
):
    assert runtime["post"]("apeir.nodes.list", {})["ok"]
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.rotated.runtime.delegation")
    assert not runtime["post"]("apeir.nodes.list", {})["ok"]
    assert not runtime["calls"]


def test_distributed_work_is_read_from_explicit_existing_owner(runtime):
    from nous_runtime.node_runtime.distributed_work import (
        DistributedWork,
        DistributedWorkStore,
    )

    store = DistributedWorkStore(runtime["root"] / ".nous" / "relay")
    work = store.create(
        DistributedWork(intent="Bounded original read", creator="owner")
    )
    arguments = {"run_id": work.work_id, "owner": "distributed"}
    status = runtime["post"]("apeir.work.status", arguments)
    assert status["ok"] and status["data"]["work"] == work.to_dict(), status
    evidence = runtime["post"]("apeir.evidence.read", arguments)
    assert evidence["ok"] and evidence["data"]["authority"] == "DistributedWorkStore"
    assert evidence["data"]["state"] == "CREATED"
    assert evidence["data"]["effect_verification"] == {}
    assert not evidence["data"]["receipt_is_observation"]
    # No fallback to another owner and no execution or promotion to MATCH.
    absent = runtime["post"]("apeir.work.status", {"run_id": work.work_id})
    assert not absent["ok"]
    runtime["permissions"].add(
        PermissionRule(
            "mcp-consumer",
            "apeir.work.status",
            "distributed-work:" + work.work_id,
            "deny",
        )
    )
    assert not runtime["post"]("apeir.work.status", arguments)["ok"]
    assert any(
        row["event_type"] == "mcp.call.denied"
        for row in runtime["gate"].store.operation_audit()
    )
    assert not runtime["calls"]


def test_scope_revoked_during_original_work_admission_blocks_dispatch(
    runtime, monkeypatch
):
    post, gate = runtime["post"], runtime["gate"]
    request = {
        "objective": "Explain original scope",
        "idempotency_key": "revoked-at-admission",
    }
    waiting = post("apeir.work.submit", request)
    assert waiting["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    ApprovalBroker(gate.store).respond_legacy(
        waiting["error"]["details"]["approval_request_id"],
        "approve",
        _build_context(),
        gate=gate,
    )
    evaluate = gate.evaluate

    def revoke_before_dispatch(proposal, context):
        decision = evaluate(proposal, context)
        if proposal.capability_id == "runtime.execute" and decision.allowed:
            runtime["permissions"].add(
                PermissionRule("mcp-consumer", "apeir.work.submit", "*", "deny")
            )
        return decision

    monkeypatch.setattr(gate, "evaluate", revoke_before_dispatch)
    denied = post("apeir.work.submit", request)
    assert not denied["ok"]
    from nous_runtime.work.runtime import WorkHarness

    assert WorkHarness(runtime["root"]).list() == []
    assert not runtime["calls"]


def test_authenticated_credential_never_becomes_work_input(runtime, monkeypatch):
    import uuid

    fake_credential = "fake.mcp.opaque." + uuid.uuid4().hex
    monkeypatch.setenv("NOUS_API_TOKEN", fake_credential)
    result = runtime["post"](
        "apeir.work.submit",
        {"objective": "Process " + fake_credential, "idempotency_key": "original"},
        token=fake_credential,
    )
    assert not result["ok"] and result["error"]["code"] == "NOUS_INVALID_REQUEST"
    assert fake_credential not in json.dumps(result)
    assert fake_credential not in json.dumps(runtime["gate"].store.operation_audit())
    assert not runtime["calls"]


def test_cancelled_bridge_closes_transport_without_retry():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received = threading.Event()
    disconnected = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(self.path)
            received.set()
            self.connection.settimeout(5)
            try:
                if self.connection.recv(1) == b"":
                    disconnected.set()
            except OSError:
                pass
            self.close_connection = True

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        bridge = create_mcp_server(f"http://127.0.0.1:{server.server_port}", TOKEN)

        async def scenario():
            call = asyncio.create_task(bridge.call_tool("apeir.nodes.list", {}))
            try:
                assert await asyncio.to_thread(received.wait, 5)
                call.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call
                assert await asyncio.to_thread(disconnected.wait, 2)
            finally:
                if not call.done():
                    call.cancel()
                await asyncio.gather(call, return_exceptions=True)

        asyncio.run(scenario())
        assert calls == ["/api/v1/mcp/call"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()

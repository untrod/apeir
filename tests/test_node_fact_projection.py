"""Desktop compatibility views must use the signed Relay's Node facts."""

import json

import pytest

from nous_runtime.api.routes import (
    handle_get_node,
    handle_list_nodes,
    handle_scan_nodes,
)
from nous_runtime.control_plane import operations
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


@pytest.fixture
def node_plane(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    controller = NodeRelayServer(state_dir=tmp_path / "controller")
    node = NodeRuntimeService(NodeRuntimeConfig(tmp_path / "node"))
    controller.register_node(node.identity.node_id, node.identity.public_key)
    plane = operations.OperationsPlane(
        tmp_path,
        controller_state=controller.state_dir,
        controller=controller,
        gate=ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance")),
    )
    monkeypatch.setattr(operations, "_operations", plane)
    from nous_runtime.connectivity.control_plane.node_registry import NodeRegistry

    monkeypatch.setattr(
        NodeRegistry, "list_all", lambda: [{"node_id": "legacy-ghost", "is_online": 1}]
    )
    return plane, controller, node


def test_node_list_and_detail_share_the_canonical_identity(node_plane):
    _, controller, node = node_plane
    before = (controller.state_dir / "trusted-nodes.json").read_bytes()
    result = handle_list_nodes()
    assert result["ok"], result
    assert len(result["data"]) == 1
    (view,) = result["data"]
    assert view["node_id"] == view["id"] == node.identity.node_id
    assert view["public_key"] == node.identity.public_key
    assert view["trust_status"] == "TRUSTED"
    assert not view["online"]
    assert not view["schedulable"]
    assert view["source"] == "node_runtime.controller-status"
    assert (
        view["connectivity_state"]
        == controller.controller_status()["nodes"][0]["connectivity_state"]
    )
    assert handle_get_node(node.identity.node_id)["data"] == view
    assert (controller.state_dir / "trusted-nodes.json").read_bytes() == before
    assert handle_get_node("legacy-ghost")["ok"] is False


def test_revoked_node_cannot_be_revived_by_a_legacy_session(node_plane):
    plane, controller, node = node_plane
    controller.revoke_node(
        node.identity.node_id, admit=lambda _: {"subject_id": "fixture-human"}
    )
    for _ in range(2):
        (view,) = handle_list_nodes("revoked")["data"]
        assert view["trust_status"] == "REVOKED"
        assert view["online"] is False
        assert view["status"] == "revoked"
        assert view["schedulable"] is False
        # A reopened Operations owner reads the same trust journal, not old SQL.
        plane.live_controller = None


def test_corrupt_node_facts_are_unknown_instead_of_legacy_fallback(node_plane):
    _, controller, _ = node_plane
    path = controller.state_dir / "trusted-nodes.json"
    path.write_text("{broken", encoding="utf-8")
    for result in (handle_list_nodes(), handle_get_node("legacy-ghost")):
        assert not result["ok"]
        assert result["error"]["details"]["status"] == "UNKNOWN"
    assert path.read_text() == "{broken"


@pytest.mark.parametrize("body", [None, {}])
def test_node_scan_only_queries_registered_facts(node_plane, monkeypatch, body):
    _, controller, _ = node_plane
    before = (controller.state_dir / "trusted-nodes.json").read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("registered-node query cannot initiate network discovery")

    monkeypatch.setattr("socket.create_connection", forbidden)
    result = handle_scan_nodes(body)
    assert result["ok"], result
    assert result["data"]["nodes_found"] == 1
    assert result["data"]["nodes_online"] == 0
    assert result["data"]["scan_performed"] is False
    assert result["data"]["source"] == "node_runtime.controller-status"
    assert (controller.state_dir / "trusted-nodes.json").read_bytes() == before
    assert not handle_scan_nodes({"target": "unqualified-target"})["ok"]


def test_unprovisioned_node_query_cannot_create_controller(node_plane):
    plane, _, _ = node_plane
    plane.live_controller = None
    plane.controller_state = plane.root / "absent-controller"
    result = handle_list_nodes()
    assert not result["ok"]
    assert result["error"]["details"]["status"] == "UNKNOWN"
    assert not plane.controller_state.exists()


def test_actual_http_node_list_detail_and_registered_query(node_plane, monkeypatch):
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from nous_runtime.api.server import RuntimeHTTPServer, RuntimeAPIHandler

    _, _, node = node_plane
    fake_token = "fake-node-http-fact-service"
    monkeypatch.setenv("NOUS_API_TOKEN", fake_token)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    worker = Thread(target=server.serve_forever)
    worker.start()
    try:
        paths = (
            ("GET", "/api/v1/nodes"),
            ("GET", "/api/v1/nodes/" + node.identity.node_id),
            ("POST", "/api/v1/nodes/scan"),
        )
        for method, path in paths:
            for authenticated in (False, True):
                headers = {"Content-Type": "application/json"}
                if authenticated:
                    headers["Authorization"] = "Bearer " + fake_token
                request = Request(
                    f"http://127.0.0.1:{server.server_port}" + path,
                    method=method,
                    headers=headers,
                    data=b"{}" if method == "POST" else None,
                )
                try:
                    response = urlopen(request, timeout=5)
                except HTTPError as exc:
                    response = exc
                with response:
                    status, result = response.status, json.load(response)
                if not authenticated:
                    assert status == 401
                    continue
                assert status == 200 and result["ok"], result
                data = result["data"]
                if method == "POST":
                    assert data["nodes_found"] == 1 and data["scan_performed"] is False
                else:
                    row = data[0] if isinstance(data, list) else data
                    assert row["node_id"] == node.identity.node_id
                    assert row["trust_status"] == "TRUSTED"
                    assert row["online"] is False
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def test_live_signed_node_readiness_and_revocation_reach_legacy_view(node_plane):
    import asyncio
    from nous_runtime.node_runtime.relay import NodeRelayClient
    from tests.node_runtime.test_node_protocol import _wait_for

    async def scenario():
        _, controller, node = node_plane
        relay_url = await controller.start()
        client = NodeRelayClient(
            node,
            relay_url,
            controller.public_key,
            heartbeat_seconds=0.05,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: (
                    controller.controller_status()["nodes"][0]["connectivity_state"]
                    == "ONLINE"
                )
            )
            (view,) = handle_list_nodes("online")["data"]
            assert view["node_id"] == node.identity.node_id
            assert view["online"] is True
            assert view["trust_status"] == "TRUSTED"
            assert view["resource_report_current"] is True
            # Heartbeat liveness cannot replace missing current resource facts.
            controller.reports[node.identity.node_id]["resource_observed_at"] = ""
            (view,) = handle_list_nodes()["data"]
            assert view["online"] is False
            assert view["schedulable"] is False
            controller.revoke_node(
                node.identity.node_id, admit=lambda _: {"subject_id": "fixture-human"}
            )
            (view,) = handle_list_nodes()["data"]
            assert view["trust_status"] == "REVOKED"
            assert view["online"] is False
            assert view["schedulable"] is False
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, timeout=3)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await controller.stop()

    asyncio.run(scenario())

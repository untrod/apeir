"""Legacy device views must report canonical facts without invented discovery."""

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nous_runtime.api.desktop_routes import handle_devices_list, handle_devices_scan
from nous_runtime.control_plane import operations
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.reality import Device, DeviceLifecycle, DeviceRegistry


@pytest.fixture
def device_plane(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    state = tmp_path / "configured-reality"
    plane = operations.OperationsPlane(
        tmp_path / "workspace",
        device_state=state,
        gate=ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance")),
    )
    monkeypatch.setattr(operations, "_operations", plane)
    return plane, DeviceRegistry(state)


def test_empty_registry_never_invents_a_local_device(device_plane):
    result = handle_devices_list()
    assert result["ok"], result
    assert result["data"]["devices"] == []
    assert result["data"]["total"] == result["data"]["online"] == 0
    assert result["data"]["liveness_status"] == "UNKNOWN"
    assert result["data"]["source"] == "reality.device_registry"


@pytest.mark.parametrize("lifecycle", list(DeviceLifecycle))
def test_device_projection_preserves_original_identity_and_lifecycle(
    device_plane, lifecycle
):
    plane, registry = device_plane
    original = Device(
        "device-owned-fixture",
        "simulated",
        "stable-fixture-id",
        "actuator",
        lifecycle=lifecycle,
        node_id="separate-node-id",
        capability_ids=("device.state.read",),
        metadata={"simulated": True},
    )
    registry.register(original)
    before = registry.path.read_bytes()
    result = handle_devices_list()
    assert result["ok"], result
    assert result["data"]["total"] == 1
    (view,) = result["data"]["devices"]
    for key, value in original.to_dict().items():
        assert view[key] == value
    assert view["type"] == original.device_type
    assert view["capabilities"] == list(original.capability_ids)
    assert view["status"] == lifecycle.value.lower()
    assert view["liveness_status"] == "UNKNOWN"
    assert result["data"]["online"] == 0
    assert registry.path.read_bytes() == before
    assert plane.snapshot()["devices"] == json.loads(json.dumps([original.to_dict()]))
    assert not (plane.controller_state / "identity.ed25519.pem").exists()


def test_corrupt_registry_is_not_successful_empty_or_local_online(device_plane):
    plane, registry = device_plane
    registry.state_dir.mkdir(parents=True)
    registry.path.write_text("{not-json", encoding="utf-8")
    result = handle_devices_list()
    assert not result["ok"]
    assert result["error"]["code"] == "DEVICES_LIST_ERROR"
    assert result["error"]["details"]["status"] == "UNKNOWN"
    assert "devices" not in result.get("data", {})
    assert registry.path.read_text() == "{not-json"


@pytest.mark.parametrize("body", [None, {}])
def test_unavailable_scan_reports_no_discovery_or_network_work(
    device_plane, body, monkeypatch
):
    plane, registry = device_plane

    def forbidden(*args, **kwargs):
        pytest.fail("unavailable discovery must not perform network access")

    monkeypatch.setattr("socket.create_connection", forbidden)
    result = handle_devices_scan(body)
    assert result["ok"], result
    assert result["data"]["discovered"] == []
    assert result["data"]["status"] == "UNAVAILABLE"
    assert result["data"]["scan_performed"] is False
    assert not registry.path.exists()
    assert not plane.controller_state.exists()


def test_scan_does_not_accept_targets_or_start_legacy_pairing(device_plane):
    result = handle_devices_scan({"target": "owned-unqualified-target"})
    assert not result["ok"]
    assert result["error"]["code"] == "DEVICES_SCAN_INVALID_REQUEST"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/v1/devices", None),
        ("POST", "/api/v1/devices/scan", None),
        ("POST", "/api/v1/devices/scan", {}),
    ],
)
def test_actual_http_device_facts_and_service_auth(
    device_plane, monkeypatch, method, path, body
):
    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer

    monkeypatch.setenv("NOUS_API_TOKEN", "fake-device-projection-service")
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    worker = Thread(target=server.serve_forever)
    worker.start()

    def request(authenticated):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer fake-device-projection-service"
        req = Request(
            f"http://127.0.0.1:{server.server_port}" + path,
            method=method,
            headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    try:
        assert request(False)[0] == 401
        status, result = request(True)
        assert status == 200 and result["ok"], result
        if method == "GET":
            assert result["data"]["devices"] == []
        else:
            assert result["data"]["discovered"] == []
            assert result["data"]["scan_performed"] is False
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()

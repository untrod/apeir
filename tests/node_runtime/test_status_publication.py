"""Heartbeat projection failure cannot revive or replay execution authority."""

import json

import pytest

from nous_runtime.node_runtime import service as node_service
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


@pytest.fixture
def node(tmp_path, monkeypatch):
    service = NodeRuntimeService(
        NodeRuntimeConfig(tmp_path / "node", heartbeat_seconds=0.05)
    )
    monkeypatch.setattr(service, "probe_resources", lambda: {})
    monkeypatch.setattr(service, "probe_devices", lambda: [])
    monkeypatch.setattr(service, "probe_execution_host", lambda *_: {})
    return service


def test_projection_refusal_is_observed_then_next_heartbeat_continues(
    node, monkeypatch, caplog
):
    original = node_service._atomic_write_json
    attempts = []

    def publish(path, value):
        if path == node.status_path and value["state"] == "ONLINE":
            attempts.append(value["heartbeat_sequence"])
            if len(attempts) == 1:
                raise PermissionError("controlled Windows reader sharing refusal")
            node.stop()
        return original(path, value)

    monkeypatch.setattr(node_service, "_atomic_write_json", publish)
    node.run_forever(install_signal_handlers=False)
    assert attempts == [1, 2]
    assert json.loads(node.status_path.read_text())["state"] == "STOPPED"
    events = [json.loads(line) for line in node.telemetry_path.read_text().splitlines()]
    assert (
        len(
            [item for item in events if item["event_type"] == "node.status.unavailable"]
        )
        == 1
    )
    heartbeat = [item for item in events if item["event_type"] == "node.heartbeat"]
    assert [item["payload"]["sequence"] for item in heartbeat] == [2]
    assert "status publication refused" in caplog.text
    assert node._workloads == {}


def test_stop_during_refused_projection_does_not_retry_the_heartbeat(node, monkeypatch):
    original = node_service._atomic_write_json
    attempts = []

    def publish(path, value):
        if path == node.status_path and value["state"] == "ONLINE":
            attempts.append(value["heartbeat_sequence"])
            node.stop()
            raise PermissionError("controlled status sharing refusal")
        return original(path, value)

    monkeypatch.setattr(node_service, "_atomic_write_json", publish)
    node.run_forever(install_signal_handlers=False)
    assert attempts == [1]
    assert json.loads(node.status_path.read_text())["state"] == "STOPPED"


def test_foreground_status_publication_reports_failure(node, monkeypatch):
    original = node_service._atomic_write_json

    def publish(path, value):
        if path == node.status_path:
            raise PermissionError("controlled status refusal")
        return original(path, value)

    monkeypatch.setattr(node_service, "_atomic_write_json", publish)
    with pytest.raises(PermissionError):
        node.run_once()
    assert not node.status_path.exists()


def test_authoritative_registration_failure_is_not_suppressed(node, monkeypatch):
    original = node_service._atomic_write_json

    def publish(path, value):
        if path == node.registration_path:
            raise PermissionError("controlled registration refusal")
        return original(path, value)

    monkeypatch.setattr(node_service, "_atomic_write_json", publish)
    with pytest.raises(PermissionError, match="registration refusal"):
        node.run_forever(install_signal_handlers=False)

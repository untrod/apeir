from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.node_runtime.protocol import NodeProtocolError
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.relay_cli import app
from nous_runtime.node_runtime.cli import node_daemon_app
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def test_controller_cli_initializes_artifacts_and_trusts_identity_file(
    tmp_path: Path,
):
    node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    controller_state = tmp_path / "controller"
    runner = CliRunner()

    initialized = runner.invoke(app, ["init", "--state-dir", str(controller_state)])
    assert initialized.exit_code == 0, initialized.output
    initial_status = json.loads(initialized.stdout)
    assert initial_status["schema"] == "apeir.controller-status/v1"
    assert initial_status["artifact_count"] == 0
    assert (controller_state / "artifacts" / "objects" / "sha256").is_dir()

    trusted = runner.invoke(
        app,
        [
            "trust",
            str(node.identity_path),
            "--state-dir",
            str(controller_state),
        ],
    )
    assert trusted.exit_code == 0, trusted.output
    assert json.loads(trusted.stdout)["trusted"] == node.identity.node_id

    status = runner.invoke(app, ["status", "--state-dir", str(controller_state)])
    assert status.exit_code == 0, status.output
    value = json.loads(status.stdout)
    assert value["trusted_node_count"] == 1
    assert value["connected_node_count"] == 0
    assert value["nodes"][0]["node_id"] == node.identity.node_id
    assert value["nodes"][0]["connected"] is False


def test_controller_selects_arm64_node_by_deterministic_capability_match():
    server = NodeRelayServer(heartbeat_seconds=60.0)
    server.node_keys = {"node-arm64": "01" * 32, "node-x64": "02" * 32}
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def observation(node_id: str, node_name: str, architecture: str) -> dict:
        return {
            "observed_at": observed_at,
            "REGISTER": {
                "identity": {
                    "node_id": node_id,
                    "node_name": node_name,
                    "capabilities": ["system.echo"],
                    "platform": {
                        "os": "Linux" if architecture == "aarch64" else "Windows",
                        "arch": architecture,
                        "abi": "glibc" if architecture == "aarch64" else "msvc",
                    },
                    "word_size_bits": 64,
                }
            },
            "HEARTBEAT": {
                "node_id": node_id,
                "status": "ONLINE",
                "heartbeat_sequence": 1,
            },
        }

    server.reports = {
        "node-arm64": observation("node-arm64", "jetson", "aarch64"),
        "node-x64": observation("node-x64", "windows", "AMD64"),
    }

    decision = server.select_node(
        {"architecture": "aarch64", "capability": "system.echo"}
    )

    assert decision["strategy"] == "deterministic-capability-match"
    assert decision["selected_node"] == "node-arm64"
    assert decision["requirements"]["architecture"] == "arm64"
    assert [item["eligible"] for item in decision["candidates"]] == [True, False]
    assert "architecture mismatch" in decision["candidates"][1]["reasons"][0]


def test_controller_select_node_cli_fails_closed_without_match(
    tmp_path: Path,
):
    result = CliRunner().invoke(
        app,
        [
            "select-node",
            "--state-dir",
            str(tmp_path / "controller"),
            "--architecture",
            "arm64",
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["selected_node"] == ""


def test_node_cli_exports_public_identity_without_running_host_probes(tmp_path: Path):
    state = tmp_path / "node"
    result = CliRunner().invoke(
        node_daemon_app,
        ["--state-dir", str(state), "--identity-only", "--json"],
    )

    assert result.exit_code == 0, result.output
    identity = json.loads(result.stdout)
    assert identity["node_id"].startswith("node_")
    assert len(identity["public_key"]) == 64
    assert (state / "identity.json").is_file()
    assert (state / "identity.ed25519.pem").is_file()
    assert not (state / "status.json").exists()


def test_controller_persists_node_observations_without_claiming_live_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def scenario() -> None:
        controller_state = tmp_path / "controller"
        node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        sequence = 0

        def lightweight_status() -> dict:
            nonlocal sequence
            sequence += 1
            return {
                "heartbeat_sequence": sequence,
                "resources": {
                    "schema": "nous.resource-report/v1",
                    "measurement_source": "test-fixture",
                },
                "devices": [],
            }

        monkeypatch.setattr(node, "run_once", lightweight_status)
        server = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=ContentAddressedArtifactStore(
                controller_state / "artifacts"
            ),
            heartbeat_seconds=0.05,
        )
        server.register_node(node.identity.node_id, node.identity.public_key)
        url = await server.start()
        stop = asyncio.Event()
        client = NodeRelayClient(node, url, server.public_key, heartbeat_seconds=0.05)
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: (
                    "HEARTBEAT" in server.reports.get(node.identity.node_id, {})
                    and "RESOURCE_REPORT"
                    in server.reports.get(node.identity.node_id, {})
                    and "DEVICE_REPORT" in server.reports.get(node.identity.node_id, {})
                )
            )
            live = server.controller_status()
            assert live["connected_node_count"] == 1
            assert live["nodes"][0]["connected"] is True
            assert live["nodes"][0]["liveness"] == "CONNECTED"
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await server.stop()

        restarted = NodeRelayServer(
            state_dir=controller_state,
            artifact_store=ContentAddressedArtifactStore(
                controller_state / "artifacts"
            ),
        )
        durable = restarted.controller_status()
        assert durable["connected_node_count"] == 0
        assert durable["nodes"][0]["connected"] is False
        assert durable["nodes"][0]["liveness"] == "RECENTLY_OBSERVED"
        assert durable["nodes"][0]["heartbeat_sequence"] > 0
        assert durable["nodes"][0]["last_observed_at"].endswith("Z")
        assert durable["nodes"][0]["has_resource_report"] is True
        assert durable["nodes"][0]["has_device_report"] is True
        assert durable["nodes"][0]["node_name"] == node.identity.node_name
        assert durable["nodes"][0]["platform"]["arch"] == node.identity.platform_arch
        assert durable["nodes"][0]["capabilities"] == list(node.identity.capabilities)

    asyncio.run(scenario())


def test_running_controller_reloads_durable_trust_before_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def scenario() -> None:
        controller_state = tmp_path / "controller"
        node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
        monkeypatch.setattr(
            node,
            "run_once",
            lambda: {
                "heartbeat_sequence": 1,
                "resources": {
                    "schema": "nous.node-resource-report/v1",
                    "measurement_source": "test-fixture",
                },
                "devices": [],
            },
        )
        running = NodeRelayServer(state_dir=controller_state)
        url = await running.start()
        registrar = NodeRelayServer(state_dir=controller_state)
        registrar.register_node(node.identity.node_id, node.identity.public_key)
        stop = asyncio.Event()
        client = NodeRelayClient(node, url, running.public_key, heartbeat_seconds=0.05)
        task = asyncio.create_task(client.run_forever(stop))
        try:
            await _wait_for(
                lambda: "REGISTER" in running.reports.get(node.identity.node_id, {})
            )
            assert node.identity.node_id in running.connections
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            await running.stop()

    asyncio.run(scenario())


def test_controller_rejects_observations_without_signed_provenance(tmp_path: Path):
    state = tmp_path / "controller"
    first = NodeRelayServer(state_dir=state)
    first.register_node("node-trusted", "01" * 32)
    (state / "node-observations.json").write_text(
        json.dumps(
            {
                "schema": "apeir.controller-observations/v1",
                "nodes": {
                    "node-trusted": {
                        "observed_at": "2026-10-01T00:00:00Z",
                        "HEARTBEAT": {
                            "node_id": "node-trusted",
                            "status": "ONLINE",
                            "heartbeat_sequence": 1,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(NodeProtocolError, match="observation provenance is invalid"):
        NodeRelayServer(state_dir=state)


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for Controller observation")

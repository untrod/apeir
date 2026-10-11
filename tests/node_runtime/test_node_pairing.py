"""Durable signed Node onboarding through the existing Controller trust owner."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest

from nous_runtime.control_plane.operations import OperationsPlane
from nous_runtime.governance import (
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceStore,
)
from nous_runtime.governance.cli import _build_context
from nous_runtime.node_runtime.protocol import (
    NODE_PROTOCOL_VERSION,
    NodeProtocolEnvelope,
    NodeProtocolError,
)
from nous_runtime.node_runtime.relay import NodeRelayClient, NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


@pytest.fixture
def setup(tmp_path):
    server = NodeRelayServer(state_dir=tmp_path / "controller")
    node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    gate = ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance"))
    plane = OperationsPlane(tmp_path, gate=gate, controller=server)
    return server, node, plane


def issue(server, plane, url="ws://127.0.0.1:9770"):
    return plane.node_action(
        {
            "kind": "pairings",
            "action": "create",
            "target_id": server.public_key,
            "relay_url": url,
        },
        _build_context(),
    )


def proof(node, server, invite, *, sequence=1, code=True):
    pairing = {
        "request_id": invite["request_id"],
        "controller_public_key": server.public_key,
    }
    if code:
        pairing["pairing_code"] = invite["pairing_code"]
    return NodeProtocolEnvelope(
        "REGISTER",
        node.identity.node_id,
        "control_plane",
        sequence,
        {
            "node_id": node.identity.node_id,
            "identity": node.identity.to_dict(),
            "supported_versions": [NODE_PROTOCOL_VERSION],
            "pairing": pairing,
        },
    ).sign(node.load_private_key())


def decide(plane, pending, approve=True, context=None):
    return plane.node_action(
        {
            "kind": "pairings",
            "action": "approve_once" if approve else "deny",
            "target_id": pending["request_id"],
            "node_id": pending["node_id"],
            "public_key": pending["public_key"],
        },
        context or _build_context(),
    )


def test_code_is_bound_once_and_persisted_trust_is_not_operation_authority(setup):
    server, node, plane = setup
    invite = issue(server, plane)
    pending = server.receive_pairing(proof(node, server, invite))
    assert pending["status"] == "PENDING"
    assert not server.node_keys
    with pytest.raises(NodeProtocolError, match="consumed"):
        server.receive_pairing(proof(node, server, invite, sequence=2))
    assert decide(plane, pending)["status"] == "APPROVED"
    restarted = NodeRelayServer(state_dir=server.state_dir)
    assert restarted.node_keys == {node.identity.node_id: node.identity.public_key}
    assert (
        restarted.receive_pairing(
            proof(node, restarted, invite, sequence=3, code=False)
        )["status"]
        == "APPROVED"
    )
    with pytest.raises(PermissionError, match="not pending"):
        decide(plane, pending)
    assert plane.gate.store.list_active_leases() == []
    for path in [
        server.state_dir / "trusted-nodes.json",
        Path(plane.gate.store.db_path),
    ]:
        assert invite["pairing_code"].encode() not in path.read_bytes()
    audit = plane.snapshot()["activity"]
    decisions = [
        entry for entry in audit if entry["event_type"] == "node.trust.decision"
    ]
    assert {entry["evidence"]["action"] for entry in decisions} == {
        "create",
        "approve_once",
    }
    assert all(
        entry["evidence"]["execution_authority_issued"] is False for entry in decisions
    )
    assert decisions[0]["evidence"]["public_key"] == node.identity.public_key


def test_denial_and_wrong_human_confirmation_never_publish_trust(setup):
    server, node, plane = setup
    pending = server.receive_pairing(proof(node, server, issue(server, plane)))
    with pytest.raises(PermissionError, match="exact Node"):
        decide(plane, {**pending, "public_key": "01" * 32})
    assert decide(plane, pending, approve=False)["status"] == "DENIED"
    assert not NodeRelayServer(state_dir=server.state_dir).node_keys
    with pytest.raises(PermissionError):
        decide(plane, pending)


@pytest.mark.parametrize(
    "actor", ["model", "agent", "planner", "scheduler", "node", "provider", "user"]
)
def test_serialized_or_nonhuman_claims_cannot_create_approve_or_revoke(setup, actor):
    server, node, plane = setup
    fake = AuthorizationContext(
        subject_type=actor,
        subject_id="self",
        authn_method="cli_os_user",
        authn_confidence=1.0,
    )
    with pytest.raises(PermissionError, match="authenticated"):
        plane.node_action(
            {
                "kind": "pairings",
                "action": "create",
                "target_id": server.public_key,
                "relay_url": "ws://127.0.0.1:9770",
            },
            fake,
        )
    invite = issue(server, plane)
    pending = server.receive_pairing(proof(node, server, invite))
    with pytest.raises(PermissionError, match="authenticated"):
        decide(plane, pending, context=fake)
    assert not server.node_keys
    decide(plane, pending)
    with pytest.raises(PermissionError, match="authenticated"):
        plane.node_action(
            {"kind": "nodes", "action": "revoke", "target_id": node.identity.node_id},
            fake,
        )
    server._require_node_trust(node.identity.node_id)


def test_attempts_expiration_controller_and_signature_binding(setup):
    server, node, plane = setup
    invite = issue(server, plane)
    bad = {**invite, "pairing_code": "WRONG123"}
    for sequence in range(1, 6):
        with pytest.raises(NodeProtocolError, match="invalid"):
            server.receive_pairing(proof(node, server, bad, sequence=sequence))
    restarted = NodeRelayServer(state_dir=server.state_dir)
    with pytest.raises(NodeProtocolError, match="exhausted"):
        restarted.receive_pairing(proof(node, restarted, invite, sequence=6))
    fresh = issue(server, plane)
    wrong_controller = proof(node, server, fresh, sequence=7)
    wrong_controller.payload["pairing"]["controller_public_key"] = "01" * 32
    wrong_controller.sign(node.load_private_key())
    with pytest.raises(NodeProtocolError, match="proof"):
        server.receive_pairing(wrong_controller)
    tampered = proof(node, server, fresh, sequence=8)
    tampered.payload["identity"]["public_key"] = "01" * 32
    with pytest.raises(NodeProtocolError, match="proof"):
        server.receive_pairing(tampered)
    record = server._trust_document["pairings"][fresh["request_id"]]
    record["expires_at"] = 1
    server._save_trusted_nodes()
    with pytest.raises(NodeProtocolError, match="expired"):
        restarted.receive_pairing(proof(node, restarted, fresh, sequence=9))
    assert not restarted.node_keys


def test_pending_expiry_and_audit_failure_prevent_trust(setup, monkeypatch):
    server, node, plane = setup
    pending = server.receive_pairing(proof(node, server, issue(server, plane)))

    def unavailable(*args, **kwargs):
        raise OSError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(plane.gate.store, "append_operation_audit", unavailable)
        with pytest.raises(OSError):
            decide(plane, pending)
    assert not NodeRelayServer(state_dir=server.state_dir).node_keys
    server._trust_document["pairings"][pending["request_id"]]["expires_at"] = 1
    server._save_trusted_nodes()
    with pytest.raises(PermissionError, match="expired"):
        decide(plane, pending)


def test_identity_conflict_and_revocation_cannot_be_overwritten(setup):
    server, node, plane = setup
    server.register_node(node.identity.node_id, "01" * 32)
    invite = issue(server, plane)
    with pytest.raises(NodeProtocolError, match="replace"):
        server.receive_pairing(proof(node, server, invite))
    original = dict(server.node_keys)
    result = plane.node_action(
        {"kind": "nodes", "action": "revoke", "target_id": node.identity.node_id},
        _build_context(),
    )
    assert result["trust_status"] == "REVOKED"
    restarted = NodeRelayServer(state_dir=server.state_dir)
    assert restarted.node_keys == original
    with pytest.raises(PermissionError, match="revoked"):
        restarted.register_node(node.identity.node_id, "01" * 32)
    with pytest.raises(NodeProtocolError, match="revive"):
        restarted.receive_pairing(proof(node, restarted, invite, sequence=2))
    status = restarted.controller_status()
    assert status["trusted_node_count"] == 0
    assert status["nodes"][0]["trust_status"] == "REVOKED"
    assert status["nodes"][0]["schedulable"] is False


@pytest.mark.parametrize(
    "corrupt", ['{"schema":"nous.relay-trust/v1","nodes":{},"revoked":[]}', "not-json"]
)
def test_corrupt_trust_is_not_an_empty_store(tmp_path, corrupt):
    server = NodeRelayServer(state_dir=tmp_path)
    path = tmp_path / "trusted-nodes.json"
    path.write_text(corrupt)
    with pytest.raises(ValueError):
        server.register_node("overwrite", "01" * 32)
    assert path.read_text() == corrupt
    with pytest.raises(ValueError):
        NodeRelayServer(state_dir=tmp_path)


async def wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=5)


def test_real_node_cli_process_pairs_and_restart_queries_original_proof(setup):
    server, node, plane = setup

    async def scenario():
        url = await server.start()
        try:
            invite = issue(server, plane, url)
            args = [
                sys.executable,
                "-m",
                "nous_runtime.node_runtime.cli",
                "pair",
                "--state-dir",
                str(node.state_dir),
                "--request-id",
                invite["request_id"],
                "--relay-url",
                url,
                "--server-public-key",
                server.public_key,
            ]
            first = await asyncio.to_thread(
                subprocess.run,
                args + ["--code-stdin"],
                input=invite["pairing_code"] + "\n",
                text=True,
                capture_output=True,
                timeout=30,
            )
            assert first.returncode == 0, first.stderr
            assert invite["pairing_code"] not in first.stdout + first.stderr
            pending = json.loads(first.stdout.splitlines()[-1])
            assert pending["status"] == "PENDING"
            decide(plane, pending)
            # A new Node CLI process reads the same private identity and queries;
            # it never resubmits the spent code or regenerates its key.
            second = await asyncio.to_thread(
                subprocess.run,
                args + ["--status"],
                text=True,
                capture_output=True,
                timeout=30,
            )
            assert second.returncode == 0, second.stderr
            result = json.loads(second.stdout.splitlines()[-1])
            assert result["status"] == "APPROVED"
            assert result["public_key"] == node.identity.public_key
            assert server.results == {}
            assert node._workloads == {}
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_revocation_closes_live_connection_and_denies_new_work(setup):
    server, node, plane = setup

    async def scenario():
        url = await server.start()
        server.register_node(node.identity.node_id, node.identity.public_key)
        client = NodeRelayClient(node, url, server.public_key, heartbeat_seconds=0.1)
        task = asyncio.create_task(client.run_session(asyncio.Event()))
        try:
            await wait_until(lambda: node.identity.node_id in server.connections)
            # Separate Controller instance models CLI/API revocation while listener lives.
            other = NodeRelayServer(state_dir=server.state_dir)
            revoker = OperationsPlane(plane.root, gate=plane.gate, controller=other)
            revoker.node_action(
                {
                    "kind": "nodes",
                    "action": "revoke",
                    "target_id": node.identity.node_id,
                },
                _build_context(),
            )
            with pytest.raises(NodeProtocolError, match="revoked"):
                await server.queue_workload(
                    node.identity.node_id, "after-revoke", "system.echo"
                )
            await wait_until(lambda: node.identity.node_id not in server.connections)
            await asyncio.gather(task, return_exceptions=True)
            assert "after-revoke" not in server.pending.get(node.identity.node_id, {})
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await server.stop()

    asyncio.run(scenario())


def test_lost_pairing_response_queries_persisted_original_without_spent_code(setup):
    from websockets.asyncio.client import connect

    server, node, plane = setup

    async def scenario():
        url = await server.start()
        try:
            invite = issue(server, plane, url)
            envelope = proof(node, server, invite)
            async with connect(url) as socket:
                await socket.send(envelope.to_json())
                await wait_until(
                    lambda: server.list_pairings()[0]["status"] == "PENDING"
                )
                # Close without reading the signed ACK; Controller has persisted proof.
            assert not server.node_keys
            # The ordinary CLI sequence belongs to the same persistent identity.
            (node.state_dir / "relay-sequence.json").write_text(
                json.dumps({"sequence": 1})
            )
            restarted_node = NodeRuntimeService(
                NodeRuntimeConfig(state_dir=node.state_dir)
            )
            client = NodeRelayClient(restarted_node, url, server.public_key)
            original = await client.pair(invite["request_id"])
            assert original["status"] == "PENDING"
            assert original["attempts"] == 1
            decide(plane, original)
            assert (await client.pair(invite["request_id"]))["status"] == "APPROVED"
            assert len(server.list_pairings()) == 1
            assert server.pending == server.results == {}
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_atomic_decision_competition_between_real_controller_processes(setup, tmp_path):
    server, node, plane = setup
    pending = server.receive_pairing(proof(node, server, issue(server, plane)))
    script = """
import json,sys
from pathlib import Path
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.control_plane.operations import OperationsPlane
from nous_runtime.governance import ExecutionAuthorizationGate,GovernanceStore
from nous_runtime.governance.cli import _build_context
state,root,request,node,public=sys.argv[1:]
server=NodeRelayServer(state_dir=Path(state))
plane=OperationsPlane(root,gate=ExecutionAuthorizationGate(GovernanceStore(Path(root)/'governance')),controller=server)
try:
    plane.node_action({'kind':'pairings','action':'approve_once','target_id':request,'node_id':node,'public_key':public},_build_context())
    print('approved')
except PermissionError:
    print('rejected')
"""
    children = []
    try:
        for _ in range(2):
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        str(server.state_dir),
                        str(tmp_path),
                        pending["request_id"],
                        pending["node_id"],
                        pending["public_key"],
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        statuses = []
        for child in children:
            output, error = child.communicate(timeout=30)
            assert child.returncode == 0, error
            statuses.append(output.strip())
        assert sorted(statuses) == ["approved", "rejected"]
        restarted = NodeRelayServer(state_dir=server.state_dir)
        assert restarted.node_keys == {node.identity.node_id: node.identity.public_key}
        assert restarted.list_pairings()[0]["status"] == "APPROVED"
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)


def test_failed_trust_write_keeps_original_pending_state(setup, monkeypatch):
    server, node, plane = setup
    pending = server.receive_pairing(proof(node, server, issue(server, plane)))

    def unavailable():
        raise OSError("controlled trust persistence failure")

    monkeypatch.setattr(server, "_save_trusted_nodes", unavailable)
    with pytest.raises(OSError):
        decide(plane, pending)
    assert not server.node_keys
    assert (
        NodeRelayServer(state_dir=server.state_dir).list_pairings()[0]["status"]
        == "PENDING"
    )
    # The audit explicitly records a decision intent, not a false persisted success.
    assert (
        plane.snapshot()["activity"][0]["evidence"]["trust_persistence_confirmed"]
        is False
    )


def test_pairing_code_redaction_protects_unknown_process_logging():
    from nous_runtime.core.redaction import (
        REDACTED,
        redact_sensitive_data,
        redact_sensitive_text,
    )

    assert redact_sensitive_data({"pairing_code": "ABCD2345"}) == {
        "pairing_code": REDACTED
    }
    assert "ABCD2345" not in redact_sensitive_text(
        'REGISTER payload={"pairing_code":"ABCD2345"}'
    )


def test_invalid_codes_do_not_allocate_anonymous_replay_sources(setup):
    from dataclasses import replace

    server, node, plane = setup
    invite = issue(server, plane)
    for sequence in range(1, 6):
        node.identity = replace(
            node.identity, node_id=f"unauthorized-candidate-{sequence}"
        )
        with pytest.raises(NodeProtocolError, match="invalid"):
            server.receive_pairing(
                proof(
                    node,
                    server,
                    {**invite, "pairing_code": "WRONG123"},
                    sequence=sequence,
                )
            )
    assert server._replay._last_sequence == {}
    assert server.list_pairings()[0]["status"] == "EXHAUSTED"


def test_bounded_invitations_retain_terminal_original_evidence(setup):
    server, node, plane = setup
    invite = issue(server, plane)
    pending = server.receive_pairing(proof(node, server, invite))
    decide(plane, pending)
    server._trust_document["pairings"][pending["request_id"]]["expires_at"] = 1
    server._save_trusted_nodes()
    for _ in range(32):
        issue(server, plane)
    with pytest.raises(PermissionError, match="pending pairing limit"):
        issue(server, plane)
    assert (
        server.receive_pairing(proof(node, server, invite, sequence=2, code=False))[
            "status"
        ]
        == "APPROVED"
    )
    assert len(server.list_pairings()) == 33


@pytest.mark.parametrize(
    "options,code",
    [
        (["--code-stdin"], "TOO-LONG-CODE\n"),
        (["--code-stdin", "--status"], "ABCD2345\n"),
    ],
)
def test_cli_rejects_invalid_stdin_before_creating_identity(tmp_path, options, code):
    from typer.testing import CliRunner
    from nous_runtime.node_runtime.cli import node_daemon_app

    state = tmp_path / "node"
    result = CliRunner().invoke(
        node_daemon_app,
        [
            "pair",
            "--request-id",
            "pair-invalid",
            "--relay-url",
            "ws://127.0.0.1:1",
            "--server-public-key",
            "a" * 64,
            "--state-dir",
            str(state),
            *options,
        ],
        input=code,
    )
    assert result.exit_code != 0
    assert code.strip() not in result.output
    assert not state.exists()

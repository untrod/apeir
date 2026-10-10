"""Trust enrollment must preserve peers and existing identity bindings."""

import json
import subprocess
import sys
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nous_runtime.node_runtime.relay import NodeRelayServer, public_key_hex
from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService


def key():
    return public_key_hex(Ed25519PrivateKey.generate())


def test_stale_controller_instances_preserve_both_enrollments(tmp_path):
    first = NodeRelayServer(state_dir=tmp_path)
    second = NodeRelayServer(state_dir=tmp_path)
    first.register_node("first", key())
    second.register_node("second", key())
    restarted = NodeRelayServer(state_dir=tmp_path)
    assert set(restarted.node_keys) == {"first", "second"}
    assert restarted.controller_status()["connected_node_count"] == 0


@pytest.mark.parametrize("durable", [False, True])
def test_normal_enrollment_cannot_replace_an_existing_identity(tmp_path, durable):
    server = NodeRelayServer(state_dir=tmp_path if durable else None)
    original = key()
    server.register_node("original", original)
    with pytest.raises(PermissionError, match="different key"):
        server.register_node("original", key())
    assert server.node_keys["original"] == original
    if durable:
        assert NodeRelayServer(state_dir=tmp_path).node_keys["original"] == original
    server.register_node("original", original)
    assert server.node_keys["original"] == original


def test_failed_persistence_does_not_publish_an_in_memory_trust(tmp_path, monkeypatch):
    server = NodeRelayServer(state_dir=tmp_path)
    original = key()
    server.register_node("original", original)

    def unavailable():
        raise OSError("controlled persistence failure")

    monkeypatch.setattr(server, "_save_trusted_nodes", unavailable)
    with pytest.raises(OSError):
        server.register_node("unpersisted", key())
    assert server.node_keys == {"original": original}
    assert NodeRelayServer(state_dir=tmp_path).node_keys == {"original": original}


@pytest.mark.parametrize("missing", ["identity", "private_key", "both"])
def test_incomplete_node_identity_does_not_generate_a_replacement(tmp_path, missing):
    node = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path))
    # An existing journal remains bound to the original Node even if both identity files vanish.
    node.execute_workload("original-work", "system.echo", {"message": "original"})
    if missing in {"identity", "both"}:
        node.identity_path.unlink()
    if missing in {"private_key", "both"}:
        node.private_key_path.unlink()
    before = {
        path.name: path.read_bytes()
        for path in (node.identity_path, node.private_key_path, node.workloads_path)
        if path.exists()
    }
    with pytest.raises(PermissionError, match="original identity"):
        NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path))
    after = {
        path.name: path.read_bytes()
        for path in (node.identity_path, node.private_key_path, node.workloads_path)
        if path.exists()
    }
    assert after == before


def test_controller_with_existing_trust_cannot_silently_replace_a_missing_key(tmp_path):
    server = NodeRelayServer(state_dir=tmp_path)
    server.register_node("existing", key())
    trust = (tmp_path / "trusted-nodes.json").read_bytes()
    (tmp_path / "identity.ed25519.pem").unlink()
    with pytest.raises(PermissionError, match="original key"):
        NodeRelayServer(state_dir=tmp_path)
    assert not (tmp_path / "identity.ed25519.pem").exists()
    assert (tmp_path / "trusted-nodes.json").read_bytes() == trust


def test_independent_processes_register_without_losing_trust(tmp_path):
    state = tmp_path / "controller"
    NodeRelayServer(state_dir=state)
    identities = {f"node-{index}": key() for index in range(4)}
    script = """
import json,sys,time
from pathlib import Path
from nous_runtime.node_runtime.relay import NodeRelayServer
state,node,public,ready,release=sys.argv[1:]
server=NodeRelayServer(state_dir=Path(state))
Path(ready).write_text('ready')
deadline=time.monotonic()+15
while not Path(release).exists():
    if time.monotonic()>deadline: raise TimeoutError('registration barrier')
    time.sleep(.01)
server.register_node(node,public)
"""
    release = tmp_path / "release"
    processes = []
    try:
        for node, public in identities.items():
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        str(state),
                        node,
                        public,
                        str(tmp_path / node),
                        str(release),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        deadline = time.monotonic() + 15
        while not all((tmp_path / node).exists() for node in identities):
            assert time.monotonic() < deadline, "processes did not load initial trust"
            assert all(child.poll() is None for child in processes)
            time.sleep(0.01)
        release.write_text("release")
        for child in processes:
            _, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr.decode()
        assert NodeRelayServer(state_dir=state).node_keys == identities
        stored = json.loads((state / "trusted-nodes.json").read_text())
        assert stored["schema"] == "nous.relay-trust/v1"
        assert stored["nodes"] == identities
    finally:
        for child in processes:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)


@pytest.mark.parametrize("owner", ["node", "controller"])
def test_independent_initializers_share_one_persistent_identity(tmp_path, owner):
    script = """
import json,sys,time
from pathlib import Path
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.node_runtime.service import NodeRuntimeConfig,NodeRuntimeService
state,owner,ready,release=sys.argv[1:]
Path(ready).write_text('ready')
deadline=time.monotonic()+15
while not Path(release).exists():
    if time.monotonic()>deadline: raise TimeoutError('identity barrier')
    time.sleep(.01)
if owner=='node':
    identity=NodeRuntimeService(NodeRuntimeConfig(state_dir=Path(state))).identity
    value={'node_id':identity.node_id,'public_key':identity.public_key}
else:
    value={'public_key':NodeRelayServer(state_dir=Path(state)).public_key}
print(json.dumps(value))
"""
    release = tmp_path / "release"
    state = tmp_path / "state"
    processes = []
    try:
        for index in range(3):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        str(state),
                        owner,
                        str(tmp_path / str(index)),
                        str(release),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        deadline = time.monotonic() + 15
        while not all((tmp_path / str(index)).exists() for index in range(3)):
            assert time.monotonic() < deadline, "initializer did not reach barrier"
            assert all(child.poll() is None for child in processes)
            time.sleep(0.01)
        release.write_text("release")
        results = []
        for child in processes:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr.decode()
            assert b"PRIVATE KEY" not in stdout
            results.append(json.loads(stdout))
        assert all(value == results[0] for value in results)
        persisted = (
            NodeRuntimeService(NodeRuntimeConfig(state_dir=state)).identity.public_key
            if owner == "node"
            else NodeRelayServer(state_dir=state).public_key
        )
        assert persisted == results[0]["public_key"]
    finally:
        for child in processes:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)

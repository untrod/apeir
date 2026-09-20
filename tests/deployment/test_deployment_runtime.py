from pathlib import Path

from nous_runtime.artifact import ArtifactType, ContentAddressedArtifactStore
from nous_runtime.deployment.runtime import DeploymentRuntime, DeploymentState


def _artifact(store: ContentAddressedArtifactStore, content: bytes) -> str:
    return store.store_bytes(
        content, artifact_type=ArtifactType.CONFIGURATION, name="config.json"
    )["artifact"]["digest"]


def test_static_deployment_runs_full_state_machine(tmp_path: Path):
    source = ContentAddressedArtifactStore(tmp_path / "source")
    digest = _artifact(source, b'{"enabled":true}')
    runtime = DeploymentRuntime(tmp_path / "runtime", source)

    record = runtime.deploy_static(digest, "local-node", deployment_id="deploy-1")

    assert record.state is DeploymentState.ACTIVE
    assert [event["state"] for event in record.events] == [
        "PENDING", "RESOLVING", "TRANSFERRING", "INSTALLING", "STARTING",
        "VERIFYING", "ACTIVE",
    ]
    assert Path(record.release_path, "payload").read_bytes() == b'{"enabled":true}'
    assert record.receipt["result"] == "COMPLETED"
    assert runtime.deploy_static(digest, "local-node", deployment_id="deploy-1").state is DeploymentState.ACTIVE


def test_failed_health_check_rolls_back_to_previous_active(tmp_path: Path):
    source = ContentAddressedArtifactStore(tmp_path / "source")
    old_digest = _artifact(source, b"old")
    new_digest = _artifact(source, b"new")
    runtime = DeploymentRuntime(tmp_path / "runtime", source)
    old = runtime.deploy_static(old_digest, "edge", deployment_id="old")

    failed = runtime.deploy_static(
        new_digest,
        "edge",
        deployment_id="new",
        health_check=lambda _path: False,
    )

    assert old.state is DeploymentState.ACTIVE
    assert failed.state is DeploymentState.ROLLED_BACK
    assert failed.error_code == "NOUS_DEPLOYMENT_FAILED"
    assert failed.receipt["result"] == "ROLLED_BACK"
    current = (tmp_path / "runtime" / "targets" / "edge" / "current.json").read_text(encoding="utf-8")
    assert '"deployment_id": "old"' in current
    assert not Path(failed.release_path).exists()


def test_idempotency_collision_is_rejected(tmp_path: Path):
    import pytest
    from nous_runtime.errors import DeploymentError

    source = ContentAddressedArtifactStore(tmp_path / "source")
    one = _artifact(source, b"one")
    two = _artifact(source, b"two")
    runtime = DeploymentRuntime(tmp_path / "runtime", source)
    runtime.deploy_static(one, "edge", deployment_id="same")

    with pytest.raises(DeploymentError, match="collision"):
        runtime.deploy_static(two, "edge", deployment_id="same")


def test_interrupted_deployment_recovery_preserves_previous_active(tmp_path: Path):
    import json

    source = ContentAddressedArtifactStore(tmp_path / "source")
    old_digest = _artifact(source, b"old")
    new_digest = _artifact(source, b"new")
    runtime = DeploymentRuntime(tmp_path / "runtime", source)
    runtime.deploy_static(old_digest, "edge", deployment_id="old")
    interrupted = {
        "schema": "nous.deployment/v1",
        "deployment_id": "interrupted",
        "artifact_digest": new_digest,
        "target_id": "edge",
        "mode": "static",
        "state": "INSTALLING",
        "created_at": "2026-09-05T00:00:00.000Z",
        "updated_at": "2026-09-05T00:00:01.000Z",
        "previous_active": "old",
        "release_path": "",
        "error_code": "",
        "error_message": "",
        "events": [{"state": "PENDING", "timestamp": "2026-09-05T00:00:00.000Z"}],
        "receipt": {},
    }
    path = tmp_path / "runtime" / "deployments" / "interrupted.json"
    path.write_text(json.dumps(interrupted), encoding="utf-8")

    recovered = runtime.deploy_static(
        new_digest, "edge", deployment_id="interrupted"
    )

    assert recovered.state is DeploymentState.ROLLED_BACK
    current = json.loads(
        (tmp_path / "runtime" / "targets" / "edge" / "current.json").read_text(
            encoding="utf-8"
        )
    )
    assert current["deployment_id"] == "old"


def test_reconciliation_converges_then_performs_no_duplicate_effect(tmp_path: Path):
    source = ContentAddressedArtifactStore(tmp_path / "source")
    digest = _artifact(source, b"desired")
    runtime = DeploymentRuntime(tmp_path / "runtime", source)

    first = runtime.reconcile_static(digest, "edge")
    second = runtime.reconcile_static(digest, "edge")

    assert first["state"] == "CONVERGED"
    assert first["action"] == "DEPLOY"
    assert second["state"] == "CONVERGED"
    assert second["action"] == "NONE"
    assert second["deployment_id"] == first["deployment_id"]
    assert len(runtime.list()) == 1


def test_reconciliation_detects_tampering_and_repairs_target(tmp_path: Path):
    source = ContentAddressedArtifactStore(tmp_path / "source")
    digest = _artifact(source, b"trusted")
    runtime = DeploymentRuntime(tmp_path / "runtime", source)
    first = runtime.reconcile_static(digest, "edge")
    first_record = runtime.get(first["deployment_id"])
    assert first_record is not None
    Path(first_record.release_path, "payload").write_bytes(b"tampered")

    repaired = runtime.reconcile_static(digest, "edge")

    assert repaired["state"] == "CONVERGED"
    assert repaired["action"] == "DEPLOY"
    assert repaired["deployment_id"] != first["deployment_id"]
    current = runtime.get(repaired["deployment_id"])
    assert current is not None
    assert Path(current.release_path, "payload").read_bytes() == b"trusted"

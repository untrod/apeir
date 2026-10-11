"""Creation evidence survives mutable Environment lifecycle records."""

import hashlib
import json

import pytest

from nous_runtime.environments import EnvironmentProviderError, EnvironmentRuntime
from tests.environments.test_environment_runtime import FakeProvider, _runtime, _spec


@pytest.mark.parametrize("fail_prepare", [False, True])
def test_original_contract_artifact_survives_lifecycle_and_restart(
    tmp_path, fail_prepare
):
    runtime, provider = _runtime(tmp_path, FakeProvider(fail_prepare=fail_prepare))
    created = runtime.create(_spec())
    artifact = runtime.artifacts.get(created["artifact_id"])
    snapshot = tmp_path / artifact.location
    original = snapshot.read_bytes()
    initial = json.loads(original)
    assert initial["state"] == "created"
    assert artifact.metadata["sha256"] == hashlib.sha256(original).hexdigest()
    assert artifact.metadata["environment_contract_sha256"] == created["sha256"]
    assert artifact.metadata["run_id"] == created["operation_run_id"]
    assert artifact.metadata["task_id"] == "task-environment-test"
    assert artifact.metadata["size_bytes"] == len(original)
    assert snapshot != runtime._environment_path(created["environment_id"])
    if fail_prepare:
        with pytest.raises(EnvironmentProviderError, match="prepare failure"):
            runtime.start(created["environment_id"])
        assert runtime.get(created["environment_id"])["state"] == "failed"
    else:
        runtime.start(created["environment_id"])
        runtime.run(created["environment_id"], {"argv": ["python", "-V"]})
        runtime.stop(created["environment_id"])
    runtime.destroy(created["environment_id"])
    reopened = EnvironmentRuntime(tmp_path, providers=runtime.providers)
    assert reopened.get(created["environment_id"])["state"] == "destroyed"
    assert reopened.artifacts.get(artifact.id).location == artifact.location
    assert snapshot.read_bytes() == original
    assert reopened._read_environment(snapshot).digest() == created["sha256"]


def test_snapshot_failure_never_registers_contract_evidence(tmp_path, monkeypatch):
    runtime, provider = _runtime(tmp_path)
    write = runtime._write_environment

    def fail_snapshot(path, environment):
        if path.is_relative_to(runtime.outputs):
            raise OSError("contract snapshot persistence failed")
        return write(path, environment)

    monkeypatch.setattr(runtime, "_write_environment", fail_snapshot)
    with pytest.raises(OSError, match="snapshot persistence failed"):
        runtime.create(_spec())
    assert runtime.artifacts.list() == []
    assert runtime.list_environments()[0]["state"] == "created"
    assert not provider.stopped and not provider.destroyed


def test_contract_snapshot_cannot_escape_workspace_through_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    outputs = workspace / "artifacts"
    outputs.mkdir()
    try:
        (outputs / "environments").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this platform")
    runtime, _ = _runtime(workspace)
    from nous_runtime.environments import EnvironmentValidationError

    with pytest.raises(EnvironmentValidationError, match="escaped output storage"):
        runtime.create(_spec())
    assert list(external.iterdir()) == []
    assert runtime.artifacts.list() == []


def test_artifact_api_reads_persisted_metadata_and_never_invents_availability(
    tmp_path, monkeypatch
):
    from nous_runtime.api.routes import handle_get_artifact, handle_list_artifacts

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    assert not handle_get_artifact("artifact_not_registered")["ok"]
    assert handle_list_artifacts()["data"]["artifacts"] == []
    assert not (tmp_path / ".nous").exists()
    runtime, _ = _runtime(tmp_path)
    created = runtime.create(_spec())
    runtime.start(created["environment_id"])
    metadata = handle_get_artifact(created["artifact_id"])
    assert metadata["ok"] and metadata["data"]["status"] == "registered"
    assert metadata["data"]["effect_verification_performed"] is False
    artifact = metadata["data"]["artifact"]
    assert (
        hashlib.sha256((tmp_path / artifact["location"]).read_bytes()).hexdigest()
        == artifact["metadata"]["sha256"]
    )
    listed = handle_list_artifacts(
        environment_id=created["environment_id"], task_id="task-environment-test"
    )
    assert listed["data"]["artifacts"] == [artifact]
    assert (
        handle_list_artifacts(environment_id="different-environment")["data"][
            "artifacts"
        ]
        == []
    )
    assert handle_list_artifacts(task_id="different-task")["data"]["artifacts"] == []
    assert not handle_get_artifact("artifact_arbitrary_success")["ok"]


def test_artifact_api_does_not_read_external_registry_symlink(tmp_path, monkeypatch):
    from nous_runtime.api.routes import handle_list_artifacts

    workspace = tmp_path / "workspace"
    (workspace / ".nous").mkdir(parents=True)
    external = tmp_path / "external.jsonl"
    external.write_text("{}\n")
    try:
        (workspace / ".nous" / "artifacts.jsonl").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks unavailable on this platform")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(workspace))
    assert not handle_list_artifacts()["ok"]

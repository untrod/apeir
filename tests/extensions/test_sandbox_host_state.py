import sys

import pytest

from nous_runtime.kernel.sandbox import SandboxPolicy
from nous_runtime.kernel.windows_sandbox import (
    _commit_writable_mappings,
    _stage_mappings,
    _validate_mapping_root,
)


@pytest.mark.parametrize("name", [".nous", ".apeir", ".git", ".NOUS"])
def test_protected_state_directory_cannot_be_a_mapping_root(tmp_path, name):
    state = tmp_path / name
    state.mkdir()
    with pytest.raises(ValueError, match="protected host state"):
        _validate_mapping_root(state, [])


def test_explicit_descendant_of_state_directory_is_a_bounded_mapping(tmp_path):
    workdir = tmp_path / ".nous" / "environments" / "workdirs" / "env-1"
    workdir.mkdir(parents=True)
    _validate_mapping_root(workdir, [])


@pytest.mark.parametrize("name", [".nous", ".apeir", ".git", ".NOUS"])
def test_runtime_state_is_not_exposed_or_overwritten(tmp_path, name):
    workspace = tmp_path / "work"
    state = workspace / name
    state.mkdir(parents=True)
    record = state / "state.db"
    record.write_bytes(b"host-only")
    source = workspace / "source.py"
    source.write_text("original")
    policy = SandboxPolicy(executable=sys.executable, working_dir=str(workspace))
    staged, commits = _stage_mappings(
        [(workspace, r"C:\NousWorkspace", False)], tmp_path / "staged", policy,
    )
    snapshot = staged[0][0]
    assert not (snapshot / name).exists()
    record.write_bytes(b"host-updated-during-execution")
    (snapshot / "source.py").write_text("updated")
    _commit_writable_mappings(commits, [])
    assert record.read_bytes() == b"host-updated-during-execution"
    assert source.read_text() == "updated"


def test_guest_cannot_inject_runtime_state(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    source = workspace / "source.py"
    source.write_text("original")
    policy = SandboxPolicy(executable=sys.executable, working_dir=str(workspace))
    staged, commits = _stage_mappings(
        [(workspace, r"C:\NousWorkspace", False)], tmp_path / "staged", policy,
    )
    snapshot = staged[0][0]
    (snapshot / "source.py").write_text("changed")
    (snapshot / ".nous").mkdir()
    with pytest.raises(ValueError, match="protected host state"):
        _commit_writable_mappings(commits, [])
    assert source.read_text() == "original"
    assert not (workspace / ".nous").exists()

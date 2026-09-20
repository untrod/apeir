"""Cancellation stays on the host; output publication retains its limits."""

import sys
from pathlib import Path

import pytest

from nous_runtime.environments.models import EnvironmentCommand, EnvironmentValidationError
from nous_runtime.kernel.sandbox import SandboxPolicy
from nous_runtime.kernel import windows_sandbox as backend


@pytest.mark.parametrize("path", ["../stop", "C:/stop", "/stop", ".", "stop:stream"])
def test_cancel_marker_cannot_escape_environment(path):
    with pytest.raises(EnvironmentValidationError):
        EnvironmentCommand.from_mapping({"argv": ["python"], "cancel_file": path})


def test_cancel_marker_survives_command_serialization():
    command = EnvironmentCommand.from_mapping({"argv": ["python"], "cancel_file": "stop.flag"})
    assert EnvironmentCommand.from_mapping(command.to_dict()) == command


def test_prestart_cancel_never_launches_vm(tmp_path, monkeypatch):
    marker = tmp_path / "stop.flag"
    marker.touch()
    monkeypatch.setattr(backend, "executable_path", lambda: "WindowsSandbox.exe")
    def unexpected_launch(*args, **kwargs):
        pytest.fail("cancelled request launched a VM")
    monkeypatch.setattr(backend.subprocess, "Popen", unexpected_launch)
    result = backend.run(SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(tmp_path), cancel_file=str(marker),
    ))
    assert result.exit_code == 130
    assert not result.timed_out


def test_shared_result_retries_transient_lock_and_keeps_byte_bound(tmp_path, monkeypatch):
    result = tmp_path / "result.json"
    result.write_bytes(b"0123456789")
    original_open = Path.open
    attempts = []
    def shared_open(path, *args, **kwargs):
        if path == result:
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError("sharing violation")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", shared_open)
    assert backend._read_result_bytes(result, 4) == b"01234"
    assert len(attempts) == 3


def test_shared_result_does_not_hide_persistent_permission_failure(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("permanent denial")
    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(PermissionError):
        backend._read_result_bytes(tmp_path / "result.json", 10, retry_seconds=0)

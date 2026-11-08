from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from nous_runtime.environments.models import (
    EnvironmentCommand,
    EnvironmentValidationError,
)
from nous_runtime.kernel import linux_vm
from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy


def test_read_only_command_is_explicit_and_legacy_serialization_is_preserved():
    original = EnvironmentCommand.from_mapping({"argv": ["python", "-V"]})
    assert "read_only_workspace" not in original.to_dict()
    command = EnvironmentCommand.from_mapping(
        {"argv": ["python", "-V"], "read_only_workspace": True}
    )
    assert (
        EnvironmentCommand.from_mapping(command.to_dict()).read_only_workspace is True
    )
    with pytest.raises(EnvironmentValidationError, match="must be a boolean"):
        EnvironmentCommand.from_mapping(
            {"argv": ["python"], "read_only_workspace": "true"}
        )


@pytest.fixture
def profile(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("Linux ownership and trusted helper admission contract")
    root = tmp_path / "profile"
    root.mkdir(mode=0o700)
    (root / "libraries").mkdir()
    (root / "data").mkdir()
    files = {}
    for name in ("qemu", "kernel", "firmware", "runtime.cpio.gz"):
        path = root / name
        path.write_bytes(name.encode())
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = {
        "schema_version": 1,
        "architecture": "x86_64",
        "files": files,
        "qemu": "qemu",
        "kernel": "kernel",
        "firmware": "firmware",
        "image": "runtime.cpio.gz",
        "libraries": "libraries",
        "data": "data",
        "python_sha256": linux_vm._digest(Path(sys.executable).resolve()),
        "python_version": sys.version.split()[0],
        "guest_controller_sha256": linux_vm._digest(
            Path(linux_vm.__file__).with_name("linux_vm_guest.py")
        ),
    }
    path = root / "profile.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("APEIR_LINUX_VM_PROFILE", str(path))
    monkeypatch.setenv("APEIR_LINUX_VM_PROFILE_SHA256", linux_vm._digest(path))
    return root, path, value


def test_profile_inventory_is_verified_before_any_host_process(profile):
    root, _, value = profile
    assert linux_vm.load_profile() == (root, value)
    (root / "kernel").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        linux_vm.load_profile()


@pytest.mark.parametrize("name", ["../escape", "/absolute", r"library\escape"])
def test_profile_paths_cannot_escape(profile, monkeypatch, name):
    _, path, value = profile
    value["files"][name] = "0" * 64
    path.write_text(json.dumps(value))
    monkeypatch.setenv("APEIR_LINUX_VM_PROFILE_SHA256", linux_vm._digest(path))
    with pytest.raises(ValueError, match="invalid VM profile path"):
        linux_vm.load_profile()


def test_extra_loader_inputs_are_rejected(profile):
    root, _, _ = profile
    (root / "libraries" / "libmalicious.so").write_bytes(b"unreviewed")
    with pytest.raises(ValueError, match="inventory mismatch"):
        linux_vm.load_profile()


def test_writable_or_linked_profile_inputs_are_rejected(profile):
    root, _, _ = profile
    (root / "kernel").chmod(0o666)
    with pytest.raises(ValueError, match="publicly writable"):
        linux_vm.load_profile()
    (root / "kernel").chmod(0o600)
    (root / "kernel").unlink()
    (root / "kernel").symlink_to(root / "firmware")
    with pytest.raises(ValueError, match="links"):
        linux_vm.load_profile()


@pytest.mark.parametrize(
    "settings",
    [
        {"network_allowed": True},
        {"write_allowed_paths": ["/tmp"]},
        {"executable": "/bin/sh"},
        {"isolation_level": "relaxed"},
    ],
)
def test_profile_cannot_grant_unsupported_policy(profile, settings):
    policy = SandboxPolicy(**{"executable": sys.executable, **settings})
    assert linux_vm.supported(policy) is False


def test_missing_profile_fails_closed_without_host_execution(tmp_path, monkeypatch):
    monkeypatch.delenv("APEIR_LINUX_VM_PROFILE", raising=False)
    marker = tmp_path / "host-effect"
    result = ProcessSandbox(
        SandboxPolicy(
            executable=sys.executable,
            args=["-c", f'open({str(marker)!r},"w").write("bad")'],
            working_dir=str(tmp_path),
            read_allowed_paths=[str(tmp_path)],
        )
    ).run()
    assert not result.success
    assert not marker.exists()


def _message(key, nonce, kind="result"):
    data = json.dumps({"nonce": nonce, "kind": kind}).encode()
    signature = hmac.new(key, data, hashlib.sha256).hexdigest()
    return b"APEIR_VM:" + signature.encode() + b":" + base64.b64encode(data)


def test_guest_result_requires_per_invocation_authentication():
    key = os.urandom(32)
    message = _message(key, "one")
    assert linux_vm._authenticated(message, key, "one")["kind"] == "result"
    with pytest.raises(ValueError, match="unauthenticated"):
        linux_vm._authenticated(message, os.urandom(32), "one")
    with pytest.raises(ValueError, match="another invocation"):
        linux_vm._authenticated(message, key, "two")
    assert linux_vm._authenticated(b"normal guest boot output", key, "one") is None


@pytest.mark.parametrize("name", ["/init", "../init", r"control\request", "a\0b"])
def test_guest_archive_rejects_unsafe_paths(name):
    with pytest.raises(ValueError, match="unsafe guest archive path"):
        linux_vm.cpio([(name, b"bad", stat.S_IFREG | 0o444)])


def test_guest_archive_is_reproducible():
    assert linux_vm.cpio(
        [("project/a.py", b"pass", stat.S_IFREG | 0o444)]
    ) == linux_vm.cpio([("project/a.py", b"pass", stat.S_IFREG | 0o444)])


def test_snapshot_limits_are_checked_before_full_digest_walk(tmp_path):
    (tmp_path / "one").write_text("1234")
    (tmp_path / "two").write_text("5678")
    policy = SandboxPolicy(executable=sys.executable, max_staging_files=1)
    with pytest.raises(ValueError, match="staging limits"):
        linux_vm._bounded_project(tmp_path, policy)
    policy.max_staging_files = 5
    policy.max_staging_bytes = 4
    with pytest.raises(ValueError, match="staging limits"):
        linux_vm._bounded_project(tmp_path, policy)


def test_guest_controller_rejects_host_invocation_before_any_execution(monkeypatch):
    from nous_runtime.kernel import linux_vm_guest

    calls = []
    monkeypatch.setattr(
        linux_vm_guest.subprocess, "Popen", lambda *a, **kw: calls.append(a)
    )
    with pytest.raises(RuntimeError, match="isolated VM init"):
        linux_vm_guest.main()
    assert calls == []

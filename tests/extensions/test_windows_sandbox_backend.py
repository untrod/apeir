from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import nous_runtime.kernel.windows_sandbox as windows_sandbox
from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy
from nous_runtime.kernel.windows_sandbox import (
    _build_mappings,
    _configuration_xml,
    _safe_environment,
    _snapshot_readonly_mappings,
    _stage_mappings,
    _commit_writable_mappings,
    _translate_argument,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
def test_windows_sandbox_maps_only_explicit_roots(tmp_path: Path):
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    control = tmp_path / "control"
    workspace.mkdir()
    runtime.mkdir()
    control.mkdir()
    executable = runtime / "tool.exe"
    executable.write_bytes(b"fixture")
    policy = SandboxPolicy(
        executable=str(executable),
        working_dir=str(workspace),
        read_allowed_paths=[str(runtime)],
        write_allowed_paths=[str(workspace)],
        network_allowed=False,
    )

    mappings, translations = _build_mappings(policy, control)

    assert {path for path, _, _ in mappings} == {
        control.resolve(),
        workspace.resolve(),
        runtime.resolve(),
    }
    assert (
        next(readonly for path, _, readonly in mappings if path == workspace) is False
    )
    assert _translate_argument(str(workspace / "out.txt"), translations).startswith(
        r"C:\NousWorkspace"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
def test_windows_sandbox_maps_virtual_environment_root(tmp_path: Path):
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "venv"
    base_runtime = tmp_path / "base-python"
    scripts = runtime / "Scripts"
    site_packages = runtime / "Lib" / "site-packages"
    control = tmp_path / "control"
    workspace.mkdir()
    base_runtime.mkdir()
    scripts.mkdir(parents=True)
    site_packages.mkdir(parents=True)
    control.mkdir()
    config = runtime / "pyvenv.cfg"
    config.write_text(f"home = {base_runtime}\n", encoding="utf-8")
    executable = scripts / "python.exe"
    executable.write_bytes(b"fixture")
    policy = SandboxPolicy(
        executable=str(executable),
        working_dir=str(workspace),
        write_allowed_paths=[str(workspace)],
        network_allowed=False,
    )

    mappings, translations = _build_mappings(policy, control)

    assert all(item[0] != runtime.resolve() for item in mappings)
    base_mapping = next(item for item in mappings if item[1] == r"C:\NousBaseRuntime")
    assert base_mapping == (base_runtime.resolve(), r"C:\NousBaseRuntime", True)
    package_mapping = next(item for item in mappings if item[1] == r"C:\NousPackages")
    assert package_mapping == (site_packages.resolve(), r"C:\NousPackages", True)
    assert all(host != runtime.resolve() for host, _guest in translations)

    staged, _ = _stage_mappings(mappings, tmp_path / "staged", policy)
    mapped_packages = next(
        path for path, guest, _ in staged if guest == r"C:\NousPackages"
    )
    assert mapped_packages == site_packages.resolve()
    assert config.read_text(encoding="utf-8") == f"home = {base_runtime}\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
def test_windows_sandbox_adds_src_layout_to_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    runtime = tmp_path / "venv"
    base_runtime = tmp_path / "base-python"
    scripts = runtime / "Scripts"
    site_packages = runtime / "Lib" / "site-packages"
    base_runtime.mkdir()
    scripts.mkdir(parents=True)
    site_packages.mkdir(parents=True)
    (runtime / "pyvenv.cfg").write_text(f"home = {base_runtime}\n", encoding="utf-8")
    executable = scripts / "python.exe"
    executable.write_bytes(b"fixture")
    (base_runtime / "python.exe").write_bytes(b"fixture")
    policy = SandboxPolicy(
        executable=str(executable),
        args=["-m", "pytest"],
        working_dir=str(workspace),
        write_allowed_paths=[str(workspace)],
        network_allowed=False,
    )
    captured: dict[str, object] = {}

    def fake_popen(*_args, **_kwargs):
        request = json.loads(
            (tmp_path / "task" / "control" / "request.json").read_text()
        )
        captured.update(request)
        raise OSError("capture after request creation")

    def fake_mkdtemp(**_kwargs):
        task = tmp_path / "task"
        task.mkdir()
        return str(task)

    monkeypatch.setattr(windows_sandbox.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(windows_sandbox.subprocess, "Popen", fake_popen)
    result = windows_sandbox.run(policy)

    assert "capture after request creation" in result.stderr
    assert captured["environment"]["PYTHONPATH"] == (
        r"C:\NousWorkspace\src;C:\NousPackages"
    )
    assert captured["environment"]["APEIR_SANDBOX_PACKAGES"] == (r"C:\NousPackages")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
def test_working_directory_is_read_only_without_explicit_write_scope(tmp_path: Path):
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    control = tmp_path / "control"
    workspace.mkdir()
    runtime.mkdir()
    control.mkdir()
    executable = runtime / "tool.exe"
    executable.write_bytes(b"fixture")
    policy = SandboxPolicy(
        executable=str(executable),
        working_dir=str(workspace),
        read_allowed_paths=[str(workspace)],
        write_allowed_paths=[],
        network_allowed=False,
    )

    mappings, _ = _build_mappings(policy, control)

    assert next(readonly for path, _, readonly in mappings if path == workspace) is True


def test_windows_sandbox_configuration_disables_host_channels(tmp_path: Path):
    xml = _configuration_xml(
        [(tmp_path, r"C:\NousWorkspace", False)], 256 * 1024 * 1024
    )

    assert "<Networking>Disable</Networking>" in xml
    assert "<ClipboardRedirection>Disable</ClipboardRedirection>" in xml
    assert "<AudioInput>Disable</AudioInput>" in xml
    assert "<VideoInput>Disable</VideoInput>" in xml
    assert "<PrinterRedirection>Disable</PrinterRedirection>" in xml
    assert "<MemoryInMB>2048</MemoryInMB>" in xml


def test_windows_sandbox_environment_drops_secret_material():
    result = _safe_environment(
        {
            "PUBLIC_SETTING": "yes",
            "NOUS_TOKEN_PROVIDER": "secret",
            "NOUS_SECRET_VALUE": "secret",
            "APEIR_TOKEN_PROVIDER": "secret",
            "APEIR_SECRET_VALUE": "secret",
            "LD_PRELOAD": "inject",
        }
    )

    assert result == {"PUBLIC_SETTING": "yes"}


def test_security_report_labels_ready_windows_vm_strong(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "nous_runtime.kernel.windows_sandbox.executable_path",
        lambda: r"C:\Windows\System32\WindowsSandbox.exe",
    )
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(Path.cwd()),
        network_allowed=False,
    )

    report = ProcessSandbox(policy).security_report()

    assert report["strong"] is True
    assert report["grade"] == "strong_vm"
    assert report["c3_certified"] is True
    assert "staged_filesystem" in report["enforced_controls"]
    assert "job_memory_budget" in report["enforced_controls"]
    assert "job_cpu_budget" in report["enforced_controls"]
    assert "job_process_limit" in report["enforced_controls"]
    assert report["unenforced_controls"] == ()
    assert "host_os_and_local_user_trusted" in report["trust_assumptions"]
    assert (
        "business_result_requires_independent_verifier" in report["trust_assumptions"]
    )
    assert "result_verification_label" in report["enforced_controls"]
    assert "network_disabled" in report["enforced_controls"]


def test_networked_process_is_never_labeled_strong(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "nous_runtime.kernel.windows_sandbox.executable_path",
        lambda: r"C:\Windows\System32\WindowsSandbox.exe",
    )
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(Path.cwd()),
        network_allowed=True,
    )

    assert ProcessSandbox(policy).security_report()["strong"] is False


def test_windows_sandbox_sessions_are_serialized(monkeypatch):
    active = 0
    maximum_active = 0
    gate = threading.Lock()

    def fake_run(_policy, _input_bytes=None):
        nonlocal active, maximum_active
        with gate:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with gate:
            active -= 1
        return windows_sandbox.WindowsSandboxExecution(exit_code=0)

    monkeypatch.setattr(windows_sandbox, "_run_locked", fake_run)
    monkeypatch.setattr(windows_sandbox, "_RELAUNCH_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(windows_sandbox, "_last_run_finished_at", 0.0)
    policy = SandboxPolicy()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: windows_sandbox.run(policy), range(2)))

    assert [result.exit_code for result in results] == [0, 0]
    assert maximum_active == 1


def test_readonly_workspace_is_replaced_by_content_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    control = tmp_path / "control"
    staged = tmp_path / "staged"
    workspace.mkdir()
    control.mkdir()
    (workspace / "input.txt").write_text("stable", encoding="utf-8")
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(workspace),
        read_allowed_paths=[str(workspace)],
        write_allowed_paths=[],
    )
    # Exercise staging independently of mapping-root admission. Hosted Windows
    # runners place their temporary directory below a reparse point, which the
    # production admission path correctly rejects.
    mappings = [
        (control.resolve(), r"C:\NousControl", True),
        (workspace.resolve(), r"C:\NousWorkspace", True),
    ]
    result = _snapshot_readonly_mappings(mappings, staged, policy)
    mapped = next(host for host, guest, _ in result if guest == r"C:\NousWorkspace")
    assert mapped != workspace.resolve()
    assert mapped.is_relative_to(staged)
    assert (mapped / "input.txt").read_text(encoding="utf-8") == "stable"


def test_snapshot_budget_fails_before_copy(tmp_path):
    workspace = tmp_path / "workspace"
    control = tmp_path / "control"
    workspace.mkdir()
    control.mkdir()
    (workspace / "large.bin").write_bytes(b"x" * 32)
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(workspace),
        max_staging_bytes=16,
    )
    mappings = [
        (control.resolve(), r"C:\NousControl", True),
        (workspace.resolve(), r"C:\NousWorkspace", True),
    ]
    with pytest.raises(ValueError, match="staging limits"):
        _snapshot_readonly_mappings(mappings, tmp_path / "staged", policy)
    assert not (tmp_path / "staged").exists()


def test_writable_mapping_is_staged_and_guarded_commit(tmp_path):
    workspace = tmp_path / "workspace"
    control = tmp_path / "control"
    staged_root = tmp_path / "staged"
    workspace.mkdir()
    control.mkdir()
    (workspace / "before.txt").write_text("before", encoding="utf-8")
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(workspace),
        write_allowed_paths=[str(workspace)],
    )
    mappings = [
        (control.resolve(), r"C:\NousControl", True),
        (workspace.resolve(), r"C:\NousWorkspace", False),
    ]
    staged, commits = _stage_mappings(mappings, staged_root, policy)
    staged_workspace = next(
        root for root, guest, _ in staged if guest == r"C:\NousWorkspace"
    )
    staged_workspace.joinpath("after.txt").write_text("after", encoding="utf-8")
    _commit_writable_mappings(commits, [])
    assert (workspace / "after.txt").read_text(encoding="utf-8") == "after"


def test_writable_commit_rejects_host_mutation(tmp_path):
    workspace = tmp_path / "workspace"
    control = tmp_path / "control"
    workspace.mkdir()
    control.mkdir()
    (workspace / "before.txt").write_text("before", encoding="utf-8")
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        working_dir=str(workspace),
        write_allowed_paths=[str(workspace)],
    )
    mappings = [
        (control.resolve(), r"C:\NousControl", True),
        (workspace.resolve(), r"C:\NousWorkspace", False),
    ]
    _, commits = _stage_mappings(mappings, tmp_path / "staged", policy)
    (workspace / "host-change.txt").write_text("external", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        _commit_writable_mappings(commits, [])

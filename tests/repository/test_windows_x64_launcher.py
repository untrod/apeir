from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_windows_x64_launcher_builds_all_authoritative_layers() -> None:
    script = _read("scripts/build-windows-x64-launcher.ps1")

    assert "x86_64-pc-windows-msvc" in script
    assert "windows_native_preflight.ps1" in script
    assert "nous-sidecar.spec" in script
    assert "SkipRuntimeSidecarBuild" in script
    assert "stage-kernel-components.ps1" in script
    assert script.index("stage-kernel-components.ps1") < script.index(
        "if (-not $SkipValidation)"
    )
    assert script.index("stage-kernel-components.ps1") < script.index(
        "python -m PyInstaller"
    )
    assert "nousd-$Target.exe" in script
    assert "nous-provider-worker-$Target.exe" in script
    assert "verify_windows_native_sidecars.ps1" in script
    assert "cargo check --locked" in script
    assert "cargo test --locked" in script
    assert "npm run tauri:build:x64" in script
    assert "APEIR-Portable" in script
    assert "SHA256SUMS-x64.txt" in script
    assert "SHA256SUMS.txt" in script
    assert "release-manifest.json" in script
    assert "native-validation-report.json" in script
    assert "build_timestamp_utc" in script
    assert "runtime_revision" in script
    assert "compiler_path" in script
    assert "windows_sdk_kernel32" in script


def test_native_sidecar_gate_is_architecture_and_authentication_aware() -> None:
    script = _read("scripts/ci/verify_windows_native_sidecars.ps1")

    assert "0x8664" in script
    assert "0xAA64" in script
    assert "NOUS_KERNEL_ENDPOINT" in script
    assert "NOUS_NKI_TOKEN" in script
    assert "Authorization = " in script
    assert "kernel_process_tree_closed" in script
    assert "provider_worker_health" in script
    assert "--stdio-once" in script


def test_launcher_preflights_runtime_before_starting_kernel() -> None:
    source = _read("desktop/src-tauri/src/main.rs")
    start = source.index("fn start_runtime_api_inner(manager: &RuntimeManager)")
    stop = source.index("fn stop_runtime_api_inner(manager: &RuntimeManager)")
    section = source[start:stop]

    assert section.index("find_nous_executable()?") < section.index(
        "start_nousd_inner(manager)?"
    )
    assert section.index("load_stored_provider_credentials()?") < section.index(
        "start_nousd_inner(manager)?"
    )
    assert "let _ = stop_nousd_inner(manager);" in section
    assert "let _ = stop_runtime_api_inner(manager);" in section


def test_kernel_launcher_cleanup_is_fail_safe() -> None:
    source = _read("desktop/src-tauri/src/main.rs")
    start = source.index("fn start_nousd_inner(manager: &RuntimeManager)")
    end = source.index("fn managed_nousd_status(manager: &RuntimeManager)")
    section = source[start:end]

    assert "match manager.nousd_child.lock()" in section
    assert "let _ = child.kill();" in section
    assert "let _ = stop_nousd_inner(manager);" in section
    assert "let process_result =" in section
    assert "manager.kernel_token.lock().map(|mut token| token.take())" in section


def test_launcher_shutdown_attempts_runtime_and_kernel_cleanup() -> None:
    source = _read("desktop/src-tauri/src/main.rs")
    start = source.index("fn stop_runtime_api_inner(manager: &RuntimeManager)")
    end = source.index("#[tauri::command]", start)
    section = source[start:end]

    assert "let runtime_result =" in section
    assert "let kernel_result = stop_nousd_inner(manager);" in section
    assert "match (runtime_result, kernel_result)" in section


def test_release_manifest_paths_support_windows_powershell_51() -> None:
    script = _read("scripts/build-windows-x64-launcher.ps1")

    assert "[System.IO.Path]::GetRelativePath" not in script
    assert "$artifactRootPrefix" in script
    assert "[System.StringComparison]::OrdinalIgnoreCase" in script
    assert "Release artifact escaped the artifact root" in script


def test_ci_windows_packaging_cannot_substitute_its_own_unverified_builder():
    workflow = yaml.safe_load(_read(".github/workflows/desktop-build.yml"))
    events = workflow.get("on", workflow.get(True))
    assert events["workflow_dispatch"]["inputs"]["native_target"]["default"] == "none"
    job = workflow["jobs"]["build-windows-x64"]
    assert "vars.APEIR_BINARY_RELEASE_ENABLED == 'true'" in job["if"]
    assert "inputs.native_target == 'windows-x64'" in job["if"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    commands = [step.get("run", "") for step in job["steps"]]
    admission = next(
        i for i, command in enumerate(commands) if "--artifact-zip" in command
    )
    build = next(
        i
        for i, command in enumerate(commands)
        if "build-windows-x64-launcher.ps1" in command
    )
    assert admission < build
    assert "--artifact-sha256" in commands[admission]
    assert "--kernel-root kernel-native-source" in commands[admission]
    assert "-Skip" not in commands[build]
    assert not any("npx tauri build" in command for command in commands)
    assert any(
        step.get("with", {}).get("path") == "distribution/artifacts/windows-x64/"
        for step in job["steps"]
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell staging contract")
@pytest.mark.parametrize(
    "fault", [None, "hash", "missing-worker", "architecture", "dirty-source"]
)
def test_staging_admits_complete_bundle_before_replacing_any_file(tmp_path, fault):
    """Synthetic PE contracts; no fixture is ever executed as a native program."""
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "Windows native build host requires PowerShell"
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    (kernel / "source.txt").write_text("frozen fixture")
    subprocess.run(["git", "init", "-q"], cwd=kernel, check=True)
    subprocess.run(["git", "add", "source.txt"], cwd=kernel, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=kernel,
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=kernel, text=True
    ).strip()
    repo, incoming = tmp_path / "distribution", tmp_path / "bundle"
    verifier = repo / "scripts/ci/verify_kernel_components.py"
    verifier.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "scripts/ci/verify_kernel_components.py", verifier)
    entries, original = [], {}
    for name in ("nousd", "nous-provider-worker"):
        relative = f"desktop/src-tauri/binaries/{name}-x86_64-pc-windows-msvc.exe"
        data = bytearray(256)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<H", data, 132, 0x014C if fault == "architecture" else 0x8664)
        source, destination = incoming / relative, repo / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
        destination.write_bytes(b"previous staged fixture")
        original[relative] = destination.read_bytes()
        entries.append(
            {
                "name": name,
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "pe_machine": "0x8664",
            }
        )
    lock = repo / "runtime-components.lock.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": {
                    "nous-kernel": {
                        "revision": revision,
                        "target": "x86_64-pc-windows-msvc",
                        "artifacts": entries,
                    }
                },
            }
        )
    )
    if fault == "hash":
        (incoming / entries[0]["path"]).write_bytes(b"changed after review")
    elif fault == "missing-worker":
        (incoming / entries[1]["path"]).unlink()
    elif fault == "dirty-source":
        (kernel / "source.txt").write_text("changed source")
    environment = dict(os.environ)
    environment["PATH"] = (
        str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    )
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-File",
            str(REPO_ROOT / "scripts/stage-kernel-components.ps1"),
            "-KernelRoot",
            str(kernel),
            "-RepoRoot",
            str(repo),
            "-Target",
            "x86_64-pc-windows-msvc",
            "-SkipBuild",
            "-ArtifactDirectory",
            str(incoming),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is (fault is None), result.stderr
    for relative, before in original.items():
        assert (repo / relative).read_bytes() == (
            (incoming / relative).read_bytes() if fault is None else before
        )

from __future__ import annotations

from pathlib import Path


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
    start = source.index(
        "fn start_runtime_api_inner(manager: &RuntimeManager)"
    )
    stop = source.index(
        "fn stop_runtime_api_inner(manager: &RuntimeManager)"
    )
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
    start = source.index(
        "fn start_nousd_inner(manager: &RuntimeManager)"
    )
    end = source.index(
        "fn managed_nousd_status(manager: &RuntimeManager)"
    )
    section = source[start:end]

    assert "match manager.nousd_child.lock()" in section
    assert "let _ = child.kill();" in section
    assert "let _ = stop_nousd_inner(manager);" in section
    assert "let process_result =" in section
    assert "manager.kernel_token.lock().map(|mut token| token.take())" in section

def test_launcher_shutdown_attempts_runtime_and_kernel_cleanup() -> None:
    source = _read("desktop/src-tauri/src/main.rs")
    start = source.index(
        "fn stop_runtime_api_inner(manager: &RuntimeManager)"
    )
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

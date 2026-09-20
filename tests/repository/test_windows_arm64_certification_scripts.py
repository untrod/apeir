from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_sidecar_smoke_starts_authenticated_kernel_before_runtime() -> None:
    script = _read("scripts/ci/verify_windows_arm64_sidecar.ps1")

    assert "[string]$KernelPath" in script
    assert "[string]$ProviderWorkerPath" in script
    assert "requires an ARM64 Windows host" in script
    assert '$env:NOUS_KERNEL_ENDPOINT = "tcp://127.0.0.1:$kernelPort"' in script
    assert "$env:NOUS_NKI_TOKEN = $kernelToken" in script
    assert "$kernelParent = Start-Process @kernelStart" in script
    assert "$parent = Start-Process @runtimeStart" in script
    assert script.index("$kernelParent = Start-Process @kernelStart") < script.index(
        "$parent = Start-Process @runtimeStart"
    )
    assert "kernel_process_tree_closed" in script


def test_bundle_smoke_passes_all_installed_sidecars() -> None:
    script = _read("scripts/ci/verify_windows_arm64_bundle.ps1")

    assert "-KernelPath $installedKernel.FullName" in script
    assert "-ProviderWorkerPath $installedWorker.FullName" in script


def test_arm64_workflow_enforces_component_lock_and_joint_smoke() -> None:
    workflow = _read(".github/workflows/desktop-build.yml")

    assert "verify_kernel_components.py --repo-root ." in workflow
    assert "-KernelPath ./desktop/src-tauri/binaries/nousd-aarch64-pc-windows-msvc.exe" in workflow
    assert (
        "-ProviderWorkerPath "
        "./desktop/src-tauri/binaries/nous-provider-worker-aarch64-pc-windows-msvc.exe"
        in workflow
    )


def test_native_preflight_reports_all_required_toolchain_surfaces() -> None:
    script = _read("scripts/ci/windows_native_preflight.ps1")

    for requirement in (
        "can_execute_target",
        "Visual Studio 2022 C++ Build Tools",
        "cl.exe",
        "link.exe",
        "kernel32.lib",
    ):
        assert requirement in script


def test_native_certification_entry_runs_every_p5_gate() -> None:
    script = _read("scripts/ci/certify_windows_native.ps1")

    assert "scripts\\test.ps1" in script
    assert "scripts\\stage-kernel-components.ps1" in script
    assert "cargo check --locked" in script
    assert "cargo test --locked" in script
    assert "verify_windows_arm64_sidecar.ps1" in script
    assert "$preflight.ready" in script

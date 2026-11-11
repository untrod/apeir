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
    assert (
        "-KernelPath ./desktop/src-tauri/binaries/nousd-aarch64-pc-windows-msvc.exe"
        in workflow
    )
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


def test_arm64_candidate_is_native_and_cannot_approve_packaging() -> None:
    import yaml

    workflow = yaml.safe_load(_read(".github/workflows/desktop-build.yml"))
    events = workflow.get("on", workflow.get(True))
    inputs = events["workflow_dispatch"]["inputs"]
    assert inputs["kernel_candidate_target"]["default"] == "x86_64-pc-windows-msvc"
    assert set(inputs["kernel_candidate_target"]["options"]) == {
        "x86_64-pc-windows-msvc",
        "aarch64-pc-windows-msvc",
    }
    candidate = workflow["jobs"]["locked-kernel-rebuild"]
    assert "windows-11-arm" in candidate["runs-on"]
    setup = next(
        step
        for step in candidate["steps"]
        if step.get("uses") == "actions/setup-python@v5"
    )
    assert "arm64" in setup["with"]["architecture"]
    commands = "\n".join(step.get("run", "") for step in candidate["steps"])
    assert "--target $env:KERNEL_CANDIDATE_TARGET" in commands
    assert "-Target $env:KERNEL_CANDIDATE_TARGET" in commands
    assert "component_lock_migration_approved = $false" in commands
    assert "installation_acceptance = 'NOT_RUN'" in commands
    assert (
        "cargo build --release" not in commands
    )  # version-pinned cargo +1.99.1 is required
    assert "cargo +1.99.1 build --release --locked" in commands
    assert "tauri build" not in commands
    assert "Set-Content runtime-components.lock.json" not in commands
    original = next(
        step for step in candidate["steps"] if step.get("id") == "original-lock"
    )
    assert "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }" in original["run"]

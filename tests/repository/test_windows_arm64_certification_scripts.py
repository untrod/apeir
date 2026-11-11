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
    assert "verify_windows_native_sidecars.ps1" in script
    assert '-Target "aarch64-pc-windows-msvc"' in script
    assert "-KernelPath $KernelPath" in script
    assert "-ProviderWorkerPath $ProviderWorkerPath" in script
    canonical = _read("scripts/ci/verify_windows_native_sidecars.ps1")
    assert '$env:NOUS_KERNEL_ENDPOINT = "tcp://127.0.0.1:$kernelPort"' in canonical
    assert "$env:NOUS_NKI_TOKEN = $kernelToken" in canonical
    assert canonical.index(
        "$kernelParent = Start-Process @kernelStart"
    ) < canonical.index("$parent = Start-Process @runtimeStart")
    assert "kernel_process_tree_closed" in canonical


def test_bundle_smoke_passes_all_installed_sidecars() -> None:
    script = _read("scripts/ci/verify_windows_arm64_bundle.ps1")

    assert "-KernelPath $installedKernel.FullName" in script
    assert "-ProviderWorkerPath $installedWorker.FullName" in script
    assert "github-hosted" in script
    assert "apeir-control-center.exe" in script
    assert "nous-control-center.exe" not in script
    assert "$currentUserRoot" not in script
    assert "if ($uninstall.ExitCode -ne 0)" in script
    assert "windows10_tablet_acceptance" in script


def test_arm64_workflow_enforces_component_lock_and_joint_smoke() -> None:
    workflow = _read(".github/workflows/desktop-build.yml")

    import yaml

    document = yaml.safe_load(workflow)
    job = document["jobs"]["build-windows-x64"]
    assert "inputs.native_target == 'windows-arm64'" in job["if"]
    assert "windows-11-arm" in job["runs-on"]
    assert "aarch64-pc-windows-msvc" in job["env"]["NATIVE_TARGET"]
    commands = [step.get("run", "") for step in job["steps"]]
    admission = next(i for i, c in enumerate(commands) if "--artifact-zip" in c)
    build = next(
        i for i, c in enumerate(commands) if "build-windows-x64-launcher.ps1" in c
    )
    assert admission < build
    assert "--target $env:NATIVE_TARGET" in commands[admission]
    assert "-Target $env:NATIVE_TARGET" in commands[build]
    assert "-Skip" not in commands[build]
    launcher = _read("scripts/build-windows-x64-launcher.ps1")
    assert '"nousd-$Target.exe"' in launcher
    assert '"nous-provider-worker-$Target.exe"' in launcher
    assert "verify_windows_native_sidecars.ps1" in launcher
    assert "tauri:build:arm64" in launcher
    assert "build-windows-arm64" not in document["jobs"]
    assert any(
        step.get("with", {}).get("name") == "windows-arm64-native-development-build"
        for step in job["steps"]
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

param(
    [Parameter(Mandatory = $true)]
    [string]$KernelRoot,
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$Target = "aarch64-pc-windows-msvc",
    [string]$ExpectedVersion = "0.1.0-rc1",
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
if ($Target -ne "aarch64-pc-windows-msvc") {
    throw "This certification entry currently covers only aarch64-pc-windows-msvc."
}
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$kernel = (Resolve-Path -LiteralPath $KernelRoot).Path
$preflightScript = Join-Path $repo "scripts\ci\windows_native_preflight.ps1"
$preflight = & $preflightScript -Target $Target
if ($PreflightOnly) {
    $preflight
    return
}
if (-not $preflight.ready) {
    $preflight | ConvertTo-Json -Depth 4
    throw "Windows native certification prerequisites are incomplete: $($preflight.missing -join ', ')."
}

$kernelTest = Join-Path $kernel "scripts\test.ps1"
if (-not (Test-Path -LiteralPath $kernelTest)) {
    throw "Kernel test entry point is missing: $kernelTest"
}
& $kernelTest

$stage = Join-Path $repo "scripts\stage-kernel-components.ps1"
& $stage -KernelRoot $kernel -RepoRoot $repo -Target $Target

$common = Join-Path $kernel "scripts\common.ps1"
. $common
$tauriManifest = Join-Path $repo "desktop\src-tauri\Cargo.toml"
$quotedManifest = '"' + $tauriManifest + '"'
Invoke-NousDeveloperCommand "cargo check --locked --target $Target --manifest-path $quotedManifest"
Invoke-NousDeveloperCommand "cargo test --locked --target $Target --manifest-path $quotedManifest"

$suffix = if ($Target -match "windows") { ".exe" } else { "" }
$binaryRoot = Join-Path $repo "desktop\src-tauri\binaries"
$sidecar = Join-Path $binaryRoot "nous-runtime-$Target$suffix"
$kernelSidecar = Join-Path $binaryRoot "nousd-$Target$suffix"
$workerSidecar = Join-Path $binaryRoot "nous-provider-worker-$Target$suffix"
if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Runtime sidecar is missing: $sidecar. Build the target-native PyInstaller sidecar first."
}

$smokeArgs = @{
    SidecarPath = $sidecar
    KernelPath = $kernelSidecar
    ProviderWorkerPath = $workerSidecar
    ExpectedVersion = $ExpectedVersion
}
$smoke = & (Join-Path $repo "scripts\ci\verify_windows_arm64_sidecar.ps1") @smokeArgs

[pscustomobject][ordered]@{
    status = "passed"
    target = $Target
    kernel_tests = $true
    kernel_components_locked = $true
    tauri_cargo_check = $true
    tauri_cargo_test = $true
    runtime_kernel_smoke = $true
    smoke = $smoke
}

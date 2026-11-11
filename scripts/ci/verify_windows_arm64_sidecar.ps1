param(
    [Parameter(Mandatory = $true)][string]$SidecarPath,
    [Parameter(Mandatory = $true)][string]$KernelPath,
    [Parameter(Mandatory = $true)][string]$ProviderWorkerPath,
    [string]$ExpectedVersion = "0.1.0-rc1",
    [string]$EvidenceDirectory = ""
)

$ErrorActionPreference = "Stop"
if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne "Arm64") {
    throw "ARM64 sidecar certification requires an ARM64 Windows host."
}
# Keep this public entry point, with one authoritative native smoke implementation.
& (Join-Path $PSScriptRoot "verify_windows_native_sidecars.ps1") `
    -SidecarPath $SidecarPath `
    -KernelPath $KernelPath `
    -ProviderWorkerPath $ProviderWorkerPath `
    -ExpectedVersion $ExpectedVersion `
    -EvidenceDirectory $EvidenceDirectory `
    -Target "aarch64-pc-windows-msvc"

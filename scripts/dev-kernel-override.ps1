param(
    [Parameter(Mandatory = $true)]
    [string]$KernelRoot,
    [Parameter(Mandatory = $true)]
    [switch]$EnableDevKernelOverride,
    [switch]$SkipBuild,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $EnableDevKernelOverride) {
    throw "Development Kernel override must be explicitly enabled."
}

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$kernel = (Resolve-Path -LiteralPath $KernelRoot).Path
$lock = Get-Content -LiteralPath (Join-Path $repo "runtime-components.lock.json") -Raw |
    ConvertFrom-Json
$lockedRevision = [string]$lock.components.'nous-kernel'.revision
$overrideRevision = (& git -C $kernel rev-parse HEAD).Trim()
$overrideBranch = (& git -C $kernel branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $overrideRevision) {
    throw "KernelRoot is not a readable git checkout."
}
if ($overrideBranch -ne "feature/reality-execution-v2") {
    throw "Development override must use feature/reality-execution-v2; got '$overrideBranch'."
}
if (-not $SkipBuild) {
    & (Join-Path $kernel "scripts\build.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Development Kernel build failed." }
}
if (-not $SkipTests) {
    & (Join-Path $kernel "scripts\test.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Development Kernel tests failed." }
}

$env:APEIR_KERNEL_ROOT = $kernel
[ordered]@{
    schema = "apeir.dev-kernel-override/v1"
    enabled = $true
    dev_only = $true
    kernel_root = $kernel
    branch = $overrideBranch
    kernel_sha = $overrideRevision
    release_lock_sha = $lockedRevision
    release_lock_modified = $false
    silent_fallback = $false
} | ConvertTo-Json -Depth 3

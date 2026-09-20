param(
    [Parameter(Mandatory = $true)]
    [string]$KernelRoot,
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Target = "aarch64-pc-windows-msvc",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$kernel = (Resolve-Path -LiteralPath $KernelRoot).Path
$lockPath = Join-Path $repo "runtime-components.lock.json"
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$component = $lock.components.'nous-kernel'

$actualRevision = (& git -C $kernel rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $component.revision) {
    throw "nous-kernel must be checked out at locked revision $($component.revision)."
}
if ($component.target -ne $Target) {
    throw "Target $Target is not present in the component lock."
}

if (-not $SkipBuild) {
    throw "Build the pinned Kernel release separately, then stage its verified release bundle. Source rebuilds are not substituted for locked release artifacts."
}

& python (Join-Path $repo "scripts\ci\verify_kernel_components.py") `
    --repo-root $repo `
    --lock $lockPath `
    --kernel-root $kernel
if ($LASTEXITCODE -ne 0) {
    throw "nous-kernel component verification failed."
}

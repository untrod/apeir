param(
    [Parameter(Mandatory = $true)]
    [string]$KernelRoot,
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Target = "aarch64-pc-windows-msvc",
    [string]$ArtifactDirectory = "",
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
$kernelChanges = (& git -C $kernel status --porcelain --untracked-files=no) -join "`n"
if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace($kernelChanges)) {
    throw "The frozen Kernel tracked source must be clean."
}
if ($component.target -ne $Target) {
    throw "Target $Target is not present in the component lock."
}

if (-not $SkipBuild) {
    throw "Build the pinned Kernel release separately, then stage its verified release bundle. Source rebuilds are not substituted for locked release artifacts."
}

if (-not [string]::IsNullOrWhiteSpace($ArtifactDirectory)) {
    $inputRoot = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
    # Admit the entire bundle with the existing verifier before replacing any
    # staged file. The immutable lock, not artifact metadata, decides acceptance.
    & python (Join-Path $repo "scripts\ci\verify_kernel_components.py") `
        --repo-root $inputRoot --lock $lockPath --kernel-root $kernel
    if ($LASTEXITCODE -ne 0) { throw "Input Kernel bundle failed component-lock admission." }
    foreach ($artifact in $component.artifacts) {
        $source = Join-Path $inputRoot $artifact.path
        $destination = Join-Path $repo $artifact.path
        if ([IO.Path]::GetFullPath($source) -eq [IO.Path]::GetFullPath($destination)) { continue }
        New-Item -ItemType Directory -Force (Split-Path $destination) | Out-Null
        $temporary = "$destination.$([guid]::NewGuid().ToString('N')).stage"
        try {
            Copy-Item -LiteralPath $source -Destination $temporary
            Move-Item -LiteralPath $temporary -Destination $destination -Force
        } finally {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        }
    }
}

& python (Join-Path $repo "scripts\ci\verify_kernel_components.py") `
    --repo-root $repo `
    --lock $lockPath `
    --kernel-root $kernel
if ($LASTEXITCODE -ne 0) {
    throw "nous-kernel component verification failed."
}

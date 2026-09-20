param(
    [string]$KernelRoot = (Resolve-Path "$PSScriptRoot\..\..\kernel").Path,
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Target = "x86_64-pc-windows-msvc",
    [string]$ExpectedVersion = "0.1.0-rc1",
    [string]$ArtifactRoot = "",
    [switch]$SkipValidation,
    [switch]$SkipSidecarSmoke,
    [switch]$SkipRuntimeSidecarBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Target -ne "x86_64-pc-windows-msvc") {
    throw "The Windows 10 launcher entry supports x86_64-pc-windows-msvc only."
}

$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$kernel = (Resolve-Path -LiteralPath $KernelRoot).Path
$desktop = Join-Path $repo "desktop"
$tauriRoot = Join-Path $desktop "src-tauri"
$binaryRoot = Join-Path $tauriRoot "binaries"
$lockPath = Join-Path $repo "runtime-components.lock.json"
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$component = $lock.components.'nous-kernel'
$actualRevision = (& git -C $kernel rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $component.revision) {
    throw "nous-kernel must be checked out at locked revision $($component.revision)."
}

$preflight = & (Join-Path $repo "scripts\ci\windows_native_preflight.ps1") -Target $Target
if (-not $preflight.ready) {
    $preflight | ConvertTo-Json -Depth 4
    throw "Windows X64 launcher prerequisites are incomplete: $($preflight.missing -join ', ')."
}

if (-not $SkipRuntimeSidecarBuild) {
    & python -c "import PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is missing. Install the project installer-build extra before building."
    }
}

if (-not $SkipValidation) {
    & python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Runtime tests failed." }

    Push-Location -LiteralPath $desktop
    try {
        & npm run lint
        if ($LASTEXITCODE -ne 0) { throw "Desktop lint failed." }
        & npm test
        if ($LASTEXITCODE -ne 0) { throw "Desktop tests failed." }
        & npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "Desktop typecheck failed." }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Desktop frontend build failed." }
    } finally {
        Pop-Location
    }

    & (Join-Path $kernel "scripts\test.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Kernel validation failed." }
}

$runtimeBuildOutput = Join-Path $repo "dist\nous-runtime.exe"
if (-not $SkipRuntimeSidecarBuild) {
    Push-Location -LiteralPath $repo
    try {
        & python -m PyInstaller --noconfirm --clean nous-sidecar.spec
        if ($LASTEXITCODE -ne 0) { throw "Runtime sidecar build failed." }
    } finally {
        Pop-Location
    }
} elseif (-not (Test-Path -LiteralPath $runtimeBuildOutput)) {
    throw "SkipRuntimeSidecarBuild requires an existing dist\nous-runtime.exe."
}
New-Item -ItemType Directory -Force -Path $binaryRoot | Out-Null
$runtimeSidecar = Join-Path $binaryRoot "nous-runtime-$Target.exe"
Copy-Item -LiteralPath $runtimeBuildOutput -Destination $runtimeSidecar -Force

& (Join-Path $repo "scripts\stage-kernel-components.ps1") `
    -KernelRoot $kernel `
    -RepoRoot $repo `
    -Target $Target `
    -SkipBuild
if ($LASTEXITCODE -ne 0) { throw "Kernel component verification failed." }
$kernelSidecar = Join-Path $binaryRoot "nousd-$Target.exe"
$workerSidecar = Join-Path $binaryRoot "nous-provider-worker-$Target.exe"

if (-not $SkipSidecarSmoke) {
    $nativeValidation = & (Join-Path $repo "scripts\ci\verify_windows_native_sidecars.ps1") `
        -SidecarPath $runtimeSidecar `
        -KernelPath $kernelSidecar `
        -ProviderWorkerPath $workerSidecar `
        -ExpectedVersion $ExpectedVersion `
        -Target $Target
} else {
    $nativeValidation = $null
}

. (Join-Path $kernel "scripts\common.ps1")
$manifestPath = Join-Path $tauriRoot "Cargo.toml"
$quotedManifest = '"' + $manifestPath + '"'
Invoke-NousDeveloperCommand "cargo check --locked --target $Target --manifest-path $quotedManifest"
Invoke-NousDeveloperCommand "cargo test --locked --target $Target --manifest-path $quotedManifest"
Invoke-NousDeveloperCommand "cd /d `"$desktop`" && npm run tauri:build:x64"

$releaseRoot = Join-Path $tauriRoot "target\$Target\release"
$launcher = Join-Path $releaseRoot "apeir-control-center.exe"
$bundleRoot = Join-Path $releaseRoot "bundle\nsis"
$installer = Get-ChildItem -LiteralPath $bundleRoot -Filter "*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "APEIR launcher executable was not generated."
}
if (-not $installer) {
    throw "APEIR NSIS installer was not generated."
}

$artifactRoot = if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    Join-Path $repo "artifacts\windows-x64"
} elseif ([System.IO.Path]::IsPathRooted($ArtifactRoot)) {
    [System.IO.Path]::GetFullPath($ArtifactRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repo $ArtifactRoot))
}
$repoPrefix = ([System.IO.Path]::GetFullPath($repo)).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
if (-not $artifactRoot.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "ArtifactRoot must remain inside the Runtime repository: $artifactRoot"
}
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$portableRoot = Join-Path $artifactRoot "APEIR-Portable"
if (Test-Path -LiteralPath $portableRoot) {
    Remove-Item -LiteralPath $portableRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $portableRoot | Out-Null
Copy-Item -LiteralPath $launcher -Destination (Join-Path $portableRoot "APEIR.exe")
Copy-Item -LiteralPath $runtimeSidecar -Destination (Join-Path $portableRoot "nous-runtime.exe")
Copy-Item -LiteralPath $kernelSidecar -Destination (Join-Path $portableRoot "nousd.exe")
Copy-Item -LiteralPath $workerSidecar -Destination (Join-Path $portableRoot "nous-provider-worker.exe")
$publishedInstaller = Join-Path $artifactRoot $installer.Name
Copy-Item -LiteralPath $installer.FullName -Destination $publishedInstaller -Force

$portableZip = Join-Path $artifactRoot "APEIR-Portable-$ExpectedVersion-windows-x64.zip"
if (Test-Path -LiteralPath $portableZip) {
    Remove-Item -LiteralPath $portableZip -Force
}
Compress-Archive -LiteralPath $portableRoot -DestinationPath $portableZip -CompressionLevel Optimal

$artifactFiles = @(
    (Join-Path $portableRoot "APEIR.exe"),
    (Join-Path $portableRoot "nous-runtime.exe"),
    (Join-Path $portableRoot "nousd.exe"),
    (Join-Path $portableRoot "nous-provider-worker.exe"),
    $publishedInstaller,
    $portableZip
)
$artifactRootPrefix = ([System.IO.Path]::GetFullPath($artifactRoot)).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
$hashes = foreach ($path in $artifactFiles) {
    $item = Get-Item -LiteralPath $path
    $fullPath = [System.IO.Path]::GetFullPath($item.FullName)
    if (-not $fullPath.StartsWith($artifactRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Release artifact escaped the artifact root: $fullPath"
    }
    [ordered]@{
        name = ($fullPath.Substring($artifactRootPrefix.Length) -replace "\\", "/")
        size_bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    }
}
$buildTimestamp = [DateTime]::UtcNow.ToString("o")
$runtimeGitDir = Join-Path $repo ".git"
if (Test-Path -LiteralPath $runtimeGitDir) {
    $runtimeRevision = (& git -C $repo rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to read the Distribution Git revision." }
    $runtimeWorktreeDirty = -not [string]::IsNullOrWhiteSpace(
        ((& git -C $repo status --porcelain=v1 --untracked-files=normal) -join "`n")
    )
} else {
    $runtimeRevision = if ([string]::IsNullOrWhiteSpace($env:APEIR_SOURCE_REVISION)) {
        "uncommitted-public-candidate"
    } else {
        $env:APEIR_SOURCE_REVISION.Trim()
    }
    $runtimeWorktreeDirty = $true
}
$kernelWorktreeDirty = -not [string]::IsNullOrWhiteSpace(
    ((& git -C $kernel status --porcelain=v1 --untracked-files=normal) -join "`n")
)
$rustVersion = (& rustc --version).Trim()
$cargoVersion = (& cargo --version).Trim()
$pythonVersion = (& python --version 2>&1).ToString().Trim()
$nodeVersion = (& node --version).Trim()
$npmVersion = (& npm --version).Trim()
$tauriCli = Join-Path $desktop "node_modules\.bin\tauri.cmd"
$tauriVersion = if (Test-Path -LiteralPath $tauriCli) {
    (& $tauriCli --version).Trim()
} else {
    "unavailable"
}
$compilerVersion = (Get-Item -LiteralPath $preflight.cl_path).VersionInfo.ProductVersion
$toolchain = [ordered]@{
    compiler = "MSVC cl.exe $compilerVersion"
    compiler_path = $preflight.cl_path
    linker_path = $preflight.link_path
    windows_sdk_kernel32 = $preflight.kernel32_lib
    rust = $rustVersion
    cargo = $cargoVersion
    python = $pythonVersion
    node = $nodeVersion
    npm = $npmVersion
    tauri = $tauriVersion
}
$nativeReport = [ordered]@{
    schema_version = 1
    status = if ($SkipSidecarSmoke) { "skipped" } else { "passed" }
    validated_at_utc = $buildTimestamp
    target = $Target
    host_os = "Windows 10"
    toolchain = $toolchain
    smoke = $nativeValidation
}
$nativeReportPath = Join-Path $artifactRoot "native-validation-report.json"
$nativeReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $nativeReportPath -Encoding utf8

$manifest = [ordered]@{
    schema_version = 1
    product = "APEIR"
    version = $ExpectedVersion
    target = $Target
    architecture = "x86_64"
    os_baseline = "Windows 10 X64"
    build_timestamp_utc = $buildTimestamp
    runtime_revision = $runtimeRevision
    kernel_revision = $actualRevision
    source_state = [ordered]@{
        runtime_worktree_dirty = $runtimeWorktreeDirty
        kernel_worktree_dirty = $kernelWorktreeDirty
    }
    toolchain = $toolchain
    frontend_embedded = $true
    runtime_sidecar = $true
    kernel_sidecars = @("nousd.exe", "nous-provider-worker.exe")
    sidecar_smoke_passed = -not $SkipSidecarSmoke
    files = @($hashes)
}
$artifactManifest = Join-Path $artifactRoot "APEIR-$ExpectedVersion-windows-x64.manifest.json"
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $artifactManifest -Encoding utf8
$releaseManifest = Join-Path $artifactRoot "release-manifest.json"
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $releaseManifest -Encoding utf8

$evidenceHashes = foreach ($path in @($nativeReportPath, $artifactManifest, $releaseManifest)) {
    $item = Get-Item -LiteralPath $path
    [ordered]@{
        name = $item.Name
        size_bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    }
}
$checksumLines = @(
    @($hashes) + @($evidenceHashes) |
        ForEach-Object { "$($_.sha256)  $($_.name)" }
)
$checksums = Join-Path $artifactRoot "SHA256SUMS-x64.txt"
$portableChecksums = Join-Path $artifactRoot "SHA256SUMS.txt"
$checksumLines | Set-Content -LiteralPath $checksums -Encoding utf8
$checksumLines | Set-Content -LiteralPath $portableChecksums -Encoding utf8

[pscustomobject][ordered]@{
    status = "built"
    target = $Target
    portable_directory = $portableRoot
    portable_zip = $portableZip
    installer = $publishedInstaller
    manifest = $artifactManifest
    release_manifest = $releaseManifest
    native_validation_report = $nativeReportPath
    checksums = $checksums
}

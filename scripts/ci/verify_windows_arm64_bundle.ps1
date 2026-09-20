param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$ExpectedVersion = "0.1.0-rc1",
    [string]$ArtifactName = "windows-arm64-nsis"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$targetRoot = Join-Path $repo "desktop\src-tauri\target\aarch64-pc-windows-msvc\release"
$bundleRoot = Join-Path $targetRoot "bundle\nsis"
$installer = Get-ChildItem -LiteralPath $bundleRoot -Filter "*.exe" |
    Where-Object { $_.Name -like "*$ExpectedVersion*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $installer) {
    $installer = Get-ChildItem -LiteralPath $bundleRoot -Filter "*.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}
if (-not $installer) {
    throw "ARM64 NSIS installer was not generated."
}

$desktopExe = Join-Path $targetRoot "nous-control-center.exe"
if (-not (Test-Path -LiteralPath $desktopExe)) {
    throw "ARM64 desktop executable was not generated."
}
$desktopBytes = [IO.File]::ReadAllBytes($desktopExe)
$desktopPe = [BitConverter]::ToInt32($desktopBytes, 0x3c)
$desktopMachine = [BitConverter]::ToUInt16($desktopBytes, $desktopPe + 4)
if ($desktopMachine -ne 0xAA64) {
    throw "Desktop executable is not ARM64."
}

$frontendIndex = Join-Path $repo "desktop\dist\index.html"
$bundledSidecar = Join-Path $repo "desktop\src-tauri\binaries\nous-runtime-aarch64-pc-windows-msvc.exe"
$bundledKernel = Join-Path $repo "desktop\src-tauri\binaries\nousd-aarch64-pc-windows-msvc.exe"
$bundledWorker = Join-Path $repo "desktop\src-tauri\binaries\nous-provider-worker-aarch64-pc-windows-msvc.exe"
if (-not (Test-Path -LiteralPath $frontendIndex)) {
    throw "Frontend production resources are missing."
}
if (-not (Test-Path -LiteralPath $bundledSidecar)) {
    throw "ARM64 Runtime sidecar is missing from the Tauri bundle input."
}
if (-not (Test-Path -LiteralPath $bundledKernel) -or -not (Test-Path -LiteralPath $bundledWorker)) {
    throw "ARM64 kernel sidecars are missing from the Tauri bundle input."
}

$installRoot = Join-Path ([IO.Path]::GetTempPath()) ("nous-rc3-install-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $installRoot | Out-Null
try {
    $install = Start-Process -FilePath $installer.FullName -ArgumentList @("/S", "/D=$installRoot") -Wait -PassThru
    if ($install.ExitCode -ne 0) {
        throw "NSIS silent installation failed with exit code $($install.ExitCode)."
    }

    $probeRoot = $installRoot
    $installedDesktop = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "*.exe" |
        Where-Object { $_.Name -notmatch "nous-runtime" } |
        Sort-Object Length -Descending |
        Select-Object -First 1
    $installedSidecar = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "*nous-runtime*.exe" |
        Select-Object -First 1
    $installedKernel = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "nousd*.exe" |
        Select-Object -First 1
    $installedWorker = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "nous-provider-worker*.exe" |
        Select-Object -First 1
    if (-not $installedDesktop -or -not $installedSidecar) {
        $currentUserRoot = Join-Path $env:LOCALAPPDATA "Nous"
        if (Test-Path -LiteralPath $currentUserRoot) {
            $probeRoot = $currentUserRoot
            $installedDesktop = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "*.exe" |
                Where-Object { $_.Name -notmatch "nous-runtime" } |
                Sort-Object Length -Descending |
                Select-Object -First 1
            $installedSidecar = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "*nous-runtime*.exe" |
                Select-Object -First 1
            $installedKernel = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "nousd*.exe" |
                Select-Object -First 1
            $installedWorker = Get-ChildItem -LiteralPath $probeRoot -Recurse -Filter "nous-provider-worker*.exe" |
                Select-Object -First 1
        }
    }
    if (-not $installedDesktop) {
        throw "Installed Desktop executable was not found."
    }
    if (-not $installedSidecar) {
        throw "Installed Runtime sidecar was not found."
    }
    if (-not $installedKernel -or -not $installedWorker) {
        throw "Installed kernel sidecars were not found."
    }

    foreach ($nativeSidecar in @($installedKernel, $installedWorker)) {
        $bytes = [IO.File]::ReadAllBytes($nativeSidecar.FullName)
        $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
        $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
        if ($machine -ne 0xAA64) {
            throw "$($nativeSidecar.Name) is not ARM64."
        }
    }

    & (Join-Path $repo "scripts\ci\verify_windows_arm64_sidecar.ps1") `
        -SidecarPath $installedSidecar.FullName `
        -KernelPath $installedKernel.FullName `
        -ProviderWorkerPath $installedWorker.FullName `
        -ExpectedVersion $ExpectedVersion

    $hash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
    $checksumPath = Join-Path $repo "SHA256SUMS-arm64.txt"
    "$hash  $($installer.Name)" | Set-Content -LiteralPath $checksumPath -Encoding utf8

    $manifest = [ordered]@{
        target = "aarch64-pc-windows-msvc"
        version = $ExpectedVersion
        artifact_name = $ArtifactName
        installer_name = $installer.Name
        installer_size_bytes = $installer.Length
        installer_sha256 = $hash
        desktop_executable = $installedDesktop.Name
        desktop_pe_machine = "0xAA64"
        runtime_sidecar = $installedSidecar.Name
        kernel_sidecar = $installedKernel.Name
        provider_worker_sidecar = $installedWorker.Name
        kernel_sidecars_arm64 = $true
        frontend_resources_built = $true
        installed_without_repo_runtime = ($probeRoot -notlike "$repo*")
        installed_sidecar_smoke = $true
    }
    $manifestPath = Join-Path $repo "RC3-ARM64-ARTIFACT.json"
    $manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8
    [pscustomobject]$manifest
} finally {
    if (Test-Path -LiteralPath $installRoot) {
        $uninstaller = Get-ChildItem -LiteralPath $installRoot -Recurse -Filter "uninstall.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($uninstaller) {
            Start-Process -FilePath $uninstaller.FullName -ArgumentList "/S" -Wait | Out-Null
        }
        if (Test-Path -LiteralPath $installRoot) {
            Remove-Item -LiteralPath $installRoot -Recurse -Force
        }
    }
}

param(
    [Parameter(Mandatory = $true)][string]$ToolsRoot,
    [Parameter(Mandatory = $true)][string]$KernelRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne 'Arm64') {
    throw 'ARM64 dependency preparation requires an ARM64 Windows host.'
}
$tools = (Resolve-Path -LiteralPath $ToolsRoot).Path
$kernel = (Resolve-Path -LiteralPath $KernelRoot).Path
$expectedToolsRevision = '2ec0f1747d8186a5c9babe276e2ad57cd2b12d2a'
$actualToolsRevision = (& git -C $tools rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualToolsRevision -ne $expectedToolsRevision) {
    throw 'Dependency tools must match the reviewed Microsoft vcpkg source.'
}
$changes = (& git -C $tools status --porcelain --untracked-files=no) -join "`n"
if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace($changes)) {
    throw 'Dependency tool tracked source must be clean.'
}
$preflight = & (Join-Path $PSScriptRoot 'windows_native_preflight.ps1') -Target aarch64-pc-windows-msvc
if (-not $preflight.ready) { throw 'ARM64 native dependency build prerequisites are missing.' }
New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
$env:VCPKG_DISABLE_METRICS = '1'
& (Join-Path $tools 'bootstrap-vcpkg.bat') -disableMetrics
if ($LASTEXITCODE -ne 0) { throw 'Pinned vcpkg bootstrap failed.' }
. (Join-Path $kernel 'scripts\common.ps1')
$triplet = 'arm64-windows-static-md'
$vcpkg = Join-Path $tools 'vcpkg.exe'
Invoke-NousDeveloperCommand "`"$vcpkg`" install openssl:$triplet --classic --disable-metrics"
$installed = Join-Path $tools "installed\$triplet"
$files = foreach ($name in @('libssl.lib', 'libcrypto.lib')) {
    $path = Join-Path $installed "lib\$name"
    if (-not (Test-Path -LiteralPath $path)) { throw "ARM64 static OpenSSL input is missing: $name" }
    [ordered]@{ name = $name; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash; size_bytes = (Get-Item -LiteralPath $path).Length }
}
$port = Get-Content -LiteralPath (Join-Path $tools 'ports\openssl\vcpkg.json') -Raw | ConvertFrom-Json
[ordered]@{
    purpose = 'Build dependency provenance; not Kernel or release approval'
    repository = 'https://github.com/microsoft/vcpkg'
    tools_revision = $actualToolsRevision
    triplet = $triplet
    openssl_version = $port.version
    openssl_port_version = $port.'port-version'
    linkage = 'static OpenSSL; native ARM64; no vcpkg runtime required by users'
    licensing = $port.license
    libraries = @($files)
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'arm64-dependency-build.json') -Encoding utf8
$env:OPENSSL_DIR = $installed
$env:OPENSSL_STATIC = '1'
$env:VCPKG_ROOT = $tools
if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_ENV)) {
    "OPENSSL_DIR=$installed`nOPENSSL_STATIC=1`nVCPKG_ROOT=$tools`nVCPKG_DISABLE_METRICS=1" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    "ARM64_DEPENDENCY_BUILD_REPORT=$(Join-Path $EvidenceDirectory 'arm64-dependency-build.json')" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}

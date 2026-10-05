param(
    [Parameter(Mandatory = $true)]
    [string]$RelayUrl,
    [Parameter(Mandatory = $true)]
    [string]$ServerPublicKey,
    [ValidateSet("X64", "ARM64")]
    [string]$Architecture = "X64",
    [string]$Name = "",
    [string]$CaFile = "",
    [string]$StateDirectory = "",
    [double]$HeartbeatSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "APEIR Python environment is missing: $python"
}
if ($RelayUrl -notmatch '^wss://') {
    throw "A remote Compute Mesh Node requires a wss:// RelayUrl"
}
if ($ServerPublicKey -notmatch '^[0-9a-fA-F]{64}$') {
    throw "ServerPublicKey must be a 32-byte Ed25519 public key in hex"
}
if ($CaFile -and -not (Test-Path -LiteralPath $CaFile -PathType Leaf)) {
    throw "CA file does not exist: $CaFile"
}

$nativeArchitecture = (& $python -c "import platform,struct; print(platform.machine()); print(struct.calcsize('P')*8)")
if ($LASTEXITCODE -ne 0 -or $nativeArchitecture.Count -lt 2) {
    throw "Unable to determine the native Python architecture"
}
$actualArchitecture = $nativeArchitecture[0].ToUpperInvariant()
$expectedNames = if ($Architecture -eq "X64") { @("AMD64", "X86_64") } else { @("ARM64", "AARCH64") }
if ($actualArchitecture -notin $expectedNames -or $nativeArchitecture[1] -ne "64") {
    throw "Expected native $Architecture, found $($nativeArchitecture -join ' ')"
}

if (-not $Name) {
    $Name = "apeir-windows-$($Architecture.ToLowerInvariant())-$env:COMPUTERNAME"
}
if (-not $StateDirectory) {
    $StateDirectory = Join-Path $repositoryRoot ".local\compute-mesh-node-$($Architecture.ToLowerInvariant())"
}

$arguments = @(
    "-m", "nous_runtime.node_runtime.cli",
    "--state-dir", $StateDirectory,
    "--name", $Name,
    "--heartbeat-seconds", $HeartbeatSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--relay-url", $RelayUrl,
    "--server-public-key", $ServerPublicKey
)
if ($CaFile) {
    $arguments += @("--ca-file", $CaFile)
}

Write-Output "Starting APEIR Compute Mesh Node"
Write-Output "Architecture: $Architecture"
Write-Output "State: $StateDirectory"
& $python @arguments
exit $LASTEXITCODE

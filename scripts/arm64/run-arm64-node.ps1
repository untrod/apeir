param(
    [string]$Name = "apeir-arm64-lab-node-v1",
    [double]$HeartbeatSeconds = 30,
    [string]$RelayUrl = "",
    [string]$ServerPublicKey = "",
    [string]$CaFile = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$stateDirectory = Join-Path $repositoryRoot ".local\arm64-node"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Repository virtual environment is missing: $python"
}

$architecture = & $python -c "import platform,struct; print(platform.machine()); print(struct.calcsize('P')*8)"
if ($LASTEXITCODE -ne 0 -or $architecture[0].ToUpperInvariant() -notin @("ARM64", "AARCH64") -or $architecture[1] -ne "64") {
    throw "Refusing to label a non-native process as an ARM64 Lab Node: $($architecture -join ' ')"
}

$arguments = @(
    "-m", "nous_runtime.node_runtime.cli",
    "--state-dir", $stateDirectory,
    "--name", $Name,
    "--heartbeat-seconds", $HeartbeatSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($RelayUrl) {
    if (-not $ServerPublicKey) {
        throw "ServerPublicKey is required when RelayUrl is set"
    }
    $arguments += @("--relay-url", $RelayUrl, "--server-public-key", $ServerPublicKey)
    if ($CaFile) {
        $arguments += @("--ca-file", $CaFile)
    }
}

Write-Output "Starting APEIR ARM64 Lab Node v1"
Write-Output "State: $stateDirectory"
Write-Output "Heartbeat: $HeartbeatSeconds seconds"
& $python @arguments
exit $LASTEXITCODE

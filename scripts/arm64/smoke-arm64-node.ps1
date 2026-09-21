param(
    [string]$KernelRoot = "",
    [string]$EvidenceDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $KernelRoot) {
    $KernelRoot = Join-Path (Split-Path -Parent $repositoryRoot) "apeir-kernel"
}
if (-not $EvidenceDirectory) {
    $EvidenceDirectory = Join-Path $repositoryRoot ".local\evidence"
}
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$evidencePath = Join-Path $EvidenceDirectory "arm64-smoke-$timestamp.json"
$stateRoot = Join-Path $EvidenceDirectory "arm64-smoke-$timestamp-state"
New-Item -ItemType Directory -Force -Path $EvidenceDirectory, $stateRoot | Out-Null

$results = [ordered]@{
    schema = "apeir.arm64-node-smoke/v1"
    measured_at = [DateTime]::UtcNow.ToString("o")
    repository = $repositoryRoot
    kernel_repository = $KernelRoot
    architecture = "NOT_TESTED"
    runtime_import = "NOT_TESTED"
    node_identity = "NOT_TESTED"
    resource_discovery = "NOT_TESTED"
    tool_inventory = "NOT_TESTED"
    execution_preflight = "NOT_TESTED"
    kernel_pe_architecture = "NOT_TESTED"
    kernel_startup = "NOT_TESTED"
    kernel_doctor = "NOT_TESTED"
    reference_execution = "NOT_TESTED"
    kernel_inspect = "NOT_TESTED"
    restart_recovery = "NOT_TESTED"
    clean_shutdown = "NOT_TESTED"
    errors = [System.Collections.Generic.List[string]]::new()
}

function Save-Evidence {
    $results | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
}

function Get-PeMachine([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $reader = [System.IO.BinaryReader]::new($stream)
        $stream.Position = 0x3c
        $offset = $reader.ReadInt32()
        $stream.Position = $offset + 4
        return $reader.ReadUInt16()
    } finally {
        $stream.Dispose()
    }
}

function Wait-Kernel([int]$ProcessId, [int]$Seconds = 15) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return $false
        }
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $connection = $client.ConnectAsync("127.0.0.1", 8771)
            if ($connection.Wait(200) -and $client.Connected) {
                return $true
            }
        } catch {
            # Readiness is retried until the bounded deadline.
        } finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Start-Kernel(
    [string]$Daemon,
    [string]$Journal,
    [string]$Worker,
    [string]$Stdout,
    [string]$Stderr
) {
    $process = Start-Process -FilePath $Daemon `
        -ArgumentList @("serve", $Journal, $Worker, "127.0.0.1:8771") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -PassThru
    if (-not (Wait-Kernel -ProcessId $process.Id)) {
        $detail = if (Test-Path -LiteralPath $Stderr) {
            Get-Content -Raw -LiteralPath $Stderr
        } else {
            "no daemon error log"
        }
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
        throw "Kernel did not become ready: $detail"
    }
    return $process
}

$firstKernel = $null
$secondKernel = $null
try {
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Native repository virtual environment is missing: $python"
    }

    $architecture = & $python -c "import platform,struct; print(platform.machine()); print(struct.calcsize('P')*8)"
    if ($LASTEXITCODE -ne 0 -or $architecture[0].ToUpperInvariant() -notin @("ARM64", "AARCH64") -or $architecture[1] -ne "64") {
        throw "Python is not a native 64-bit ARM process: $($architecture -join ' ')"
    }
    $results.architecture = "PASS"

    & $python -c "import nous_runtime; print('runtime import PASS')"
    if ($LASTEXITCODE -ne 0) { throw "APEIR Runtime import failed" }
    $results.runtime_import = "PASS"

    $nodeState = Join-Path $stateRoot "node"
    $nodeCheck = @'
import json
import sys
from pathlib import Path
from nous_runtime.node_runtime import NodeRuntimeConfig, NodeRuntimeService

state = Path(sys.argv[1])
first = NodeRuntimeService(NodeRuntimeConfig(state_dir=state, node_name='arm64-smoke'))
first_status = first.run_once()
preflight = first.preflight_execution({'architecture': 'arm64', 'tools': ['python >= 3.12', 'cargo']})
second = NodeRuntimeService(NodeRuntimeConfig(state_dir=state))
second_status = second.run_once()
result = {
    'identity_stable': first.identity.node_id == second.identity.node_id,
    'heartbeat_recovered': second_status['heartbeat_sequence'] > first_status['heartbeat_sequence'],
    'resources_real': first_status['resources']['measurement_source'] == 'host-os',
    'inventory_schema': first_status['execution_host']['schema'],
    'preflight': preflight['status'],
}
print(json.dumps(result, sort_keys=True))
if not all((result['identity_stable'], result['heartbeat_recovered'], result['resources_real'])):
    raise SystemExit(1)
if result['preflight'] != 'ELIGIBLE':
    raise SystemExit(2)
'@
    $nodeOutput = & $python -c $nodeCheck $nodeState
    if ($LASTEXITCODE -ne 0) { throw "Node inventory/preflight/restart smoke failed: $nodeOutput" }
    $results.node_identity = "PASS"
    $results.resource_discovery = "PASS"
    $results.tool_inventory = "PASS"
    $results.execution_preflight = "PASS"

    $daemon = Join-Path $KernelRoot "target\debug\apeird.exe"
    $worker = Join-Path $KernelRoot "target\debug\nous-provider-worker.exe"
    $controller = Join-Path $KernelRoot "target\debug\apeir-kernelctl.exe"
    foreach ($binary in @($daemon, $worker, $controller)) {
        if (-not (Test-Path -LiteralPath $binary)) {
            throw "Kernel binary is missing: $binary"
        }
        if ((Get-PeMachine $binary) -ne 0xAA64) {
            throw "Kernel binary is not ARM64 PE: $binary"
        }
    }
    $results.kernel_pe_architecture = "PASS"

    $sessionToken = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:NOUS_NKI_TOKEN = $sessionToken
    $journal = Join-Path $stateRoot "kernel.db"
    $firstKernel = Start-Kernel $daemon $journal $worker `
        (Join-Path $stateRoot "kernel-first.stdout.log") `
        (Join-Path $stateRoot "kernel-first.stderr.log")
    $results.kernel_startup = "PASS"

    & $controller doctor
    if ($LASTEXITCODE -ne 0) { throw "Kernel doctor failed" }
    $results.kernel_doctor = "PASS"
    & $controller run "arm64-reference-smoke" --backend reference
    if ($LASTEXITCODE -ne 0) { throw "Kernel reference execution failed" }
    $results.reference_execution = "PASS"
    & $controller inspect
    if ($LASTEXITCODE -ne 0) { throw "Kernel inspect failed" }
    $results.kernel_inspect = "PASS"

    Stop-Process -Id $firstKernel.Id -Force
    $firstKernel.WaitForExit()
    $firstKernel = $null
    Start-Sleep -Milliseconds 500

    $secondKernel = Start-Kernel $daemon $journal $worker `
        (Join-Path $stateRoot "kernel-second.stdout.log") `
        (Join-Path $stateRoot "kernel-second.stderr.log")
    & $controller doctor
    if ($LASTEXITCODE -ne 0) { throw "Kernel doctor failed after restart" }
    & $controller inspect
    if ($LASTEXITCODE -ne 0) { throw "Kernel inspect failed after restart" }
    $results.restart_recovery = "PASS"
} catch {
    $results.errors.Add($_.Exception.Message)
} finally {
    if ($firstKernel -and -not $firstKernel.HasExited) {
        Stop-Process -Id $firstKernel.Id -Force
    }
    if ($secondKernel -and -not $secondKernel.HasExited) {
        Stop-Process -Id $secondKernel.Id -Force
    }
    Remove-Item Env:NOUS_NKI_TOKEN -ErrorAction SilentlyContinue
    Save-Evidence
}

Write-Output "ARM64 smoke evidence: $evidencePath"
if ($results.errors.Count -gt 0) {
    $results.errors | ForEach-Object { Write-Error $_ }
    exit 1
}
Write-Output "ARM64 Lab Node smoke PASS"
exit 0

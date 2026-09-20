param(
    [Parameter(Mandatory = $true)]
    [string]$SidecarPath,
    [Parameter(Mandatory = $true)]
    [string]$KernelPath,
    [Parameter(Mandatory = $true)]
    [string]$ProviderWorkerPath,
    [string]$ExpectedVersion = "0.1.0-rc1",
    [string]$Target = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"

function Get-NativePeMachine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$ExpectedMachine,
        [Parameter(Mandatory = $true)][string]$Architecture
    )
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4D -or $bytes[1] -ne 0x5A) {
        throw "$Name is not a PE executable."
    }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ($peOffset -lt 0 -or ($peOffset + 6) -gt $bytes.Length) {
        throw "$Name has an invalid PE header."
    }
    $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
    if ($machine -ne $ExpectedMachine) {
        throw "$Name is not $Architecture (PE machine 0x$('{0:X4}' -f $machine))."
    }
}
function Get-FreeTcpPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

function Test-TcpPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync("127.0.0.1", $Port)
        return $connect.Wait(500) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Stop-ProcessTree {
    param([Diagnostics.Process]$Process)
    if ($Process -and -not $Process.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $Process.Id /T /F *> $null
        Start-Sleep -Milliseconds 750
    }
}

$sidecar = (Resolve-Path -LiteralPath $SidecarPath).Path
$kernel = (Resolve-Path -LiteralPath $KernelPath).Path
$worker = (Resolve-Path -LiteralPath $ProviderWorkerPath).Path
$osArchitecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
$targetArchitecture = if ($Target -match '^aarch64-') { 'Arm64' } elseif ($Target -match '^x86_64-') { 'X64' } else { '' }
$expectedMachine = if ($targetArchitecture -eq 'Arm64') { 0xAA64 } elseif ($targetArchitecture -eq 'X64') { 0x8664 } else { 0 }
if (-not $targetArchitecture) {
    throw "Unsupported Windows target: $Target"
}
$canExecuteTarget = if ($targetArchitecture -eq 'Arm64') {
    $osArchitecture -eq 'Arm64'
} else {
    $osArchitecture -in @('X64', 'Arm64')
}
if (-not $canExecuteTarget) {
    throw "$targetArchitecture sidecar certification cannot run on $osArchitecture Windows."
}
Get-NativePeMachine -Path $sidecar -Name 'Runtime sidecar' -ExpectedMachine $expectedMachine -Architecture $targetArchitecture
Get-NativePeMachine -Path $kernel -Name 'Kernel daemon' -ExpectedMachine $expectedMachine -Architecture $targetArchitecture
Get-NativePeMachine -Path $worker -Name 'Provider worker' -ExpectedMachine $expectedMachine -Architecture $targetArchitecture
$version = (& $sidecar --version 2>&1 | Out-String).Trim()
if ($version -notmatch [regex]::Escape($ExpectedVersion)) {
    throw "Runtime sidecar version does not match $ExpectedVersion."
}
$workerResponseJson = ('{"type":"health"}' | & $worker --stdio-once 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Provider Worker health process failed with exit code $LASTEXITCODE."
}
$workerResponse = $workerResponseJson | ConvertFrom-Json
if (-not $workerResponse.ok) {
    throw "Provider Worker health response was not successful."
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("nous-native-sidecar-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$tokenFile = Join-Path $tempRoot "runtime-session.token"
$journalFile = Join-Path $tempRoot "kernel-journal.db"
$kernelStdoutFile = Join-Path $tempRoot "kernel.stdout.log"
$kernelStderrFile = Join-Path $tempRoot "kernel.stderr.log"
$stdoutFile = Join-Path $tempRoot "runtime.stdout.log"
$stderrFile = Join-Path $tempRoot "runtime.stderr.log"

$port = Get-FreeTcpPort
$kernelPort = Get-FreeTcpPort
while ($kernelPort -eq $port) {
    $kernelPort = Get-FreeTcpPort
}
$kernelToken = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")

$environmentNames = @(
    "NOUS_WORKSPACE_ROOT",
    "NOUS_SESSION_TOKEN_FILE",
    "NOUS_CLI_PATH",
    "NOUS_KERNEL_ENDPOINT",
    "NOUS_NKI_TOKEN",
    "NOUS_ALLOWED_CREDENTIALS",
    "PYTHONHOME",
    "PYTHONPATH",
    "RUST_LOG"
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$previousPath = $env:PATH
$env:NOUS_WORKSPACE_ROOT = $tempRoot
$env:NOUS_SESSION_TOKEN_FILE = $tokenFile
$env:NOUS_CLI_PATH = $null
$env:NOUS_KERNEL_ENDPOINT = "tcp://127.0.0.1:$kernelPort"
$env:NOUS_NKI_TOKEN = $kernelToken
$env:NOUS_ALLOWED_CREDENTIALS = ""
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:RUST_LOG = "nousd=info"
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"

$parent = $null
$kernelParent = $null
$summary = $null
try {
    $kernelStart = @{
        FilePath = $kernel
        ArgumentList = @("serve", $journalFile, $worker, "127.0.0.1:$kernelPort")
        WorkingDirectory = $tempRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = $kernelStdoutFile
        RedirectStandardError = $kernelStderrFile
        PassThru = $true
    }
    $kernelParent = Start-Process @kernelStart

    $kernelReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($kernelParent.HasExited) {
            throw "Packaged Kernel exited during startup with code $($kernelParent.ExitCode)."
        }
        if (Test-TcpPort -Port $kernelPort) {
            $kernelReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $kernelReady) {
        throw "Packaged Kernel did not accept NKI connections within 10 seconds."
    }

    $runtimeStart = @{
        FilePath = $sidecar
        ArgumentList = @("runtime-api", "start", "--host", "127.0.0.1", "--port", [string]$port)
        WorkingDirectory = $tempRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = $stdoutFile
        RedirectStandardError = $stderrFile
        PassThru = $true
    }
    $parent = Start-Process @runtimeStart

    $live = $null
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if ($parent.HasExited) {
            throw "Packaged Runtime exited during startup with code $($parent.ExitCode)."
        }
        try {
            $live = Invoke-RestMethod -Uri "http://127.0.0.1:$port/live" -TimeoutSec 1
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $live -or -not $live.ok) {
        throw "Packaged Runtime did not become live within 60 seconds."
    }
    if (-not (Test-Path -LiteralPath $tokenFile)) {
        throw "Packaged Runtime did not create a session token."
    }

    $token = [IO.File]::ReadAllText($tokenFile).Trim()
    if ($token.Length -ne 64) {
        throw "Packaged Runtime created an invalid session token."
    }
    $headers = @{
        Authorization = "Bearer $token"
        Origin = "tauri://localhost"
    }
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/status" -Headers $headers -TimeoutSec 5
    if (-not $status.ok -or $status.data.version -ne $ExpectedVersion) {
        throw "Authenticated Runtime status verification failed."
    }

    $summary = [ordered]@{
        sidecar = (Split-Path -Leaf $sidecar)
        kernel = (Split-Path -Leaf $kernel)
        provider_worker = (Split-Path -Leaf $worker)
        target = $Target
        pe_machine = "0x$('{0:X4}' -f $expectedMachine)"
        version = $ExpectedVersion
        kernel_ready = $true
        live = $true
        authenticated_status = $true
        provider_worker_health = $true
        token_length = $token.Length
        token_disclosed = $false
        kernel_pid = $kernelParent.Id
        parent_pid = $parent.Id
        runtime_pid = [int]$live.data.pid
    }
} finally {
    Stop-ProcessTree -Process $parent
    Stop-ProcessTree -Process $kernelParent
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    $env:PATH = $previousPath
}

$runtimeClosed = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:$port/live" -TimeoutSec 1 | Out-Null
} catch {
    $runtimeClosed = $true
}
if (-not $runtimeClosed) {
    throw "Runtime process tree remained reachable after shutdown."
}

$kernelClosed = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if (-not (Test-TcpPort -Port $kernelPort)) {
        $kernelClosed = $true
        break
    }
    Start-Sleep -Milliseconds 250
}
if (-not $kernelClosed) {
    throw "Kernel process tree remained reachable after shutdown."
}

$summary.process_tree_closed = $true
$summary.kernel_process_tree_closed = $true
$summary.stdout_captured = (Test-Path $stdoutFile) -and ([IO.File]::ReadAllText($stdoutFile).Contains("Nous Runtime API listening"))
$summary.kernel_stdout_captured = (Test-Path $kernelStdoutFile) -and ([IO.File]::ReadAllText($kernelStdoutFile).Contains("READY"))

if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}

[pscustomobject]$summary

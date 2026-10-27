param(
    [Parameter(Mandatory = $true)]
    [string]$SidecarPath,
    [Parameter(Mandatory = $true)]
    [string]$KernelPath,
    [Parameter(Mandatory = $true)]
    [string]$ProviderWorkerPath,
    [string]$ExpectedVersion = "0.1.0-rc1",
    [string]$Target = "x86_64-pc-windows-msvc",
    [string]$EvidenceDirectory = ""
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
    if ([BitConverter]::ToUInt32($bytes, $peOffset) -ne 0x00004550) {
        throw "$Name has an invalid PE signature."
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
        if ($LASTEXITCODE -ne 0) { throw "Native smoke process-tree cleanup failed." }
        if (-not $Process.WaitForExit(5000)) { throw "Native smoke process did not exit." }
    }
}

function Wait-KernelReady {
    param([Diagnostics.Process]$Process, [int]$Port)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt 10) {
        if ($Process.HasExited) { throw "Kernel exited before accepting connections." }
        if (Test-TcpPort -Port $Port) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Kernel did not accept connections within 10 seconds."
}

function Wait-RuntimeLive {
    param([Diagnostics.Process]$Process, [int]$Port)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt 60) {
        if ($Process.HasExited) { throw "Runtime exited before becoming live." }
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/live" -TimeoutSec 1
            if ($response.ok -eq $true) { return $response }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "Runtime did not become live within 60 seconds."
}

function Assert-HttpAuthenticationRejected {
    param([int]$Port, [hashtable]$Headers)
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/status" -Headers $Headers -TimeoutSec 5 | Out-Null
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) { return }
        throw "Runtime authentication probe failed at an unexpected boundary."
    }
    throw "Runtime accepted an unauthenticated request."
}

$sidecar = (Resolve-Path -LiteralPath $SidecarPath).Path
$kernel = (Resolve-Path -LiteralPath $KernelPath).Path
$worker = (Resolve-Path -LiteralPath $ProviderWorkerPath).Path
# Python is only the build host's NKI test driver. Native child PATH and Python
# environment are scrubbed below; the packaged Runtime must start independently.
$probePython = (Get-Command python -ErrorAction Stop).Source
$nkiProbe = Join-Path $PSScriptRoot "probe_native_nki.py"
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
if ($LASTEXITCODE -ne 0 -or $version -notmatch [regex]::Escape($ExpectedVersion)) {
    throw "Runtime sidecar version does not match $ExpectedVersion."
}
$workerResponseJson = ('{"type":"health"}' | & $worker --stdio-once 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Provider Worker health process failed with exit code $LASTEXITCODE."
}
$workerResponse = $workerResponseJson | ConvertFrom-Json
if ($workerResponse.ok -isnot [bool] -or -not $workerResponse.ok) {
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
$nkiReport = Join-Path $tempRoot "nki-initial.json"
$recoveryReport = Join-Path $tempRoot "nki-recovery.json"

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
    "NOUS_RUNTIME_MODE",
    "NOUS_NO_INTELLIGENCE",
    "NOUS_API_TOKEN",
    "NOUS_AUTH_TOKEN",
    "NOUS_DATA_DIR",
    "APEIR_STATE_DIR",
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
$env:NOUS_RUNTIME_MODE = "production"
$env:NOUS_NO_INTELLIGENCE = $null
$env:NOUS_API_TOKEN = $null
$env:NOUS_AUTH_TOKEN = $null
$env:NOUS_DATA_DIR = Join-Path $tempRoot "capabilities"
$env:APEIR_STATE_DIR = Join-Path $tempRoot "state"
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:RUST_LOG = "nousd=info"
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"

$parent = $null
$kernelParent = $null
$badParent = $null
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
    Wait-KernelReady -Process $kernelParent -Port $kernelPort
    $appLocalCrt = Join-Path (Split-Path $kernel) 'vcruntime140.dll'
    $appLocalCrtChecked = $false
    if (Test-Path -LiteralPath $appLocalCrt) {
        Get-NativePeMachine -Path $appLocalCrt -Name 'Visual C++ runtime' -ExpectedMachine $expectedMachine -Architecture $targetArchitecture
        $loadedCrt = @($kernelParent.Modules | Where-Object { $_.ModuleName -ieq 'vcruntime140.dll' })
        if ($loadedCrt.Count -ne 1 -or $loadedCrt[0].FileName -ine $appLocalCrt) {
            throw 'Kernel did not load the supplied app-local Visual C++ runtime.'
        }
        $appLocalCrtChecked = $true
    }
    & $probePython -I $nkiProbe --endpoint $env:NOUS_KERNEL_ENDPOINT --report $nkiReport | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Actual Kernel NKI qualification failed." }

    $workflowReport = Join-Path $tempRoot "workflow-cli-qualification.json"
    & $probePython -I (Join-Path $PSScriptRoot "probe_native_workflow.py") `
        --sidecar $sidecar --workspace $tempRoot --report $workflowReport
    if ($LASTEXITCODE -ne 0) { throw "Actual packaged Workflow qualification failed." }

    $runtimeStart = @{
        FilePath = $sidecar
        ArgumentList = @("runtime-api", "start", "--host", "127.0.0.1", "--port", [string]$port)
        WorkingDirectory = $tempRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = $stdoutFile
        RedirectStandardError = $stderrFile
        PassThru = $true
    }
    # Exercise the frozen Runtime itself, not a mocked transport, with a bad NKI
    # credential before creating its good HTTP session. No model may fall back.
    $env:NOUS_NKI_TOKEN = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    try {
        $badParent = Start-Process @runtimeStart
        if (-not $badParent.WaitForExit(60000)) { throw "Invalid NKI credential did not fail closed." }
        if ($badParent.ExitCode -ne 1 -or (Test-Path -LiteralPath $tokenFile) -or (Test-TcpPort -Port $port)) {
            throw "Invalid NKI credential unexpectedly created a Runtime session."
        }
        $refusal = [IO.File]::ReadAllText($stderrFile)
        if (-not $refusal.Contains("UNAUTHENTICATED")) { throw "Runtime failed before proving NKI credential rejection." }
    } finally {
        $env:NOUS_NKI_TOKEN = $kernelToken
        Stop-ProcessTree -Process $badParent
    }
    $runtimeStart.RedirectStandardOutput = Join-Path $tempRoot "runtime-good.stdout.log"
    $runtimeStart.RedirectStandardError = Join-Path $tempRoot "runtime-good.stderr.log"
    $stdoutFile = $runtimeStart.RedirectStandardOutput
    $parent = Start-Process @runtimeStart
    $live = Wait-RuntimeLive -Process $parent -Port $port
    if (-not (Test-Path -LiteralPath $tokenFile)) {
        throw "Packaged Runtime did not create a session token."
    }

    $token = [IO.File]::ReadAllText($tokenFile).Trim()
    if ($token.Length -ne 64) {
        throw "Packaged Runtime created an invalid session token."
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $tokenAcl = Get-Acl -LiteralPath $tokenFile
    $rules = @($tokenAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $tokenAcl.AreAccessRulesProtected -or $tokenAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $identity.Value -or $rules.Count -ne 1 -or $rules[0].IdentityReference.Value -ne $identity.Value -or $rules[0].AccessControlType -ne 'Allow') {
        throw "Runtime session token is not protected by a current-user-only DACL."
    }
    $headers = @{
        Authorization = "Bearer $token"
        Origin = "tauri://localhost"
    }
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/status" -Headers $headers -TimeoutSec 5
    if (-not $status.ok -or $status.data.version -ne $ExpectedVersion) {
        throw "Authenticated Runtime status verification failed."
    }
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health/detailed" -Headers $headers -TimeoutSec 5
    if (-not $health.data.kernel.ready -or $health.data.kernel.state -ne "READY") {
        throw "Runtime did not report an authenticated, ready Kernel."
    }
    Assert-HttpAuthenticationRejected -Port $port -Headers @{}
    $invalidToken = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    Assert-HttpAuthenticationRejected -Port $port -Headers @{ Authorization = "Bearer $invalidToken" }

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
        token_owner_only_dacl = $true
        app_local_crt_loaded = $appLocalCrtChecked
        kernel_pid = $kernelParent.Id
        parent_pid = $parent.Id
        runtime_pid = [int]$live.data.pid
        nki = (Get-Content -LiteralPath $nkiReport -Raw | ConvertFrom-Json)
        workflow_cli = (Get-Content -LiteralPath $workflowReport -Raw | ConvertFrom-Json)
        invalid_nki_runtime_start_rejected = $true
        invalid_http_sessions_rejected = $true
        shutdown_mode = "forced owned-process fault/restart test; not graceful Desktop exit"
    }
    $initialRuntimePid = [int]$live.data.pid
    Stop-ProcessTree -Process $parent
    Stop-ProcessTree -Process $kernelParent
    if ((Test-TcpPort -Port $port) -or (Test-TcpPort -Port $kernelPort) -or (Get-Process -Id $initialRuntimePid -ErrorAction SilentlyContinue)) {
        throw "Original native processes survived fault cleanup."
    }
    # Restart the same binaries and original journal. The probe only queries the
    # original denied workload; it cannot replay or submit a replacement.
    $kernelStart.RedirectStandardOutput = Join-Path $tempRoot "kernel-restart.stdout.log"
    $kernelStart.RedirectStandardError = Join-Path $tempRoot "kernel-restart.stderr.log"
    $kernelParent = Start-Process @kernelStart
    Wait-KernelReady -Process $kernelParent -Port $kernelPort
    & $probePython -I $nkiProbe --endpoint $env:NOUS_KERNEL_ENDPOINT --resume-from $nkiReport --report $recoveryReport | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Original Kernel workload recovery qualification failed." }
    $runtimeStart.RedirectStandardOutput = Join-Path $tempRoot "runtime-restart.stdout.log"
    $runtimeStart.RedirectStandardError = Join-Path $tempRoot "runtime-restart.stderr.log"
    $parent = Start-Process @runtimeStart
    $live = Wait-RuntimeLive -Process $parent -Port $port
    $headers.Authorization = "Bearer $([IO.File]::ReadAllText($tokenFile).Trim())"
    $restarted = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health/detailed" -Headers $headers -TimeoutSec 5
    if (-not $restarted.ok -or -not $restarted.data.kernel.ready) { throw "Restarted Runtime/Kernel did not recover." }
    $summary.restart_original_workload = (Get-Content -LiteralPath $recoveryReport -Raw | ConvertFrom-Json)
    $summary.restarted_runtime_pid = [int]$live.data.pid
    $summary.restarted_authenticated_status = $true
} finally {
    try {
        try { Stop-ProcessTree -Process $badParent }
        finally {
            try { Stop-ProcessTree -Process $parent }
            finally { Stop-ProcessTree -Process $kernelParent }
        }
    } finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
        }
        $env:PATH = $previousPath
        if ($EvidenceDirectory) {
            New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
            foreach ($path in @($nkiReport, $recoveryReport)) {
                if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $EvidenceDirectory -Force }
            }
        }
    }
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
$summary.final_runtime_process_closed = -not [bool](Get-Process -Id $summary.restarted_runtime_pid -ErrorAction SilentlyContinue)
if (-not $summary.final_runtime_process_closed) { throw "Native Runtime child survived final cleanup." }
$summary.stdout_captured = (Test-Path $stdoutFile) -and ([IO.File]::ReadAllText($stdoutFile).Contains("Nous Runtime API listening"))
$summary.kernel_stdout_captured = (Test-Path $kernelStdoutFile) -and ([IO.File]::ReadAllText($kernelStdoutFile).Contains("READY"))

if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}

[pscustomobject]$summary

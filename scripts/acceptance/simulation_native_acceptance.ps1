param(
    [string]$PortableRoot = (Resolve-Path "$PSScriptRoot\..\..\artifacts\windows-x64\Nous-Portable").Path,
    [string]$EvidencePath = (Join-Path (Resolve-Path "$PSScriptRoot\..\..").Path "artifacts\build-logs\p19-simulation-native-validation-20260901.json")
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FreePort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); return ([Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}
function Test-Port([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try { $attempt = $client.ConnectAsync("127.0.0.1", $Port); return $attempt.Wait(500) -and $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}
function Stop-Tree([Diagnostics.Process]$Process) {
    if ($Process -and -not $Process.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $Process.Id /T /F *> $null
    }
}
function Invoke-Api([string]$Method, [string]$Path, [string]$Json = "") {
    $arguments = @{ Uri = $script:Endpoint + $Path; Method = $Method; Headers = $script:Headers; TimeoutSec = 180 }
    if ($Json) { $arguments.ContentType = "application/json"; $arguments.Body = $Json }
    try { return @{ status = 200; body = Invoke-RestMethod @arguments } }
    catch {
        if (-not $_.ErrorDetails.Message) { throw }
        return @{ status = [int]$_.Exception.Response.StatusCode; body = $_.ErrorDetails.Message | ConvertFrom-Json }
    }
}
function Invoke-Approved([string]$Path, [string]$Json) {
    $first = Invoke-Api POST $Path $Json
    if ($first.body.ok) { throw "Mutation executed without approval: $Path" }
    $approvalId = [string]$first.body.error.details.approval_request_id
    if (-not $approvalId) { throw "Approval id missing: $Path" }
    $approval = Invoke-Api POST "/api/v1/approvals/$approvalId/approve" "{}"
    if (-not $approval.body.ok) { throw "Approval failed: $approvalId" }
    $retry = Invoke-Api POST $Path $Json
    if (-not $retry.body.ok) { throw "Approved retry failed: $Path - $($retry.body.error.message)" }
    return @{ approval_id = $approvalId; data = $retry.body.data }
}

$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$portable = (Resolve-Path -LiteralPath $PortableRoot).Path
$sidecar = Join-Path $portable "nous-runtime.exe"
$kernel = Join-Path $portable "nousd.exe"
$worker = Join-Path $portable "nous-provider-worker.exe"
$launcher = Join-Path $portable "Nous.exe"
foreach ($path in @($sidecar, $kernel, $worker, $launcher)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Native artifact missing: $path" }
}
$workspace = Join-Path $repo ("artifacts\build-logs\p19-native-workspace-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $workspace | Out-Null
$tokenFile = Join-Path $workspace "runtime-session.token"
$runtimeOut = Join-Path $workspace "runtime.stdout.log"
$runtimeErr = Join-Path $workspace "runtime.stderr.log"
$kernelOut = Join-Path $workspace "kernel.stdout.log"
$kernelErr = Join-Path $workspace "kernel.stderr.log"
$journal = Join-Path $workspace "kernel-journal.db"
$port = Get-FreePort
$kernelPort = Get-FreePort
while ($kernelPort -eq $port) { $kernelPort = Get-FreePort }
$env:NOUS_WORKSPACE_ROOT = $workspace
$env:NOUS_SESSION_TOKEN_FILE = $tokenFile
$env:NOUS_CLI_PATH = $null
$env:NOUS_KERNEL_ENDPOINT = "tcp://127.0.0.1:$kernelPort"
$env:NOUS_NKI_TOKEN = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$env:NOUS_ALLOWED_CREDENTIALS = ""
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$kernelProcess = $null
$runtimeProcess = $null
try {
    $kernelStart = @{
        FilePath = $kernel
        ArgumentList = @("serve", $journal, $worker, "127.0.0.1:$kernelPort")
        WorkingDirectory = $workspace
        WindowStyle = "Hidden"
        RedirectStandardOutput = $kernelOut
        RedirectStandardError = $kernelErr
        PassThru = $true
    }
    $kernelProcess = Start-Process @kernelStart
    $kernelReady = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($kernelProcess.HasExited) { throw "Kernel exited with code $($kernelProcess.ExitCode)" }
        if (Test-Port $kernelPort) { $kernelReady = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $kernelReady) { throw "Kernel did not become ready" }

    $runtimeStart = @{
        FilePath = $sidecar
        ArgumentList = @("runtime-api", "start", "--host", "127.0.0.1", "--port", [string]$port)
        WorkingDirectory = $workspace
        WindowStyle = "Hidden"
        RedirectStandardOutput = $runtimeOut
        RedirectStandardError = $runtimeErr
        PassThru = $true
    }
    $runtimeProcess = Start-Process @runtimeStart
    $script:Endpoint = "http://127.0.0.1:$port"
    $live = $null
    for ($attempt = 0; $attempt -lt 180; $attempt++) {
        if ($runtimeProcess.HasExited) { throw "Runtime exited: $([IO.File]::ReadAllText($runtimeErr))" }
        try { $live = Invoke-RestMethod -Uri "$script:Endpoint/live" -TimeoutSec 1; if ($live.ok) { break } } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $live -or -not $live.ok) { throw "Runtime did not become live" }
    for ($attempt = 0; $attempt -lt 20 -and -not (Test-Path $tokenFile); $attempt++) { Start-Sleep -Milliseconds 250 }
    $token = [IO.File]::ReadAllText($tokenFile).Trim()
    if ($token.Length -ne 64) { throw "Invalid session token" }
    $script:Headers = @{ Authorization = "Bearer $token"; Origin = "tauri://localhost" }

    $status = (Invoke-Api GET "/api/v1/simulations/status").body
    if (-not $status.ok) { throw "Simulation status failed" }
    $spec = [ordered]@{
        model_ref = "spacecraft-thermal/v1"
        environment_type = "local_sandbox"
        provider = "local-sandbox"
        initial_state = @{ initial_temperature = 290.0 }
        boundary_conditions = @{ external_temperature = 3.0 }
        parameters = @{
            solar_flux = 1361.0
            surface_area = 2.0
            emissivity = 0.8
            thermal_capacity = 10000.0
            absorptivity = 0.7
            max_safe_temperature = 373.15
        }
        solver = "explicit-euler"
        time_step = 1.0
        duration = 30.0
        seed = 42
        resource_budget = @{
            cpu_limit = 1.0
            memory_limit_mb = 256
            wall_time_seconds = 120
            max_cases = 4
            max_retries = 0
            max_output_bytes = 2000000
        }
        network_policy = @{ mode = "none" }
        metric_schema = @("peak_temperature", "final_temperature", "safety_margin", "sample_count")
        output_schema = @("json", "csv", "svg")
        parameter_space = @{ solar_flux = @(1000.0, 1361.0) }
        numerical_tolerance = @{ absolute = 1e-9; relative = 1e-9 }
        task_id = "p19-native-acceptance"
    }
    $specJson = $spec | ConvertTo-Json -Depth 8 -Compress
    $create = Invoke-Approved "/api/v1/simulations" $specJson
    $simulationId = [string]$create.data.simulation_id
    $run = Invoke-Approved "/api/v1/simulations/$simulationId/run" "{}"
    $runId = [string]$run.data.simulation_run_id
    $replay = Invoke-Approved "/api/v1/simulations/runs/$runId/replay" "{}"
    $environmentId = [string]$run.data.environment_id
    $environment = (Invoke-Api GET "/api/v1/environments/$environmentId").body.data
    $runEvents = (Invoke-Api GET "/api/v1/runtime/runs/$($run.data.event_run_id)/events").body.data.events
    $replayEvents = (Invoke-Api GET "/api/v1/runtime/runs/$($replay.data.event_run_id)/events").body.data.events
    $artifactChecks = @()
    foreach ($artifact in $run.data.artifacts) {
        $artifactPath = Join-Path $workspace ([string]$artifact.location).Replace("/", "\")
        $actual = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $artifactChecks += [ordered]@{
            artifact_id = $artifact.artifact_id
            name = $artifact.name
            location = $artifact.location
            sha256 = $actual
            expected_sha256 = [string]$artifact.sha256
            verified = $actual -eq [string]$artifact.sha256
        }
    }
    $evidence = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString("o")
        evidence_level = "native-packaged-windows-10-x64-integrated-host"
        workspace = $workspace
        token_disclosed = $false
        contracts = @{ simulation = $status.data.simulation_contract; run = $status.data.simulation_run_contract; environment = $status.data.environment_contract }
        scientific_providers = $status.data.scientific_providers
        approvals = @{ create = $create.approval_id; run = $run.approval_id; replay = $replay.approval_id }
        simulation_id = $simulationId
        simulation_run_id = $runId
        replay_run_id = [string]$replay.data.simulation_run_id
        case_count = [int]$run.data.case_count
        result_digest = [string]$run.data.result_digest
        replay_result_digest = [string]$replay.data.result_digest
        replay = $replay.data.replay
        execution_attempts = $run.data.execution_attempts
        environment = @{ environment_id = $environmentId; state = $environment.state; provider = $environment.provider; evidence_level = $status.data.built_in_models[0].evidence_level }
        artifacts = $artifactChecks
        run_event_sequence = @($runEvents | ForEach-Object { $_.event_type })
        replay_event_sequence = @($replayEvents | ForEach-Object { $_.event_type })
        reproducibility = $run.data.reproducibility
        runtime_pid = [int]$live.data.pid
        launcher_hash = (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash
        runtime_hash = (Get-FileHash -LiteralPath $sidecar -Algorithm SHA256).Hash
    }
    if ($evidence.case_count -ne 2) { throw "Expected two parameter cases" }
    if (-not $evidence.replay.verified -or $evidence.result_digest -ne $evidence.replay_result_digest) { throw "Deterministic replay failed" }
    if ($environment.state -ne "destroyed") { throw "Owned Environment was not destroyed" }
    if ($artifactChecks | Where-Object { -not $_.verified }) { throw "Artifact hash verification failed" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EvidencePath) | Out-Null
    [IO.File]::WriteAllText($EvidencePath, ($evidence | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    [PSCustomObject]@{
        status = "passed"
        evidence = $EvidencePath
        simulation_id = $simulationId
        run_id = $runId
        replay_verified = [bool]$evidence.replay.verified
        maximum_absolute_error = $evidence.replay.maximum_absolute_error
        artifact_count = $artifactChecks.Count
        environment_state = $environment.state
    }
} finally {
    Stop-Tree $runtimeProcess
    Stop-Tree $kernelProcess
}

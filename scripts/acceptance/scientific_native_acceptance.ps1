param(
    [string]$PortableRoot = (Resolve-Path "$PSScriptRoot\..\..\artifacts\windows-x64\Nous-Portable").Path,
    [string]$EvidencePath = (Join-Path (Resolve-Path "$PSScriptRoot\..\..").Path "artifacts\build-logs\p20-scientific-native-validation-20260901.json")
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
$workspace = Join-Path $repo ("artifacts\build-logs\p20-native-workspace-" + [guid]::NewGuid().ToString("N"))
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
    $scientificStatus = (Invoke-Api GET "/api/v1/scientific/status").body
    if (-not $scientificStatus.ok) { throw "Scientific status failed" }
    $expectedProviders = @("numpy", "scipy", "pandas", "sympy", "matplotlib")
    foreach ($providerName in $expectedProviders) {
        $provider = $scientificStatus.data.providers.$providerName
        if (-not $provider -or -not $provider.available -or -not [string]$provider.version) {
            throw "Scientific provider unavailable: $providerName"
        }
    }

    $analysisSpec = [ordered]@{
        simulation_run_id = $runId
        analysis_type = "spacecraft-thermal-analysis/v1"
        reference_solver = "scipy.solve_ivp"
        reference_tolerance_kelvin = 0.05
        report_formats = @("docx", "pdf")
        task_id = "p20-native-scientific-acceptance"
    }
    $analysisRequest = Invoke-Approved "/api/v1/scientific/analyses" ($analysisSpec | ConvertTo-Json -Depth 6 -Compress)
    $analysis = $analysisRequest.data
    $environment = (Invoke-Api GET "/api/v1/environments/$($analysis.environment_id)").body.data
    $events = (Invoke-Api GET "/api/v1/runtime/runs/$($analysis.event_run_id)/events").body.data.events
    $detail = (Invoke-Api GET "/api/v1/scientific/analyses/$($analysis.analysis_id)").body.data
    $listing = (Invoke-Api GET "/api/v1/scientific/analyses").body.data

    $artifactChecks = @()
    foreach ($artifact in $analysis.artifacts) {
        $artifactPath = Join-Path $workspace ([string]$artifact.location).Replace("/", "\")
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) { throw "Scientific artifact missing: $artifactPath" }
        $actual = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $artifactChecks += [ordered]@{
            artifact_id = [string]$artifact.artifact_id
            name = [string]$artifact.name
            location = [string]$artifact.location
            sha256 = $actual
            expected_sha256 = [string]$artifact.sha256
            verified = $actual -eq [string]$artifact.sha256
            size_bytes = (Get-Item -LiteralPath $artifactPath).Length
        }
    }
    $documentChecks = @()
    foreach ($output in $analysis.document.outputs) {
        $outputPath = Join-Path $workspace ([string]$output.location).Replace("/", "\")
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) { throw "Document output missing: $outputPath" }
        $actual = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $documentChecks += [ordered]@{
            artifact_id = [string]$output.artifact_id
            format = [string]$output.format
            location = [string]$output.location
            sha256 = $actual
            expected_sha256 = [string]$output.sha256
            verified = $actual -eq [string]$output.sha256
            size_bytes = (Get-Item -LiteralPath $outputPath).Length
            checks = @($output.checks)
        }
    }
    $claimChecks = @()
    foreach ($claimDetail in $analysis.claims) {
        $claimChecks += [ordered]@{
            claim_id = [string]$claimDetail.claim.claim_id
            verification_state = [string]$claimDetail.claim.verification_state
            trace_complete = [bool]$claimDetail.trace_complete
            artifact_refs = @($claimDetail.artifact_refs)
            evidence_relations = @($claimDetail.evidence | ForEach-Object { $_.relation })
        }
    }
    $providerVersions = [ordered]@{}
    foreach ($providerName in $expectedProviders) {
        $providerVersions[$providerName] = [string]$analysis.provider_inventory.$providerName.version
    }
    $eventSequence = @($events | ForEach-Object { $_.event_type })
    $requiredEvents = @(
        "run.created", "command.proposed", "run.started", "scientific.started",
        "scientific.reference_verified", "scientific.claims_created",
        "scientific.report_rendered", "scientific.completed", "run.completed"
    )

    if ($analysis.state -ne "completed" -or $detail.analysis_id -ne $analysis.analysis_id) { throw "Scientific record retrieval failed" }
    if ([int]$analysis.case_count -ne 2) { throw "Expected two scientific cases" }
    if (-not $analysis.reference_verified -or [double]$analysis.maximum_reference_error_kelvin -gt 0.05) { throw "Scientific reference verification failed" }
    if ($environment.state -ne "destroyed" -or $analysis.environment_state -ne "destroyed") { throw "Scientific Environment was not destroyed" }
    if ($artifactChecks.Count -ne 3 -or ($artifactChecks | Where-Object { -not $_.verified })) { throw "Scientific artifact verification failed" }
    if ($claimChecks.Count -ne 2 -or ($claimChecks | Where-Object { $_.verification_state -ne "supported" -or -not $_.trace_complete })) { throw "Claim/Evidence verification failed" }
    if (-not $analysis.document.verified -or $documentChecks.Count -ne 2 -or ($documentChecks | Where-Object { -not $_.verified })) { throw "DOCX/PDF verification failed" }
    if (($documentChecks.format | Sort-Object) -join "," -ne "docx,pdf") { throw "Expected DOCX and PDF outputs" }
    foreach ($requiredEvent in $requiredEvents) {
        if ($requiredEvent -notin $eventSequence) { throw "Missing scientific event: $requiredEvent" }
    }
    if ($eventSequence[0] -ne "run.created" -or $eventSequence[-1] -ne "run.completed") { throw "Scientific event boundaries are invalid" }
    if ([int]$listing.total -ne 1) { throw "Scientific list endpoint did not return exactly one analysis" }

    $evidence = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString("o")
        evidence_level = "native-packaged-windows-10-x64-integrated-host"
        workspace = $workspace
        token_disclosed = $false
        contracts = @{
            analysis = [string]$scientificStatus.data.analysis_contract
            result = [string]$scientificStatus.data.result_contract
            simulation = [string]$status.data.simulation_contract
        }
        providers = $providerVersions
        approvals = @{
            simulation_create = $create.approval_id
            simulation_run = $run.approval_id
            scientific_analyze = $analysisRequest.approval_id
        }
        simulation_id = $simulationId
        simulation_run_id = $runId
        analysis_id = [string]$analysis.analysis_id
        scientific_event_run_id = [string]$analysis.event_run_id
        case_count = [int]$analysis.case_count
        reference_solver = [string]$analysis.reference_solver
        reference_verified = [bool]$analysis.reference_verified
        reference_tolerance_kelvin = [double]$analysis.reference_tolerance_kelvin
        maximum_reference_error_kelvin = [double]$analysis.maximum_reference_error_kelvin
        safe_during_simulated_duration = [bool]$analysis.safe_during_simulated_duration
        worker_code_hash = [string]$analysis.worker_code_hash
        environment = @{
            environment_id = [string]$analysis.environment_id
            state = [string]$environment.state
            provider = [string]$environment.provider
            network_mode = [string]$environment.network_policy.mode
        }
        artifacts = $artifactChecks
        claims = $claimChecks
        document = @{
            document_id = [string]$analysis.document.document_id
            verified = [bool]$analysis.document.verified
            outputs = $documentChecks
        }
        event_sequence = $eventSequence
        runtime_pid = [int]$live.data.pid
        launcher_hash = (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash
        runtime_hash = (Get-FileHash -LiteralPath $sidecar -Algorithm SHA256).Hash
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EvidencePath) | Out-Null
    [IO.File]::WriteAllText($EvidencePath, ($evidence | ConvertTo-Json -Depth 14), [Text.UTF8Encoding]::new($false))
    [PSCustomObject]@{
        status = "passed"
        evidence = $EvidencePath
        analysis_id = $analysis.analysis_id
        providers = ($providerVersions.Keys -join ",")
        case_count = $analysis.case_count
        maximum_reference_error_kelvin = $analysis.maximum_reference_error_kelvin
        claim_count = $claimChecks.Count
        report_formats = ($documentChecks.format -join ",")
        environment_state = $environment.state
    }
} finally {
    Stop-Tree $runtimeProcess
    Stop-Tree $kernelProcess
}

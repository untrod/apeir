param(
    [int]$KernelPort = 18872
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$probeRoot = Join-Path $env:TEMP (
    "nous-integration-probe-" + [guid]::NewGuid().ToString("N")
)
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$resolvedProbe = [IO.Path]::GetFullPath($probeRoot)
if (-not $resolvedProbe.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Integration probe directory is outside the temporary directory."
}
New-Item -ItemType Directory -Path $resolvedProbe | Out-Null

$oldToken = $env:NOUS_NKI_TOKEN
$oldPythonPath = $env:PYTHONPATH
$process = $null
try {
    $env:NOUS_NKI_TOKEN = (
        "integration-probe-" + [guid]::NewGuid().ToString("N")
    )
    $env:PYTHONPATH = $repo
    $process = Start-Process `
        -FilePath (Join-Path $repo "desktop\src-tauri\binaries\nousd-aarch64-pc-windows-msvc.exe") `
        -ArgumentList @(
            "serve",
            (Join-Path $resolvedProbe "journal.db"),
            (Join-Path $repo "desktop\src-tauri\binaries\nous-provider-worker-aarch64-pc-windows-msvc.exe"),
            "127.0.0.1:$KernelPort"
        ) `
        -RedirectStandardOutput (Join-Path $resolvedProbe "out.log") `
        -RedirectStandardError (Join-Path $resolvedProbe "err.log") `
        -WindowStyle Hidden `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $client = [Net.Sockets.TcpClient]::new()
            $client.Connect("127.0.0.1", $KernelPort)
            $ready = $client.Connected
            $client.Dispose()
            if ($ready) { break }
        } catch {
            $ready = $false
        }
    }
    if (-not $ready) {
        throw "Integration probe kernel did not become ready."
    }

    & (Join-Path $repo ".venv\Scripts\python.exe") `
        -m scripts.acceptance.integration_observation_probe `
        --kernel-endpoint "tcp://127.0.0.1:$KernelPort"
    if ($LASTEXITCODE -ne 0) {
        throw "Integration observation probe failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    $env:NOUS_NKI_TOKEN = $oldToken
    $env:PYTHONPATH = $oldPythonPath
    if (Test-Path -LiteralPath $resolvedProbe) {
        Remove-Item -LiteralPath $resolvedProbe -Recurse -Force
    }
}

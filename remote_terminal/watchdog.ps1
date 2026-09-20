# 指挥层守护进程 —— 每分钟检查 agent/brain 是否存活,挂了自动拉起。
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1
# 建议加到 Windows 计划任务,触发器:每 1 分钟,无论用户是否登录。

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyExe = if ($env:NOUS_PYTHON) { $env:NOUS_PYTHON } else { "python.exe" }
$AgentPy = Join-Path $ScriptDir "agent.py"
$BrainPy = Join-Path $ScriptDir "brain.py"
$WorkDir = if ($env:NOUS_WORKDIR) { $env:NOUS_WORKDIR } else { $env:USERPROFILE }

function Test-Port($Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $c -ne $null
}

# 检查 Agent(8765)
if (-not (Test-Port 8765)) {
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Agent 不在线,正在拉起..."
    Start-Process -FilePath $PyExe -ArgumentList $AgentPy -WorkingDirectory $WorkDir -WindowStyle Hidden
}

# 检查 Brain(8770)
if (-not (Test-Port 8770)) {
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Brain 不在线,正在拉起..."
    Start-Process -FilePath $PyExe -ArgumentList $BrainPy -WorkingDirectory $WorkDir -WindowStyle Hidden
}

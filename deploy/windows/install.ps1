# Nous Runtime Windows Installer
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

param(
    [string]$InstallPath = "$env:ProgramFiles\NousRuntime",
    [switch]$RegisterService = $false
)

Write-Host "Nous Runtime v1.1.0 — Windows Installer" -ForegroundColor Cyan
Write-Host "============================================"

# 1. Python check
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python 3.10+ required. Install from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $(python --version)"

# 2. Install package
Write-Host "Installing nous-runtime..."
python -m pip install nous-runtime[all] -q

# 3. Verify
nous version
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installation failed." -ForegroundColor Red
    exit 1
}

# 4. PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$InstallPath*") {
    Write-Host "Add $InstallPath to your PATH for global `nous` command."
}

# 5. Service (optional)
if ($RegisterService) {
    Write-Host "Registering Windows service..."
    New-Service -Name "nousd" -BinaryPathName "$InstallPath\nousd.exe" -DisplayName "Nous Runtime Daemon" -StartupType Automatic
    Start-Service nousd
}

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host "  Start runtime: nous start"
Write-Host "  Interactive:   nous"
Write-Host "  Docs:          https://github.com/nous-runtime/nous"

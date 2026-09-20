# Nous Runtime — Clean Install Validation (Windows)
# Run: powershell -ExecutionPolicy Bypass -File scripts/validate_clean_install.ps1

$ErrorActionPreference = "Stop"
$VENV = "test_nous_venv"
$PASS = 0
$FAIL = 0

function Test-Command($Name, $Script) {
    Write-Host "  [$Name] " -NoNewline
    try {
        & $Script 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PASS" -ForegroundColor Green
            $global:PASS++
        } else {
            Write-Host "FAIL (exit code: $LASTEXITCODE)" -ForegroundColor Red
            $global:FAIL++
        }
    } catch {
        Write-Host "FAIL ($_)" -ForegroundColor Red
        $global:FAIL++
    }
}

Write-Host "Nous Runtime v1.0.0 — Clean Install Validation" -ForegroundColor Cyan
Write-Host "================================================="

# 1. Create venv
Write-Host "`n1. Creating clean virtual environment..."
python -m venv $VENV
$ACTIVATE = ".\$VENV\Scripts\Activate.ps1"
. $ACTIVATE

# 2. Install
Write-Host "`n2. Installing package..."
pip install -e . --no-cache-dir -q 2>&1 | Out-Null

# 3. Test commands
Write-Host "`n3. Testing commands..."
Test-Command "nous --help"       { nous --help }
Test-Command "nous version"      { nous version }
Test-Command "nous doctor"       { nous doctor }
Test-Command "nous status"       { nous status }
Test-Command "nous demo"         { nous demo }
Test-Command "nous provider list"  { nous provider list }
Test-Command "nous capability list" { nous capability list }
Test-Command "nous pack list"    { nous pack list }
Test-Command "nous trace"        { nous trace --limit 3 }
Test-Command "nous pack --help"  { nous pack --help }
Test-Command "nous provider --help" { nous provider --help }
Test-Command "nous capability --help" { nous capability --help }
Test-Command "nous dev --help"   { nous dev --help }

# 4. Cleanup
Write-Host "`n4. Cleaning up..."
deactivate
Remove-Item -Recurse -Force $VENV

# 5. Summary
Write-Host "`n================================================="
Write-Host "Results: $PASS passed, $FAIL failed"
if ($FAIL -eq 0) {
    Write-Host "Status: PASS" -ForegroundColor Green
} else {
    Write-Host "Status: FAIL" -ForegroundColor Red
}

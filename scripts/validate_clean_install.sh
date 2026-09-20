#!/bin/bash
# Nous Runtime — Clean Install Validation (Linux/macOS)
# Run: bash scripts/validate_clean_install.sh

set -e
VENV="test_nous_venv"
PASS=0
FAIL=0

test_cmd() {
    local name="$1"
    shift
    printf "  [%s] " "$name"
    if "$@" > /dev/null 2>&1; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
    fi
}

echo "Nous Runtime v1.0.0 — Clean Install Validation"
echo "================================================="

# 1. Create venv
echo ""
echo "1. Creating clean virtual environment..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"

# 2. Install
echo ""
echo "2. Installing package..."
pip install -e . --no-cache-dir -q

# 3. Test commands
echo ""
echo "3. Testing commands..."
test_cmd "nous --help"        nous --help
test_cmd "nous version"       nous version
test_cmd "nous doctor"        nous doctor
test_cmd "nous status"        nous status
test_cmd "nous demo"          nous demo
test_cmd "nous provider list"   nous provider list
test_cmd "nous capability list" nous capability list
test_cmd "nous pack list"     nous pack list
test_cmd "nous trace"         nous trace --limit 3
test_cmd "nous pack --help"   nous pack --help
test_cmd "nous provider --help" nous provider --help
test_cmd "nous capability --help" nous capability --help
test_cmd "nous dev --help"    nous dev --help

# 4. Cleanup
echo ""
echo "4. Cleaning up..."
deactivate
rm -rf "$VENV"

# 5. Summary
echo ""
echo "================================================="
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -eq 0 ]; then
    echo "Status: PASS"
else
    echo "Status: FAIL"
    exit 1
fi

#!/usr/bin/env bash

# Nous Doctor — security health check

set -euo pipefail

PASS=0; FAIL=0; WARN=0
check() { if [ $1 -eq 0 ]; then echo "  PASS $2"; PASS=$((PASS+1)); else echo "  FAIL $2"; FAIL=$((FAIL+1)); fi }
warn()  { echo "  WARN  $1"; WARN=$((WARN+1)); }

echo "╔======================================╗"
echo "║        Nous Doctor — Security       ║"
echo "╚======================================╝"
echo ""

# .env Security
echo "[1] Environment Security"
[ -f remote_terminal/.env ] && check 0 ".env exists" || check 1 ".env MISSING"
[ "$(stat -c %a remote_terminal/.env 2>/dev/null || echo 644)" = "600" ] && check 0 ".env permissions 600" || warn ".env should be chmod 600"
grep -q "sk-your-key" remote_terminal/.env 2>/dev/null && warn "API key is still default placeholder" || check 0 "API key is set"
grep -q "change-me" remote_terminal/.env 2>/dev/null && warn "AUTH_TOKEN is still default placeholder" || check 0 "Auth token is set"
grep -q "change-me" remote_terminal/.env 2>/dev/null && warn "AGENT_SIGNING_SECRET is still default" || check 0 "Signing secret is set"

# Data Security
echo "[2] Data Security"
[ -d remote_terminal/data ] && check 0 "Data directory exists" || check 1 "Data directory MISSING"
[ "$(stat -c %a remote_terminal/data 2>/dev/null || echo 755)" = "700" ] && check 0 "Data directory permissions 700" || warn "Data dir should be chmod 700"
find remote_terminal/data -name "*.db" -perm /o+r 2>/dev/null | head -1 | read && warn "Database files world-readable" || check 0 "Database files not world-readable"

# High-Risk Capabilities
echo "[3] High-Risk Capabilities"
grep -q "NOUS_ENABLE_PC_SHELL=1" remote_terminal/.env 2>/dev/null && warn "PC Shell execution ENABLED (HIGH risk)" || check 0 "PC Shell execution disabled by default"
grep -q "NOUS_ENABLE_PHONE_CONTROL=1" remote_terminal/.env 2>/dev/null && warn "Phone control ENABLED (HIGH risk)" || check 0 "Phone control disabled by default"
grep -q "NOUS_ENABLE_FILE_WRITE=1" remote_terminal/.env 2>/dev/null && warn "File write ENABLED (HIGH risk)" || check 0 "File write disabled by default"

# Port Exposure
echo "[4] Network Exposure"
BIND_HOST=$(grep "NOUS_BRAIN_HOST" remote_terminal/.env 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'" || echo "")
[ "$BIND_HOST" = "127.0.0.1" ] && check 0 "Brain bound to localhost only" || warn "Brain bound to $BIND_HOST (ensure firewall)"
ss -tlnp 2>/dev/null | grep -q ":8770" && warn "Port 8770 is listening (ensure firewall)" || check 0 "Port 8770 not exposed"

# Git Security
echo "[5] Git Security"
git ls-files 2>/dev/null | grep -q ".env$" && check 1 ".env is TRACKED by git!" || check 0 ".env not tracked by git"
git ls-files 2>/dev/null | grep -q "config.local.json" && check 1 "config.local.json TRACKED!" || check 0 "config.local.json not tracked"
git ls-files 2>/dev/null | grep -q "clients.json" && check 1 "clients.json TRACKED!" || check 0 "clients.json not tracked"
git ls-files 2>/dev/null | grep -q ".key$" && check 1 "Private key files TRACKED!" || check 0 "No private keys in git"

# Log Hygiene
echo "[6] Log Hygiene"
LOG_SIZE=$(du -sm remote_terminal/*.log 2>/dev/null | awk '{s+=$1}END{print s+0}')
[ "$LOG_SIZE" -gt 100 ] && warn "Log files are $LOG_SIZE MB (consider rotation)" || check 0 "Log size under 100MB"
grep -r "sk-" remote_terminal/*.log 2>/dev/null | head -1 | read && check 1 "API keys found in logs!" || check 0 "No API keys in logs"
grep -r "Bearer" remote_terminal/*.log 2>/dev/null | head -1 | read && warn "Bearer tokens found in logs" || check 0 "No tokens in logs"

# Database
echo "[7] Database Health"
DB_SIZE=$(du -sm remote_terminal/data/nous_core.db 2>/dev/null | awk '{print $1+0}')
[ "$DB_SIZE" -gt 500 ] && warn "nous_core.db is $DB_SIZE MB (consider vacuum)" || check 0 "Database size healthy ($DB_SIZE MB)"

# Backup
echo "[8] Backup Status"
[ -f remote_terminal/sessions.json.bak ] && check 0 "Session backup exists" || warn "No session backup"
[ -f remote_terminal/learn_data.db ] && [ ! -f remote_terminal/learn_data.db.bak ] && warn "No learn_data.db backup" || true

# Summary
echo ""
echo "----------------------------------------"
echo "Results: $PASS passed, $WARN warnings, $FAIL failed"
echo "----------------------------------------"
if [ $FAIL -gt 0 ]; then
    echo "FAIL Fix the failures above before deploying."
elif [ $WARN -gt 0 ]; then
    echo "WARN  Review warnings above."
else
    echo "PASS All checks passed. Nous is secure."
fi

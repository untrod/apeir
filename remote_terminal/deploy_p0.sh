#!/usr/bin/env bash

# Nous P0 Kernel — Server Deployment Script

# Run from the Nous install directory (default: /opt/nous).
# Set NOUS_HOME env var to override.

set -euo pipefail
NOUS_HOME="${NOUS_HOME:-/opt/nous}"
cd "$NOUS_HOME"

echo "=== Nous P0 Kernel Deployment ==="
echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# 1. Stop the brain service
echo "[1/7] Stopping nous service..."
systemctl stop nous 2>/dev/null || true
sleep 2

# 2. Back up current files
echo "[2/7] Backing up current brain.py and brain_devices.py..."
cp brain.py brain.py.p0bak.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
cp brain_devices.py brain_devices.py.p0bak.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

# 3. Install nous_core module
echo "[3/7] Installing nous_core/ module..."
mkdir -p nous_core/events nous_core/jobs nous_core/devices nous_core/notifications nous_core/migrations
# (files should already be in place from the tarball extraction)

# 4. Syntax check all Python files
echo "[4/7] Syntax checking..."
python3 -c "import ast
for f in ['brain.py', 'brain_devices.py',
          'nous_core/__init__.py', 'nous_core/config.py', 'nous_core/db.py',
          'nous_core/ids.py', 'nous_core/time.py',
          'nous_core/events/__init__.py', 'nous_core/events/dispatcher.py',
          'nous_core/jobs/__init__.py', 'nous_core/devices/__init__.py',
          'nous_core/notifications/__init__.py']:
    ast.parse(open(f, encoding='utf-8').read())
    print(f'  {f} OK')
print('All files pass syntax check')
"

# 5. Start the brain service
echo "[5/7] Starting nous service..."
systemctl start nous
sleep 3

# 6. Health check
echo "[6/7] Health check..."
NOUS_HEALTH_URL="${NOUS_HEALTH_URL:-http://127.0.0.1:8770/api/v1/health}"
curl -fsS "$NOUS_HEALTH_URL" 2>/dev/null || echo "WARNING: Health check failed (may need a few more seconds)"

# 7. Verify nous_core initialization
echo "[7/7] Verifying nous_core..."
python3 -c "
import sqlite3
db = sqlite3.connect('data/nous_core.db')
tables = [r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()]
print(f'Tables: {tables}')
for t in tables:
    cnt = db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t}: {cnt} rows')
db.close()
"

echo "=== Deployment complete ==="
echo "Check events: python3 -c \"from nous_core.events import count_events; print(count_events(), 'events recorded')\""
echo "Check jobs: python3 -c \"from nous_core.jobs import count_jobs; print(count_jobs(), 'jobs stored')\""
echo "Start dispatcher: (auto-started with brain)"

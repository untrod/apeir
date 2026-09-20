#!/usr/bin/env bash
# ==============================================================
# Nous One-Click Install
# ==============================================================
set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║     Nous Intelligence Runtime       ║"
echo "║         Quick Install               ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Check prerequisites ──
echo "[1/6] Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl required"; exit 1; }
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PYTHON_VER ✓"
echo "  curl ✓"

# ── 2. .env setup ──
echo "[2/6] Setting up .env..."
if [ ! -f .env ]; then
    cp remote_terminal/.env.example remote_terminal/.env
    chmod 600 remote_terminal/.env
    echo "  Created remote_terminal/.env (edit with your keys)"
else
    echo "  .env already exists, skipping"
fi

# ── 3. Install Python dependencies ──
echo "[3/6] Installing Python dependencies..."
cd remote_terminal
python3 -m pip install --quiet --upgrade pip 2>/dev/null || true
python3 -m pip install --quiet -r requirements.txt 2>/dev/null || {
    echo "  Some pip packages may need system deps (tesseract, etc.)"
    echo "  Continuing anyway — optional features will be disabled"
}
cd ..
echo "  Dependencies installed ✓"

# ── 4. Syntax check ──
echo "[4/6] Verifying installation..."
cd remote_terminal
python3 -c "
import ast, os
errors = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__','brain','sessions','learn_docs','vector_data')]
    for f in files:
        if f.endswith('.py'):
            try:
                ast.parse(open(os.path.join(root,f), encoding='utf-8').read())
            except SyntaxError as e:
                errors.append(f'{os.path.join(root,f)}: {e}')
if errors:
    for e in errors: print(f'  ERROR: {e}')
    exit(1)
print('  All Python files pass syntax check ✓')
" || { echo "  Syntax errors found!"; exit 1; }
cd ..

# ── 5. Create data directories ──
echo "[5/6] Creating data directories..."
mkdir -p remote_terminal/data
chmod 700 remote_terminal/data
echo "  Data directory created ✓"

# ── 6. Done ──
echo "[6/6] Installation complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit remote_terminal/.env with your API keys"
echo "  2. Start: cd remote_terminal && python3 brain.py"
echo "  3. Health: curl http://localhost:8770/health"
echo "  4. Setup:  curl http://localhost:8770/setup?token=YOUR_AUTH_TOKEN"
echo "  5. Doctor: bash scripts/nous-doctor.sh"
echo ""
echo "  Docker alternative: docker compose up -d"

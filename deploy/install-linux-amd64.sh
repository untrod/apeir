#!/usr/bin/env bash
# Nous Runtime — Linux amd64 Tier 1 Installer
# Target: Ubuntu 20.04+, Debian 11+, RHEL 8+
# Installs: Full Runtime (Server Primary, Desktop, CUDA GPU support)
set -euo pipefail

ARCH="amd64"
TIER="full"
INSTALL_DIR="${NOUS_HOME:-$HOME/.nous}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

echo "=== Nous Runtime Installer — Linux ${ARCH} (${TIER}) ==="
echo "Install directory: ${INSTALL_DIR}"

# Check Python
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
    echo "Installing Python 3.11..."
    sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

# Create virtualenv
VENV_DIR="${INSTALL_DIR}/venv"
if [ ! -d "${VENV_DIR}" ]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"

# Install Nous Runtime with Tier 1 extras
pip install --upgrade pip
pip install "nous-runtime[tier1]"

# Platform detection
python -c "
from nous_runtime.platform import platform_service
print(f'Detected: {platform_service.info.platform_tag}')
assert platform_service.tier.value == 'full', 'Expected full tier'
assert platform_service.architecture.value == 'amd64', 'Expected amd64'
print('Platform verification OK')
"

# Create service
SERVICE_FILE="/etc/systemd/system/nous-runtime.service"
if [ ! -f "${SERVICE_FILE}" ]; then
    sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=Nous Runtime Server
After=network.target

[Service]
Type=simple
User=${USER}
ExecStart=${VENV_DIR}/bin/nous server start
Restart=on-failure
RestartSec=5
Environment=NOUS_HOME=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable nous-runtime
    echo "Service installed. Run: sudo systemctl start nous-runtime"
fi

echo "=== Installation complete ==="
echo "Start:  sudo systemctl start nous-runtime"
echo "Status: sudo systemctl status nous-runtime"
echo "CLI:    nous --help"

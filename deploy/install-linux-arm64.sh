#!/usr/bin/env bash
# Nous Runtime — Linux ARM64 Tier 1 Installer
# Target: Ubuntu 22.04+ on ARM64 (Jetson Orin, AWS Graviton, Raspberry Pi 5)
# Installs: Full Runtime (Server Primary, optional local LLM)
set -euo pipefail

ARCH="arm64"
TIER="full"
INSTALL_DIR="${NOUS_HOME:-$HOME/.nous}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

echo "=== Nous Runtime Installer — Linux ${ARCH} (${TIER}) ==="
echo "Install directory: ${INSTALL_DIR}"

# Check platform
MACHINE=$(uname -m)
if [ "${MACHINE}" != "aarch64" ]; then
    echo "WARNING: This installer is for ARM64 (aarch64). Detected: ${MACHINE}"
    echo "Use install-linux-amd64.sh for x86_64 or install-linux-armv7-lite.sh for ARM32."
    read -p "Continue anyway? [y/N] " -n 1 -r; echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
fi

# Jetson detection
IS_JETSON=false
if [ -f /proc/device-tree/model ] && grep -qi "jetson\|tegra" /proc/device-tree/model; then
    IS_JETSON=true
    echo "Jetson platform detected — enabling JetPack optimizations"
fi

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

# Install Nous Runtime
pip install --upgrade pip
pip install "nous-runtime[tier1,arm64]"

# Jetson-specific: install ONNX Runtime for GPU
if [ "${IS_JETSON}" = true ]; then
    echo "Installing Jetson-optimized packages..."
    pip install onnxruntime-gpu 2>/dev/null || echo "  (onnxruntime-gpu not available, using CPU)"
fi

# Platform detection
python -c "
from nous_runtime.platform import platform_service
print(f'Detected: {platform_service.info.platform_tag}')
assert platform_service.tier.value == 'full', 'Expected full tier'
assert platform_service.architecture.value == 'arm64', 'Expected arm64'
print('Platform verification OK')
"

# Create service
SERVICE_FILE="/etc/systemd/system/nous-runtime.service"
if [ ! -f "${SERVICE_FILE}" ]; then
    sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=Nous Runtime Server (ARM64)
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
fi

echo "=== Installation complete ==="
echo "Start:  sudo systemctl start nous-runtime"
echo "CLI:    nous --help"
if [ "${IS_JETSON}" = true ]; then
    echo "Jetson: Local model setup — nous model install --local llama3.2"
fi

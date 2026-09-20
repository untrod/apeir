#!/usr/bin/env bash
# Nous Runtime — Linux ARMv7 Lite Node Installer
# Target: Raspberry Pi 3/4 (ARMv7), ARM32 edge devices
# Installs: Lite Node only (identity, heartbeat, capability executor, offline buffer)
# NO desktop UI, NO local LLM, NO vector DB, NO heavy agent runtime
set -euo pipefail

ARCH="armv7"
TIER="lite"
INSTALL_DIR="${NOUS_HOME:-$HOME/.nous}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "=== Nous Runtime Installer — Linux ${ARCH} (${TIER}) ==="
echo "Install directory: ${INSTALL_DIR}"
echo ""
echo "Lite Node restrictions:"
echo "  ✓ Identity attestation & key rotation"
echo "  ✓ Secure communication (TLS)"
echo "  ✓ Heartbeat with Primary"
echo "  ✓ Capability Executor (restricted allowlist)"
echo "  ✓ Device adapters (GPIO, serial, I2C)"
echo "  ✓ Offline buffer (store-and-forward)"
echo "  ✓ Audit logging"
echo "  ✓ Update check & rollback"
echo "  ✗ Desktop UI / GUI"
echo "  ✗ Local LLM inference"
echo "  ✗ Vector databases"
echo "  ✗ Heavy Agent Runtime"
echo "  ✗ Training / fine-tuning"
echo ""

# Check platform
MACHINE=$(uname -m)
if [ "${MACHINE}" != "armv7l" ]; then
    echo "NOTE: This installer is for ARMv7 (32-bit). Detected: ${MACHINE}"
    echo "You can still run in lite mode on any architecture."
    read -p "Continue? [y/N] " -n 1 -r; echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
fi

# Check Python (3.10+ required, Raspberry Pi OS has 3.11)
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
    echo "Installing Python 3..."
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-dev
    PYTHON_BIN="python3"
fi

PYVER=$(${PYTHON_BIN} --version 2>&1 | grep -oP '\d+\.\d+')
echo "Python version: ${PYVER}"

# Create virtualenv
VENV_DIR="${INSTALL_DIR}/venv"
if [ ! -d "${VENV_DIR}" ]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}" --without-pip
    curl -sS https://bootstrap.pypa.io/get-pip.py | "${VENV_DIR}/bin/python"
fi
source "${VENV_DIR}/bin/activate"

# Install Lite deps only (no heavy packages)
pip install --upgrade pip
pip install "nous-runtime[tier2-lite]"

# Verify Lite Node restrictions
python -c "
from nous_runtime.platform import (
    platform_service, Architecture, RuntimeTier,
    LITE_NODE_ALWAYS_ALLOWED, LITE_NODE_RESTRICTED_CAPABILITIES,
)
print(f'Platform: {platform_service.info.platform_tag}')
print(f'Tier: {platform_service.tier.value}')
print(f'Allowed capabilities: {len(LITE_NODE_ALWAYS_ALLOWED)}')
print(f'Restricted capabilities: {len(LITE_NODE_RESTRICTED_CAPABILITIES)}')

# Verify heavy deps are NOT installed
for pkg in ['torch', 'chromadb', 'llama_cpp', 'sentence_transformers', 'vllm']:
    try:
        __import__(pkg.replace('-', '_'))
        print(f'WARNING: {pkg} is installed — should not be on Lite Node')
    except ImportError:
        print(f'  OK: {pkg} not installed')
print('Lite Node verification complete')
"

# Create Lite Node config
CONFIG_FILE="${INSTALL_DIR}/lite_config.json"
if [ ! -f "${CONFIG_FILE}" ]; then
    cat > "${CONFIG_FILE}" <<EOF
{
    "node_name": "$(hostname)",
    "primary_url": "http://localhost:8770",
    "primary_token": "",
    "heartbeat_interval_sec": 30,
    "offline_buffer_max_mb": 50,
    "offline_buffer_dir": "${INSTALL_DIR}/offline_buffer",
    "audit_log_path": "${INSTALL_DIR}/lite_audit.log",
    "device_adapters": [],
    "allowed_capabilities": [
        "identity.attest",
        "connectivity.heartbeat",
        "connectivity.handshake",
        "connectivity.offline_buffer",
        "capability.execute",
        "device.adapter.scan",
        "audit.log",
        "audit.export",
        "update.check",
        "update.apply",
        "security.verify_signature"
    ]
}
EOF
    echo "Lite Node config created: ${CONFIG_FILE}"
    echo "Edit this file to configure your Primary URL and device adapters."
fi

# Create service
SERVICE_FILE="/etc/systemd/system/nous-lite-node.service"
if [ ! -f "${SERVICE_FILE}" ]; then
    sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=Nous Lite Node (ARMv7)
After=network.target

[Service]
Type=simple
User=${USER}
ExecStart=${VENV_DIR}/bin/python -m nous_runtime.platform.lite_node --config ${CONFIG_FILE}
Restart=on-failure
RestartSec=10
Environment=NOUS_HOME=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable nous-lite-node
fi

echo ""
echo "=== Lite Node Installation Complete ==="
echo "Config:   ${CONFIG_FILE}"
echo "Start:    sudo systemctl start nous-lite-node"
echo "Status:   sudo systemctl status nous-lite-node"
echo "Audit:    tail -f ${INSTALL_DIR}/lite_audit.log"
echo ""
echo "Configure your Primary URL in ${CONFIG_FILE} before starting."

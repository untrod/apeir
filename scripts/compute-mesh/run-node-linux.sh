#!/usr/bin/env bash
set -euo pipefail
umask 077

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${APEIR_PYTHON:-${repository_root}/.venv/bin/python}"
state_dir="${APEIR_NODE_STATE_DIR:-${repository_root}/.local/compute-mesh-node}"
node_name="${APEIR_NODE_NAME:-apeir-linux-$(hostname)}"
relay_url="${APEIR_RELAY_URL:-}"
server_public_key="${APEIR_SERVER_PUBLIC_KEY:-}"
ca_file="${APEIR_CA_FILE:-}"
heartbeat="${APEIR_NODE_HEARTBEAT_SECONDS:-15}"

if [[ ! -x "${python_bin}" ]]; then
    echo "APEIR Python environment is missing: ${python_bin}" >&2
    exit 2
fi
if [[ ! "${relay_url}" =~ ^wss:// ]]; then
    echo "A remote Compute Mesh Node requires APEIR_RELAY_URL=wss://..." >&2
    exit 2
fi
if [[ ! "${server_public_key}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "APEIR_SERVER_PUBLIC_KEY must be a 32-byte Ed25519 public key in hex." >&2
    exit 2
fi
if [[ -n "${ca_file}" && ! -f "${ca_file}" ]]; then
    echo "Configured APEIR_CA_FILE does not exist: ${ca_file}" >&2
    exit 2
fi

arguments=(
    -m nous_runtime.node_runtime.cli
    --state-dir "${state_dir}"
    --name "${node_name}"
    --heartbeat-seconds "${heartbeat}"
    --relay-url "${relay_url}"
    --server-public-key "${server_public_key}"
)
if [[ -n "${ca_file}" ]]; then
    arguments+=(--ca-file "${ca_file}")
fi

exec "${python_bin}" "${arguments[@]}"

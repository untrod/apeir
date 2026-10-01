#!/usr/bin/env bash
set -euo pipefail
umask 077

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${APEIR_PYTHON:-${repository_root}/.venv/bin/python}"
state_dir="${APEIR_CONTROLLER_STATE_DIR:-${repository_root}/.local/compute-mesh-controller}"
host="${APEIR_CONTROLLER_HOST:-127.0.0.1}"
port="${APEIR_CONTROLLER_PORT:-9771}"
heartbeat="${APEIR_CONTROLLER_HEARTBEAT_SECONDS:-15}"
cert_file="${APEIR_CONTROLLER_CERT_FILE:-}"
key_file="${APEIR_CONTROLLER_KEY_FILE:-}"

if [[ ! -x "${python_bin}" ]]; then
    echo "APEIR Python environment is missing: ${python_bin}" >&2
    exit 2
fi

arguments=(
    -m nous_runtime.node_runtime.relay_cli serve
    --state-dir "${state_dir}"
    --host "${host}"
    --port "${port}"
    --heartbeat-seconds "${heartbeat}"
)

if [[ -n "${cert_file}" || -n "${key_file}" ]]; then
    if [[ ! -f "${cert_file}" || ! -f "${key_file}" ]]; then
        echo "Both Controller TLS certificate and key must exist." >&2
        exit 2
    fi
    arguments+=(--cert-file "${cert_file}" --key-file "${key_file}")
fi

exec "${python_bin}" "${arguments[@]}"

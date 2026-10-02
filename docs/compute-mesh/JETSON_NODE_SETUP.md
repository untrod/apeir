# Jetson Node setup

This guide connects an NVIDIA Jetson Orin Nano to an existing APEIR Compute
Mesh Controller as an independent ARM64 Node. It does not change Kernel
authority or the `nous.*.v1` compatibility protocol.

## Supported baseline

The first certified target is:

- NVIDIA Jetson Orin Nano
- JetPack 5 / L4T R35 on Ubuntu 20.04
- `aarch64`
- Python 3.10 or newer in an isolated environment

JetPack 5 includes Python 3.8 as the operating-system interpreter. APEIR
requires Python 3.10 or newer and uses Python 3.10 language features. Do not
replace JetPack's system Python or lower APEIR's declared Python requirement.
Install a separate Python 3.10+ interpreter and set `APEIR_PYTHON` when the
virtual environment is not located at `.venv`.

Confirm the interpreter before installing APEIR:

```bash
python3.10 -c 'import platform, sys; print(platform.machine(), sys.version); assert sys.version_info >= (3, 10)'
```

## Install the Node

Check out the same Distribution revision used by the Controller and other
Nodes, then create a fresh environment:

```bash
cd ~/workspace/apeir
git switch feature/compute-mesh-v0.1
git pull --ff-only
git status --short
git rev-parse HEAD

python3.10 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e .
.venv/bin/python -m nous_runtime.node_runtime.cli --help
```

The worktree must be clean. Record the revision in the deployment evidence; do
not patch the Jetson checkout independently.

## Create and enroll the Jetson identity

Generate the identity on the Jetson. Never copy an identity from a Windows
Node or from the Controller.

```bash
.venv/bin/apeir-node \
  --state-dir .local/compute-mesh-node \
  --name jetson-orin-nano \
  --identity-only \
  --json
```

Transfer only `.local/compute-mesh-node/identity.json` to the Controller over an
authenticated channel. Enroll the public identity on the Controller:

```bash
sudo -u apeir /opt/apeir/.venv/bin/apeir-controller trust \
  /tmp/jetson-orin-nano-identity.json \
  --state-dir /var/lib/apeir-controller
```

Keep `.local/compute-mesh-node/identity.ed25519.pem` on the Jetson with mode
`0600`. It is the Node's private identity and must not be committed, uploaded,
or copied to another machine.

## Configure trust and start the Node

Copy the Controller's TLS CA certificate to the Jetson over an authenticated
channel. Obtain the Controller Ed25519 public key from the Controller's trusted
deployment record, not from an unauthenticated network response.

```bash
export APEIR_NODE_NAME=jetson-orin-nano
export APEIR_NODE_STATE_DIR="$HOME/workspace/apeir/.local/compute-mesh-node"
export APEIR_RELAY_URL="wss://controller.example:9771"
export APEIR_SERVER_PUBLIC_KEY="<64-hex-character-controller-public-key>"
export APEIR_CA_FILE="$HOME/.config/apeir/controller-ca.pem"

scripts/compute-mesh/run-node-linux.sh
```

The launcher fails closed when the relay is not `wss://`, the Controller key is
not a 32-byte Ed25519 public key in hexadecimal, or the configured CA file does
not exist.

## Acceptance checks

On the Controller, inspect durable state:

```bash
sudo -u apeir /opt/apeir/.venv/bin/apeir-controller status \
  --state-dir /var/lib/apeir-controller
```

Verify deterministic placement before binding a workload to a Node:

```bash
sudo -u apeir /opt/apeir/.venv/bin/apeir-controller select-node \
  --state-dir /var/lib/apeir-controller \
  --architecture arm64 \
  --capability system.echo
```

The decision uses signed, durable Controller observations and stable Node ID
ordering. It is not an LLM decision, does not grant capabilities, and fails
closed with exit code `2` when no eligible Node is available.

The signed observations for `jetson-orin-nano` must show:

- registration under its own Node identity;
- recent heartbeats;
- `architecture` reported as `aarch64` or normalized `arm64`;
- Ubuntu and host resource facts;
- resource, device, and execution-host reports.

Complete certification also requires three real operations through the
Controller:

1. Store the Jetson execution-host inventory as a content-addressed artifact and
   verify its SHA-256 digest.
2. Dispatch a bounded remote workload and retain its signed result envelope and
   OperationReceipt.
3. Run signed execution preflight against the candidates, invoke deterministic
   placement with `architecture=arm64`, and verify that it selects the Jetson
   rather than an AMD64 Node before the workload target is bound.

A connected socket or an `echo` alone is not sufficient evidence. Preserve the
Node identity hash, Distribution revision, signed observations, workload
binding, receipt, artifact digest, and verification result as the acceptance
record.

## Integrated GPU discovery

Jetson does not normally expose its integrated GPU through the desktop/server
NVML path used by discrete NVIDIA GPUs. The Node therefore reports a CUDA
device only when all of the following bounded host evidence is present:

- Linux on ARM64;
- an NVIDIA Jetson, Orin, Xavier, or Tegra device-tree model;
- an L4T release record;
- both `/dev/nvhost-gpu` and `/dev/nvmap`.

The CUDA version is read from the local JetPack installation when available.
Because Jetson uses unified memory, the fallback does not invent a dedicated
VRAM capacity. If any required evidence is missing, `gpu_required=true`
placement remains unsatisfied and no Work is dispatched.

## Troubleshooting

### The package requires a newer Python

If installation reports that Python 3.8 is unsupported, the wrong interpreter
created the environment. Recreate it with Python 3.10 or newer. Do not edit
`requires-python` and do not replace `/usr/bin/python3` on JetPack.

### The Controller rejects registration

Confirm that the exact Jetson `identity.json` was enrolled and that the Node
retained the corresponding private key. Re-enrolling a public identity does not
repair a Node whose private identity was deleted.

### TLS or key pinning fails

Verify the CA path, the hostname or IP address covered by the certificate, and
the pinned Controller public key. Do not disable TLS verification or downgrade
the relay URL to plaintext.

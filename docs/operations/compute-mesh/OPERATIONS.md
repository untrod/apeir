# Compute Mesh operations

APEIR Compute Mesh uses the existing authenticated Node Protocol. The Controller
does not grant Kernel authority. It maintains durable node trust, signed workload
results, pending controls, and a content-addressed artifact store. Nodes retain
their own Ed25519 private keys; only public `identity.json` files are enrolled.
Node and Controller startup fail closed if their private-key files cannot be
restricted to the current operating-system identity.

Protocol identifiers under `nous.*.v1` remain compatibility contracts. The
public commands use the APEIR product name.

## 1. Controller on Linux

Use a dedicated host and a DNS name with a valid TLS certificate. Internet-facing
plaintext WebSockets are rejected by the Runtime.

```bash
python3 -m venv /opt/apeir/.venv
/opt/apeir/.venv/bin/pip install /opt/apeir/source
sudo install -d -o apeir -g apeir -m 0700 /var/lib/apeir-controller
sudo install -d -o root -g apeir -m 0750 /etc/apeir-controller/tls
sudo install -m 0640 deploy/compute-mesh/controller.env.example \
  /etc/apeir-controller/controller.env
sudo install -m 0644 deploy/compute-mesh/apeir-controller.service \
  /etc/systemd/system/apeir-controller.service
```

Edit `controller.env` for the certificate paths and public port. Limit the cloud
security-group ingress rule to the known Node source addresses whenever possible.
Then initialize and start the service:

```bash
sudo -u apeir /opt/apeir/.venv/bin/apeir-controller init \
  --state-dir /var/lib/apeir-controller
sudo systemctl daemon-reload
sudo systemctl enable --now apeir-controller
sudo systemctl status apeir-controller
```

The `init` output includes the Controller public key. Distribute that public key
and the TLS CA chain to Nodes over an authenticated channel. Never copy
`identity.ed25519.pem` from the Controller.

## 2. Enroll a Node

Create a Node identity locally without connecting it:

```powershell
.\.venv\Scripts\apeir-node.exe --state-dir .local\compute-mesh-node-x64 --identity-only --json
```

Transfer only `.local/compute-mesh-node-x64/identity.json` to the Controller and
enroll it:

```bash
sudo -u apeir /opt/apeir/.venv/bin/apeir-controller trust \
  /tmp/identity.json --state-dir /var/lib/apeir-controller
```

Start a Windows x64 or ARM64 Node with
`scripts/compute-mesh/run-node-windows.ps1`. Start a Jetson or other Linux Node
with `scripts/compute-mesh/run-node-linux.sh`. Both launchers require `wss://`
for remote connections and validate the pinned Controller Ed25519 public key.
For the Jetson Orin Nano deployment procedure and ARM64-specific prerequisites,
see [Jetson Node setup](JETSON_NODE_SETUP.md).

For the durable Distribution-layer Work contract and its fail-closed state
machine, see [Distributed Work](DISTRIBUTED_WORK.md).
The complete execution and recovery path is documented in
[Distributed execution](DISTRIBUTED_EXECUTION.md),
[Work lifecycle](WORK_LIFECYCLE.md), and
[Execution recovery](EXECUTION_RECOVERY.md). The fault and replay rules are
summarized in the [recovery matrix](RECOVERY_MATRIX.md).

## 3. Inspect durable state

```bash
sudo -u apeir /opt/apeir/.venv/bin/apeir-controller status \
  --state-dir /var/lib/apeir-controller
```

The status is deliberately conservative. `connected` is true only in the live
Controller process. After a restart, the last signed heartbeat and resource
reports remain visible, but an offline Node is never presented as currently
connected. Persisted observations retain their signed protocol envelopes and
are verified against the enrolled Node key when Controller state is reopened.
The legacy `liveness` field remains available for compatible clients. The
authoritative operational projection is `connectivity_state`: an interrupted
transport becomes `DEGRADED` while its short connectivity lease remains valid,
then `STALE`, and finally `OFFLINE`. An authenticated reconnect passes through
`RECONNECTING` and `RECONCILING` before returning to `ONLINE`. Only `ONLINE` and
a lease-valid `DEGRADED` Node are eligible for placement; queued work still
requires the normal capability, policy, and Kernel authorization path.

## Security boundary

- TLS protects the transport; Ed25519 signatures authenticate protocol messages.
- Trust enrollment is explicit and out of band.
- Remote plaintext transport is allowed only on loopback.
- Artifact bytes are verified against SHA-256 before they become ready on a Node.
- Completed workload results retain the signed Node envelope.
- Unknown remote effects must not be replayed as a recovery shortcut.

## Signed result timeout diagnosis

A local wait deadline is UNKNOWN, not proof of failure or permission to execute
again. Inspect the existing Node journal, Controller signed result and provider
spool for the original operation before any recovery decision. Never subtract
absolute timestamps across hosts unless their clock error is independently known.

Main `15bc285dd46b7a088e042b35b63114be1e7d7354` Core CI run
[38069080761](https://github.com/untrod/apeir/actions/runs/38069080761) failed
on Windows in `test_external_provider_spool_reaches_signed_node_protocol`: one
failed, 4017 passed, 53 skipped. The five-second provider deadline expired. Its
execution code and test were unchanged by the workbench PR; the available failure
log does not establish where delivery stalled. This is unresolved evidence, not
a claimed recovery fix. Issues #4 and #8 remain open.

That integration test now attaches bounded stage facts on a timeout: original
operation/node IDs, host-local monotonic elapsed time, connection/report presence,
pending assignment, Node journal state, Relay state, signed result and spool-file
presence. It does not print arguments, outputs, credentials, keys or file contents.
The existing deadline, success assertions and cleanup remain unchanged. A later
passing run alone cannot explain or close the original failure.

A newer authenticated connection for the same Node supersedes the previous
transport. Application messages from the previous socket are rejected before
replay-sequence admission or observation/result updates. This does not enroll
a new key, grant Work authority, or reconcile an uncertain effect by replay.
The regression opens two actual WebSockets: the old socket is rejected; its
sequence remains usable by the current connection; Controller shutdown closes
the transports. This fixes that specific ownership bug, not every Windows
shutdown or delivery deadline issue.

## Local measurement baseline

The existing rotating Node telemetry now records authenticated connection spans
and new workload execution/persistence spans using the Node's monotonic clock.
`node.relay.authenticated` separates transport connect, signed registration, and
initial local probe/report send. The last span is not Controller receipt proof.
`node.workload.finished.payload.timing` measures execution and durable result
publication; cached delivery does not emit another execution span. Timing stays
in telemetry and does not change the signed receipt or its effect digest.

Measure the existing public CLI in distinct empty workspaces (this explicitly
approves each simulated mutation once):

```sh
python scripts/compute-mesh/measure-verified-demo.py \
  --samples 12 --output /tmp/apeir-mesh-measurement-new
```

The destination must not exist. Each sample retains original Runtime state, CLI
evidence JSON and diagnostic stderr. Failures are counted, never retried or
removed from the percentiles; UNKNOWN is not PASS. Output reports nearest-rank
p50/p95/p99 of the complete CLI, including startup and evidence serialization.
This wrapper calls the existing CLI, not a second executor or verification path.

Cloud Linux x86_64 / CPython 3.12.14 measured 12/12 COMMITTED/MATCH samples with
one effect each: p50 **1.524 s**, p95/p99 **1.669 s**. An independent 20 ms process
sampler on 12 additional fresh CLI runs measured a maximum sampled process-tree
RSS of **83,599,360 bytes**, **1 process**, and **1.60 CPU seconds**. Process count
does not measure thread/PID-cgroup consumption; sampling can miss shorter peaks.
These are local simulation baselines, not a before/after optimization claim,
production tail estimates, Windows installation or cross-network qualification.
The existing Demo's runtime-service path does not traverse the locked native
Kernel; its evidence labels that explicitly.

Queue/dispatch, Artifact transfer, independent Observation/Verification spans,
real reconnect distributions and Windows/Jetson/NAT measurements still require
additional qualification. This measurement does not close Issues #4 or #8.

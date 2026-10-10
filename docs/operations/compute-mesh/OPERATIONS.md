# Compute Mesh operations

APEIR Compute Mesh uses the existing authenticated Node Protocol. The Controller
does not grant Kernel authority. It maintains durable node trust, signed workload
results, pending controls, and a content-addressed artifact store. Nodes retain
their own Ed25519 private keys; only public `identity.json` files are enrolled.
Node and Controller startup fail closed if their private-key files cannot be
restricted to the current operating-system identity.

Identity provisioning and trust updates use the existing cross-process file
lock. Separate CLI/listener instances reload the authoritative trust map inside
the update lock; registering one Node cannot erase another registration. Repeating
the same Node ID/key is idempotent. Supplying a different key for an existing
Node ID is rejected rather than silently rotating its identity. Treat public
identity files as enrollment inputs only; registration does not grant device,
Shell or firmware permissions.

A partial Node identity or missing Controller key beside existing durable
state blocks startup without generating replacement keys or altering original
workload evidence. Restore that host's original identity from a protected
backup; do not delete journals or replace the key to make startup pass.
Concurrent initializers share one persistent identity. These are local durability
guarantees, not Controller HA or permission for two Node daemons to write the
same execution journal concurrently.

The legacy in-memory Connectivity PairingService does not enroll signed Node
Protocol identities. One-time invitation/QR onboarding and real cross-network
Windows/Jetson qualification remain separate unfinished items; the manual
public-identity enrollment procedure below remains supported.

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

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

Main `59b670c8811d11c480608a7ee17f6d17a0037422` Core CI run
[38071947425](https://github.com/untrod/apeir/actions/runs/38071947425) also failed
on Windows: `test_completed_work_is_delivered_after_transport_loss_without_reexecution`
exceeded its original five-second convergence wait (1 failed, 4031 passed,
53 skipped). The preceding four-platform source run passed; that does not explain
the later failure. Both failure records remain open qualification evidence.

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

## Execution and transport responsiveness

The Node Relay previously called its synchronous workload handler on the network
event loop. A controlled handler prevented a callback on that same loop from
running until the test watchdog released the handler. The original implementation
fails this causal ordering assertion; increasing a deadline cannot make it pass.

The Relay now awaits the same existing `NodeRuntimeService.execute_workload`
call through Python's thread offload. Work admission, authorization rechecks,
at-most-once journal, signed receipts and serial result delivery remain owned by
their existing paths. This permits transport keepalive/background callbacks while
a synchronous handler runs; it does not enable concurrent Work dispatch or process
incoming application cancellation/heartbeat messages during that serial await.
It does not establish the cause of either Windows convergence failure above.

Cancelling the transport await cannot stop an already-running handler or prove
that its effect was absent. The controlled cancellation regression keeps the
original at-most-once journal in EXECUTING, rejects another execution as
RECOVERY_REQUIRED, releases the original handler and reconnects to deliver its
persisted signed result with exactly one handler call. Process termination still
requires the existing uncertain-effect reconciliation/Observation path; a missing
response never authorizes another side effect. Thread offload does not change
sandbox limits, grant authority or qualify physical/network acceptance.

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

## One-time signed Node onboarding

The signed Controller owns enrollment in its existing `trusted-nodes.json`;
legacy Connectivity `PairingService` remains in-memory compatibility code.
Pairing never issues a Work, CapabilityGrant, credential lease or Device trust.

As the trusted local Controller OS owner, start the existing listener, then issue
an invitation with its advertised address:

```sh
apeir-controller serve --state-dir ./controller
apeir-controller pairing-create --state-dir ./controller --relay-url ws://127.0.0.1:9771
```

The default listener port is documented by `apeir-controller serve --help`; use
its actual address. Loopback `ws` is for local development only. A remote address
requires `wss`, a verified TLS certificate and the Controller public key confirmed
through a trusted channel. No route, DNS or port-forwarding changes are performed.
The returned eight-character code expires within five minutes. Do not store it in
scripts, logs, screenshots or command-line arguments. On the stopped Node:

```sh
apeir-node pair --state-dir ./node --request-id <request-id> \
  --relay-url <verified-relay-url> --server-public-key <confirmed-controller-key>
```

The CLI prompts privately for the code and signs with the existing persistent
Node key. It publishes a PENDING proof, not an executable session. Inspect the
exact Node public key and approve or deny explicitly:

```sh
apeir-controller pairing-list --state-dir ./controller
apeir-controller pairing-decide <request-id> --state-dir ./controller \
  --node-id <confirmed-node-id> --public-key <confirmed-node-public-key> --approve-once
# Replace --approve-once with --deny to refuse trust.
apeir-node pair --state-dir ./node --request-id <request-id> \
  --relay-url <verified-relay-url> --server-public-key <confirmed-controller-key> --status
apeir-node --state-dir ./node --relay-url <verified-relay-url> \
  --server-public-key <confirmed-controller-key>
```

Only one Node daemon/journal writer is supported. Run onboarding while that
daemon is stopped. After a lost pairing ACK, use `--status` on the original
request, never its spent code. Controller/Node restart preserves the proof,
identity and original decision. The five-attempt bound and atomic consumption
share the existing Controller trust-file lock; pending invitations are bounded
to 32; 1,024 retained request records are the storage ceiling, with no automatic
deletion of original decisions. Incorrect identity, replay, expired proof or invalid state fails closed.

Interactive onboarding uses concealed terminal input. Automation must use
`apeir-node pair ... --code-stdin` with redirected, bounded input; it must not put
the code in arguments, shell history or logs. This avoids Windows console-input
APIs waiting on an unavailable console when stdin is a pipe. The option rejects
terminal stdin and `--status`, and invalid input is rejected before identity
creation. Status recovery never needs a code. Python 3.10 pairing tests use the
same five-second bounds through `asyncio.wait_for`; no timeout was increased.

The first merged onboarding main run **38099724857** exposed two Python 3.10
`asyncio.timeout` compatibility failures (**4053 passed, 60 skipped**) and a
Windows concealed-pipe input timeout (**4061 passed, 53 skipped**). Multi-Arch
Windows run **38099724853** reproduced that pipe timeout (**3772 passed,
53 skipped, 272 deselected**). These are onboarding regressions, distinct from
the older unexplained signed-response/keepalive failures in Issues #4/#8. The
failure evidence is retained; corrected-source platform CI is required before
claiming the onboarding platform gate.

The Operations Workbench **Add Node** form uses the same authority. Sign in through
the configured trusted human boundary, confirm the Controller key, enter its WSS
Relay address and create an invitation. Inspect the submitted Node key in
**pairings**, then select **Trust this Node once** or **Deny**. The invitation
code is transient UI state; layout storage contains no code. Its typed human
HTTP response uses `no-store`; ordinary API serialization and logging redact it.
The remote human policy must separately allow `governance.approve` and
`control.node_pair` on the selected `controller:<key>` / `node:<id>` resource.
Node revocation additionally requires `control.revoke` on that Node. A service
bearer token, model-supplied user claim or valid Node key cannot perform these
human mutations. Existing cookie/session, Origin, permission and nonce checks
remain in place. Fake OIDC Cloud tests are not deployed IdP qualification.

```sh
apeir-controller revoke-node <node-id> --state-dir ./controller
```

Revocation retains the original identity and evidence. Existing sessions are
closed by trust monitoring; inbound messages and new dispatch recheck current
trust. Ordinary registration, restart and pairing cannot revive a revoked Node.
Already admitted effects may finish: revocation is not proof of interruption and
requires original journal reconciliation/independent observation. Explicit
revoked-identity restoration is not exposed in this slice.

Human decisions are recorded before trust persistence in the existing Governance
trail, with actor/session/context, request, exact public keys and proof digest.
`trust_persistence_confirmed=false` denotes decision/admission evidence, not a
claim that the separate file write succeeded. The canonical trust record confirms
application. Audit failure blocks publication; a file-write failure leaves the
original PENDING proof, which can be inspected before another human decision.
Trust administration uses an empty Work binding and issues no execution grant.

The exercised acceptance scope is signed Cloud loopback, real Node CLI processes,
Controller reload, concurrent decision processes and fake human HTTP sessions.
Windows native UI, Jetson, WAN/CGNAT/proxy networks, real IdP and physical Device
acceptance remain separate PENDING/BLOCKED gates. Issues #4/#8 remain open.

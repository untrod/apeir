# Execution recovery

APEIR recovers from durable facts rather than replaying remote work.

## Node restart

The Node persists an at-most-once workload as `EXECUTING` before invoking its
handler. If it restarts before persisting a terminal result, the same request
returns `RECOVERY_REQUIRED`. Controller reconciliation records the Work as
`UNKNOWN`; it does not issue `WORKLOAD_START` again.

Completed Node workloads are idempotent. Redelivery of the exact same binding
returns the existing result. A changed binding under the same workload id is
rejected.

## Controller restart

The Controller persists trust, observations, pending assignments, signed
results, Work state, and CAS indexes. After restart it can:

- recreate a missing provider-spool file from an immutable dispatch record;
- verify and consume a result received before the restart;
- continue from `SUCCEEDED` when Artifact commit was interrupted;
- continue from `VERIFIED` by rechecking CAS and committing;
- return the existing result for repeated reconciliation.

Reality simulation Work adds an independent observation gate. Reconciliation
leaves it `VERIFIED` until `EffectVerifier` returns `MATCH`. Resuming its
Workflow performs a fresh read-only observation Work rather than repeating the
device mutation. Previous verdicts and observations remain in CAS. If the
MATCH was persisted but commit was interrupted, recovery checks the existing
signed result and CAS evidence before committing that MATCH.

The simulator can apply an effect, persist its state and the Node terminal
OperationReceipt, then drop the transport response. On reconnect the existing
at-most-once Node path returns the persisted result without invoking the handler
again. A fresh Observation must still match before commit. If terminal Node
persistence was also interrupted, the existing `EXECUTING` journal yields
`RECOVERY_REQUIRED`; observation alone cannot replace the missing receipt.

Temporary state files have unique names, writes are serialized with the project
file lock, and final replacement is atomic. Windows sharing violations receive
a small bounded retry; exhaustion remains a hard failure.

## Dispatch and reconnect ordering

The focused recovery audit classified canonical ownership as follows:

| Existing mechanism | Action | Scope |
| --- | --- | --- |
| DistributedWorkStore, signed assignments/results and existing file lock | REUSE | Durable identity, state transitions and immutable binding remain authoritative. |
| Node at-most-once execution journal, receipt and independent EffectVerification | REUSE | Reconnect returns persisted evidence; mutation is not executed again. |
| Relay staging and provider spool | EXTEND | Persist before publication; distinguish an admitted started dispatch from new execution. |
| Deterministic ACK/spool-consumption interleavings | MISSING → EXTEND | Add to existing Node and simulated Reality tests, alongside natural ordering and fail-closed cases. |
| Physical response-loss/power-loss evidence | MISSING | Hardware acceptance remains PENDING. |

The canonical Work store is authoritative; a Workflow's earlier ASSIGNED
snapshot may already be stale when a signed Node ACK arrives. Staging an exact
previously recorded dispatch after Work advances to RUNNING, SUCCEEDED, VERIFIED
or COMMITTED validates the immutable request binding and returns existing
evidence only. It never recreates a missing spool file for those states, never
creates a new assignment and never treats staging as effect verification.
Unrecorded RUNNING Work and FAILED, UNKNOWN or RECOVERING Work remain ineligible
for staging. A changed request or assignment binding fails closed.
Spool disappearance during a read is handled as consumed transport staging;
malformed or changed content still fails closed. A spool file is not a receipt.

For initial dispatch the Controller persists the dispatch binding before
publishing its spool file. A publication failure can recreate that exact file
while the Work remains ASSIGNED. This closes the ACK-before-record race without
weakening the Node's existing at-most-once journal or authorization boundary.

Issue [#4](https://github.com/untrod/apeir/issues/4) was reproduced on the unchanged
main baseline by deferring the target ACK transition until immediately before
staging's canonical read. Both response-loss cases failed deterministically:
effect-before-response-loss and response-loss-before-effect. The same forced
ordering is now part of the existing simulated Reality regression, alongside
natural ordering. Software tests establish this dispatch race and its repair;
they do not establish physical recovery or prove the absence of other timing
defects. Keep the issue open until its independent CI acceptance is complete.

Local validation of this focused repair from Distribution `d9c642d`:

- affected M3.1–M4 suites: **618 passed**, including the real OCI reference;
- final ten rounds of natural/forced response-loss ordering: **40 passed**;
- repository contracts: **246 passed**, including component-lock contracts;
- full regression: **3683 passed, 35 skipped, 9 failed**, four warnings. All nine
  failures match recorded managed-Cloud MCP interpreter, read-only HOME,
  persistence and orphan-process baselines; none was hidden or skipped;
- Ruff, changed-file formatting, compile, documentation/link, comment, identity,
  metadata, security and version checks passed; security reported zero findings;
- actual native hash verifier ran and was **BLOCKED** by the missing locked
  `nousd-x86_64-pc-windows-msvc.exe`. Kernel and component lock are unchanged.

Preserved diagnostic evidence includes two forced ACK failures on unchanged
main and an intermediate repair's stress result of **11 passed, 1 failed**.
That remaining failure reported `staged Work dispatch binding changed`, leading
to the explicit spool-consumption interleaving test and strict missing-file
handling. The final 40-pass stress result applies only to the corrected version.
Hosted CI results and merge SHA belong to the independent PR acceptance record;
these local counts are not claims that hosted or physical acceptance completed.

## Duplicate and invalid results

A repeated signed result is idempotent only when its Work, assignment, Node,
state, and envelope digest match the recorded summary. A different Node,
request binding, signature, receipt, or Artifact digest fails closed.

## Operator rule

Never delete `UNKNOWN` or edit it back to `ASSIGNED` as a retry shortcut. First
reconcile the Node journal and physical effect. If the outcome remains unknown,
create an explicit recovery decision with a new operation identity.

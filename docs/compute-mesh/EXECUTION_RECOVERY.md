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

Temporary state files have unique names, writes are serialized with the project
file lock, and final replacement is atomic. Windows sharing violations receive
a small bounded retry; exhaustion remains a hard failure.

## Duplicate and invalid results

A repeated signed result is idempotent only when its Work, assignment, Node,
state, and envelope digest match the recorded summary. A different Node,
request binding, signature, receipt, or Artifact digest fails closed.

## Operator rule

Never delete `UNKNOWN` or edit it back to `ASSIGNED` as a retry shortcut. First
reconcile the Node journal and physical effect. If the outcome remains unknown,
create an explicit recovery decision with a new operation identity.

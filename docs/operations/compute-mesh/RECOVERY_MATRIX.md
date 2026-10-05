# Compute Mesh recovery matrix

APEIR treats transport availability, durable execution state, and verified
effects as separate facts. A reconnect does not grant authority and a recent
heartbeat does not prove that an effect completed.

| Failure | Durable fact | Recovery behavior | Replay rule |
| --- | --- | --- | --- |
| Node transport drops before assignment delivery | Controller retains the pending assignment | Redeliver the same signed assignment after authentication | Allowed; no execution was acknowledged |
| Transport drops after execution finishes but before the result arrives | Node retains the terminal workload result; Controller retains the pending assignment | Redelivery returns the stored result and the Controller verifies it | Handler is not executed again |
| Node restarts while an at-most-once effect is `EXECUTING` | Node journal contains a non-terminal execution marker | Return `RECOVERY_REQUIRED`; Controller records `UNKNOWN` | Forbidden |
| Controller restarts before reconciliation | Pending assignment, signed result, Work state, and CAS are durable | Reload state and resume verification/commit | Existing result is consumed, not replayed |
| A result is submitted twice | First signed envelope and result binding are durable | Return the existing reconciliation result | Idempotent only for an identical binding |
| Signature, Node identity, receipt, or Artifact digest changes | Verification fails | Reject and retain the prior durable state | Forbidden |
| Heartbeats stop | Last signed observation remains durable | `DEGRADED`, then `STALE`, then `OFFLINE` as the connectivity lease expires | No effect inference |
| Node reconnects | Live authenticated transport plus reports | `RECONNECTING` → `RECONCILING` → `ONLINE` | Pending facts are reconciled before new placement |

## Connectivity states

- `ONLINE`: authenticated transport is live and heartbeat, resource, and device
  observations have converged.
- `DEGRADED`: transport is absent, but the short connectivity lease derived from
  signed observations has not expired. Work may be queued; it is not claimed to
  be running.
- `STALE`: the lease expired and the observation remains within the bounded
  diagnostic window. The Node is not eligible for placement.
- `OFFLINE`: there is no usable recent observation.
- `RECONNECTING` and `RECONCILING`: the transport is authenticated, but current
  observations or pending facts have not converged. The Node is not yet eligible
  for placement.

The connectivity lease is a scheduling freshness mechanism only. It is not a
Kernel Permit and does not replace resource leases.

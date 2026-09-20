# Task Delivery Specification v1.0

> Status: Draft — Phase 0.5
> Task lifecycle, state machine, idempotency, persistence

---

## 1. Task State Machine

```
  ┌──────────┐
  │  QUEUED   │  Task submitted, waiting for compatible node
  └─────┬─────┘
        │ node online + capability match
  ┌─────▼─────┐
  │ DELIVERED  │  Task sent to node, waiting for ACK
  └─────┬─────┘
        │ ACK received (accepted=true)
  ┌─────▼─────┐
  │ ACCEPTED   │  Node accepted, preparing execution
  └─────┬─────┘
        │ execution started
  ┌─────▼─────┐
  │  RUNNING   │  Task executing on node
  └──┬───┬────┘
     │   │
     ▼   ▼
  ┌──────┐ ┌──────┐
  │COMPLETED│ │FAILED│  Terminal states
  └──────┘ └──────┘
```

### 1.1 State Definitions

| State | Description | Entry Condition | Exit Condition |
|---|---|---|---|
| QUEUED | Waiting for node assignment | Task submitted | Node online + capability match -> DELIVERED |
| DELIVERED | Sent to node, awaiting ACK | Assignment sent | ACK accepted -> ACCEPTED; ACK rejected/timeout -> QUEUED; deadline passed -> FAILED |
| ACCEPTED | Node accepted task | ACK received | Execution started -> RUNNING; deadline passed -> FAILED |
| RUNNING | Task executing | Node reports start | Completion -> COMPLETED; error -> FAILED; cancellation -> FAILED (reason=cancelled) |
| COMPLETED | Task finished successfully | Result received | Terminal |
| FAILED | Task failed | Error, timeout, rejection, cancellation, crash | Terminal |

### 1.2 Transitions

| From | To | Trigger | Side Effects |
|---|---|---|---|
| QUEUED | DELIVERED | Compatible node online | Task assigned to node, sequence number incremented |
| DELIVERED | ACCEPTED | Node sends TASK_ACK {accepted:true} | ACK timeout cleared |
| DELIVERED | QUEUED | ACK timeout (30s) or TASK_ACK {accepted:false} | Task returned to queue, retry count incremented |
| DELIVERED | FAILED | Deadline passed | Expired, not retried |
| ACCEPTED | RUNNING | Node sends TASK_EVENT {event_type:"started"} | Execution timer started |
| ACCEPTED | FAILED | Deadline passed | Expired, cancellation sent to node |
| RUNNING | COMPLETED | Node sends TASK_RESULT {status:"completed"} | Result stored, artifacts linked, outcome recorded |
| RUNNING | FAILED | Node sends TASK_RESULT {status:"failed"} | Error stored, outcome recorded, retry evaluated |
| RUNNING | FAILED | Cancellation requested | Cancellation sent to node, process terminated |
| ANY | FAILED | Process crash (non-idempotent task) | Marked "crash_recovery", not auto-retried |

---

## 2. Task Schema

### 2.1 TaskSubmission

```json
{
  "task_id": "task_20260713_a1b2c3d4",
  "capability_id": "system.echo",
  "params": {"message": "hello"},
  "target_node": "node_laptop_01",
  "idempotency_key": "idem_20260713_e5f6g7h8",
  "deadline": "2026-07-13T10:05:00Z",
  "risk_level": "low",
  "max_retries": 0,
  "budget": {
    "max_cost": 0,
    "max_tokens": 0,
    "max_time_ms": 5000
  }
}
```

### 2.2 TaskResult

```json
{
  "task_id": "task_20260713_a1b2c3d4",
  "status": "completed",
  "result": {"echo": "hello"},
  "error": null,
  "artifacts": [],
  "events": [
    {"event_type": "started", "timestamp": "..."},
    {"event_type": "completed", "timestamp": "..."}
  ],
  "duration_ms": 42,
  "node_id": "node_laptop_01",
  "completed_at": "2026-07-13T10:01:00Z"
}
```

---

## 3. Idempotency Protection

### 3.1 Idempotency Key

- Every TASK_SUBMISSION must include an `idempotency_key`
- Format: `idem_{YYYYMMDD}_{8hex}`
- Server stores mapping: `idempotency_key -> task_id -> result`
- Duplicate submission with same key returns original task status (not re-executed)

### 3.2 Idempotency Window

- Keys retained for 24 hours after task reaches terminal state
- After retention: key may be reused (but task won't be re-executed — key collision rejected if original task still in retention)
- Idempotency key deduplication checked at QUEUED state (before delivery)

### 3.3 Non-Idempotent Tasks

- Non-idempotent tasks marked with `idempotent: false` in capability declaration
- On reconnect: if non-idempotent task was in RUNNING state, marked FAILED with reason "crash_recovery"
- Cannot be auto-resumed or auto-retried
- User must explicitly re-submit with new idempotency_key

---

## 4. Acknowledgement

### 4.1 ACK Protocol

1. Control Plane sends TASK_ASSIGNMENT to node
2. Node must respond with TASK_ACK within ACK timeout (default 30s)
3. If `accepted: true` -> task moves to ACCEPTED
4. If `accepted: false` -> task returns to QUEUED (with reject_reason)
5. If timeout -> task returns to QUEUED, retry count incremented

### 4.2 ACK Timeout

- Default: 30 seconds
- Configurable per node type (cloud: 15s, personal: 30s)
- On timeout: task returned to QUEUED
- Node that failed to ACK may receive the task again on next delivery attempt

---

## 5. Sequence Numbers

- Monotonically increasing per session
- Included in TASK_ASSIGNMENT
- Node verifies: received sequence_number == expected sequence_number
- Gap detected -> node requests replay of missing messages
- Server replays messages from gap point

---

## 6. Persistence

### 6.1 What Is Persisted

| Data | Storage | Survives Restart |
|---|---|---|
| Task state | SQLite (extends jobs table) | Yes |
| Task queue | SQLite | Yes |
| Sequence numbers | SQLite (per session) | Yes |
| Idempotency keys | SQLite | Yes (24h retention) |
| Task events | SQLite (extends events table) | Yes |
| Task results | SQLite + filesystem (artifacts) | Yes |
| ACK state | SQLite | Yes |

### 6.2 Recovery on Control Plane Restart

1. Load all non-terminal tasks from SQLite
2. For tasks in QUEUED: ready for delivery
3. For tasks in DELIVERED: re-send assignment (idempotency key prevents double-execution if node already executed)
4. For tasks in ACCEPTED/RUNNING: 
   - If node reconnects with session resume -> request status
   - If node doesn't reconnect within grace period -> mark FAILED (crash_recovery for non-idempotent)
5. For COMPLETED/FAILED: no action

---

## 7. Retry Policy

### 7.1 Automatic Retries

- Configured per task (`max_retries` field, default 0)
- Retried on: DELIVERED->QUEUED (ACK timeout), ACCEPTED->FAILED (execution error, if idempotent)
- Not retried on: FAILED due to deadline, FAILED due to cancellation, FAILED due to crash_recovery (non-idempotent)

### 7.2 Retry Backoff

- Exponential: delay = min(2^retry_count * 1000, 60000) ms
- Jitter: ±25%
- Max total retry time: bounded by task deadline

---

## 8. Cancellation

1. User or system requests cancellation: `nous task cancel <id>`
2. If task in QUEUED -> immediate FAILED (reason=cancelled)
3. If task in DELIVERED/ACCEPTED -> TASK_CANCELLATION sent to node
4. If task in RUNNING -> TASK_CANCELLATION sent, process-tree terminated on node
5. Node confirms with TASK_RESULT {status:"failed", error:"cancelled"}
6. Cancellation is terminal — cancelled tasks cannot be retried

---

## 9. Deadlines

- Every task has an optional `deadline` field
- Checked at every state transition
- If deadline has passed:
  - QUEUED/DELIVERED -> FAILED (reason=expired)
  - ACCEPTED/RUNNING -> TASK_CANCELLATION sent, then FAILED (reason=expired)
- Deadline is UTC ISO-8601

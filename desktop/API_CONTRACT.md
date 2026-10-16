# Nous Runtime — API Contract & Runtime Event Catalog

**Version:** 1.0.0
**Schema Version:** 1.0.0
**Date:** 2026-07-28

---

## 1. API Endpoints

All endpoints are served from the Nous Runtime HTTP server (default `http://localhost:8770`).
Auth: Bearer token via `Authorization` header. Public: `/api/v1/health`, `/api/v1/version`.

### 1.1 Core v1 (`/api/v1/`)

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| GET | `/health` | — | `{ ok: true, version: string }` | Public |
| GET | `/version` | — | `{ version: string }` | Public |
| GET | `/status` | — | `RuntimeStatus` | |
| GET | `/capabilities` | — | `{ capabilities: Capability[] }` | |
| POST | `/capabilities/run` | `{ capability_id, params }` | `{ result, trace_id }` | |
| GET | `/providers` | — | `{ providers: Provider[] }` | |
| GET | `/providers/health` | — | `{ healthy: number, total: number }` | |
| GET | `/packs` | — | `{ packs: Pack[] }` | |
| POST | `/packs/install` | `{ path }` | `Pack` | |
| DELETE | `/packs/{name}` | — | `{ ok: true }` | |
| GET | `/jobs` | — | `{ jobs: Job[] }` | |
| GET | `/jobs/{id}` | — | `Job` | |
| GET | `/traces` | — | `{ traces: Trace[] }` | |
| GET | `/traces/{id}` | — | `ExecutionTrace` | |
| GET | `/traces/{id}/timeline` | — | `{ spans: TraceSpan[] }` | |
| GET | `/events/stream` | `?domain=&since_event_id=&limit=` | `{ events: RuntimeEventEnvelope[], latest_event_id }` | Polling-based |
| GET | `/nodes` | `?status=` | `Node[]` | |
| GET | `/nodes/{id}` | — | `Node` | |
| POST | `/nodes/scan` | — | `{ nodes_found, nodes_online }` | |
| GET | `/artifacts` | — | `{ artifacts: Artifact[] }` | |
| GET | `/artifacts/{id}` | — | `Artifact` | |
| POST | `/approvals/{request_id}/{action}` | — | `{ ok: true }` | action = `approve` \| `deny` |
| GET | `/models/observations` | `?model_id=&provider_id=&capability_id=&limit=` | `{ observations, count, statistics }` | |
| GET | `/models/rankings` | `?capability_id=&task_type=` | `{ rankings: ModelRanking[] }` | |
| GET | `/experience/stats` | — | `{ total, by_category }` | |

### 1.2 Runtime (`/api/runtime/`)

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| POST | `/run` | `{ user_input, model_id? }` | `{ message, result: { content }, trace_id }` | Chat execution |
| GET | `/dashboard` | — | `DashboardData` | |
| GET | `/sessions` | — | `{ sessions: Session[] }` | |
| GET | `/runs` | `?limit=` | `{ runs: Run[] }` | |
| GET | `/runs/{id}/events` | `?after_sequence=&limit=` | `{ events, next_after_sequence }` | |
| GET | `/memory` | — | `{ used_pct, rss_mb, total_gb }` | |

### 1.3 Desktop UI (`/api/`)

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/tasks` | `?state=&limit=` | `{ tasks: TaskView[], total, running }` |
| POST | `/tasks/action` | `{ action, task_id }` | `{ ok: true }` |
| GET | `/devices` | — | `{ devices, total, online, liveness_status, source }` |
| POST | `/devices/scan` | absent or `{}` | `{ discovered: [], timestamp, status: "UNAVAILABLE", scan_performed: false, reason }` |
| GET | `/automations` | — | `{ automations, total }` |
| POST | `/automations/add` | Legacy `{ name, trigger, schedule?, action }`; explicit simulation `{ adapter: "simulated-reality", name, trigger: "manual"\|"schedule", due_at?, firmware_version? }` | Legacy UNQUALIFIED config or immutable simulated Workflow binding |
| POST | `/automations/action` | `{ action, automation_id?, trigger_key?, run_id?, limit? }` | Actual original Workflow/Work state; `run_due` returns bounded runs |
| GET | `/automations/{automation_id}/history` | `?limit=` | Original trigger/run, Work, receipt/observation/verification and verified CAS evidence |
| GET | `/knowledge` | `?category=` | `{ items, total }` |
| POST | `/knowledge/add` | `{ title, category, content }` | `KnowledgeItem` |
| GET | `/security/permissions` | — | `{ permissions }` |
| GET | `/control/approvals` | — | `{ approvals }` |
| GET | `/logs` | `?level=&limit=` | `{ lines, level, total }` |
| GET | `/models` | — | `{ models: ModelView[], summary }` |
| POST | `/models/action` | `{ action, model_id, provider_id?, api_key? }` | varies |
| GET | `/workspace` | — | `WorkspaceEntry` |
| GET | `/health/dashboard` | — | `HealthDashboard` |
| GET | `/service/status` | — | `ServiceStatus` |

The qualified Automation actions are `trigger`, `run_due` (1–10 one-shot due
proposals), `resume`, `reconcile`, `cancel`, `enable` and `disable`. Execution
is explicitly simulated; `enabled` grants no authority. A new firmware Work
pauses for separate trusted human approval. Repeated trigger keys only project
the original run; `resume` never accepts changed inputs or approval hints.
`reconcile` observes original effects without entering a mutation handler.
Management uses the existing live human session/nonce boundary and
`control.automation.manage`; listing and bound history use
`control.automation.read`. HTTP admission applies to empty, legacy-only and
mixed stores alike. Legacy direct local configuration remains compatible and
UNQUALIFIED; it cannot execute or seed approval.
The existing Governance human boundary also checks `governance.approve` for
the workspace. No background timer or recurring Cron is implemented.

The Operations Automation pane is a consumer of this API, including structured
creation, explicit trigger/due polling, original history, approval, reconciliation
and cancellation. It binds each mutation to the captured current Controller
configuration epoch and human session. A lost response retains the original key
and uses history; it never reports success from a local button state. Legacy
configuration remains visible as UNQUALIFIED without execution controls.

Device compatibility views use the same configured Reality DeviceRegistry as
Operations, preserving stable identity, lifecycle, Node association and simulation
metadata. Nodes and the local host are not manufactured as Devices. Persisted
AVAILABLE/TRUSTED state is not a fresh liveness observation: `online` counts zero
confirmed online records and `liveness_status` remains UNKNOWN, not proof that
every device is offline. Corrupt/unavailable state returns an explicit UNKNOWN
error. Discovery is currently UNAVAILABLE: the scan route performs no network
probe, pairing or trust change and refuses nonempty request bodies. Use existing
explicit Node pairing and qualified managed Device providers.

### 1.4 Inspector (`/api/inspector/`)

| Method | Path | Response |
|--------|------|----------|
| GET | `/runtime` | Runtime snapshot |
| GET | `/capabilities` | Capability status |
| GET | `/tasks` | Task inspector data |
| GET | `/observations` | Observation data |
| GET | `/memory` | Memory details |
| GET | `/diagnostics` | Diagnostic report |
| GET | `/decisions` | Decision log |
| GET | `/outcomes` | Outcome log |
| GET | `/consistency` | Consistency report |
| GET | `/providers/reliability` | Provider reliability |

### 1.5 Phase Runtime APIs (`/api/`)

**Context Runtime:**
| Method | Path | Notes |
|--------|------|-------|
| GET | `/context/current` | Active context snapshot |
| GET | `/context/history` | Context history |
| GET | `/context/explain` | Context explanation |
| GET | `/context/timeline` | Context timeline |
| POST | `/context/snapshot` | Create snapshot |
| POST | `/context/restore` | Restore snapshot |

**Evaluation Runtime:**
| Method | Path | Notes |
|--------|------|-------|
| GET | `/evaluation/current` | Current evaluation |
| GET | `/evaluation/history` | Evaluation history |
| GET | `/evaluation/report` | Evaluation report |
| POST | `/evaluation/run` | Run evaluation |

**Experience Runtime:**
| Method | Path | Notes |
|--------|------|-------|
| GET | `/experience/list` | Experience list |
| GET | `/experience/search` | Search experiences |
| GET | `/experience/recommend` | Recommendations |
| GET | `/experience/stats` | Statistics |

### 1.6 Other

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/chat` | Chat Runtime |
| POST | `/api/ide/runtime` | IDE Runtime |
| POST | `/api/workflow/run` | Workflow execution |
| POST | `/api/model/select` | Model selection |
| GET | `/api/tasks/timeline` | Task timeline |
| GET | `/api/tasks/graph` | Task DAG |
| GET | `/api/tasks/{id}/artifacts` | Task artifacts |
| GET | `/api/tasks/{id}/verification` | Task verification |

---

## 2. Runtime Event Catalog

All events follow the `<domain>.<action>` convention. Each event carries:
```json
{
  "event_id": "uuid",
  "sequence": 123,
  "event_type": "task.created",
  "domain": "task",
  "source": "runtime",
  "timestamp": "2026-07-28T00:00:00Z",
  "payload": {},
  "metadata": {},
  "dedup_key": "task.created:task-uuid"
}
```

### 2.1 Task Events

| Event Type | Payload | Description |
|------------|---------|-------------|
| `task.created` | `{ task_id, name, priority }` | Task created |
| `task.queued` | `{ task_id }` | Task enqueued for execution |
| `task.planning` | `{ task_id, plan_id }` | Task is being planned |
| `task.awaiting_approval` | `{ task_id, capability_id, risk_level }` | Task requires approval |
| `task.dispatching` | `{ task_id, node_id? }` | Task dispatched to node |
| `task.running` | `{ task_id, model_id?, node_id? }` | Task executing |
| `task.waiting_for_model` | `{ task_id, model_id }` | Waiting for model availability |
| `task.waiting_for_node` | `{ task_id, node_id }` | Waiting for node |
| `task.paused` | `{ task_id, reason }` | Task paused |
| `task.recovering` | `{ task_id, attempt }` | Task recovery in progress |
| `task.verifying` | `{ task_id }` | Verification phase |
| `task.completed` | `{ task_id, result_summary, duration_ms }` | Task completed successfully |
| `task.completed_with_warnings` | `{ task_id, warnings[] }` | Completed with warnings |
| `task.failed` | `{ task_id, error, recoverable }` | Task failed |
| `task.failed_verification` | `{ task_id, evidence }` | Verification failed |
| `task.cancelled` | `{ task_id, reason }` | Task cancelled |
| `task.step.started` | `{ task_id, step_id, step_name }` | Step started |
| `task.step.completed` | `{ task_id, step_id }` | Step completed |
| `task.step.failed` | `{ task_id, step_id, error }` | Step failed |

### 2.2 Model Events

| Event Type | Payload |
|------------|---------|
| `model.invoked` | `{ model_id, provider_id, capability_id }` |
| `model.invoked.{operation}` | `{ model_id, operation }` |
| `model.streaming` | `{ model_id, token_count }` |
| `model.completed` | `{ model_id, tokens_in, tokens_out, latency_ms }` |
| `model.completed.{operation}` | `{ model_id, operation }` |
| `model.failed` | `{ model_id, error, retry_count }` |
| `model.retry` | `{ model_id, attempt, reason }` |
| `model.fallback` | `{ from_model_id, to_model_id, reason }` |
| `model.token_usage` | `{ model_id, tokens_in, tokens_out, cost_usd }` |

### 2.3 Capability Events

| Event Type | Payload |
|------------|---------|
| `capability.requested` | `{ capability_id, params }` |
| `capability.resolved` | `{ capability_id, provider_id }` |
| `capability.admitted` | `{ capability_id }` |
| `capability.denied` | `{ capability_id, reason }` |
| `capability.approved` | `{ capability_id, approved_by }` |
| `capability.started` | `{ capability_id, task_id }` |
| `capability.completed` | `{ capability_id, result }` |
| `capability.failed` | `{ capability_id, error }` |
| `capability.timeout` | `{ capability_id, timeout_ms }` |

### 2.4 Node Events

| Event Type | Payload |
|------------|---------|
| `node.registered` | `{ node_id, platform, arch }` |
| `node.online` | `{ node_id }` |
| `node.offline` | `{ node_id }` |
| `node.heartbeat` | `{ node_id, latency_ms }` |
| `node.heartbeat_lost` | `{ node_id }` |
| `node.revoked` | `{ node_id }` |
| `node.paired` | `{ node_id }` |
| `node.unpaired` | `{ node_id }` |
| `node.reconnected` | `{ node_id, downtime_ms }` |
| `node.session_expired` | `{ node_id }` |

### 2.5 Approval Events

| Event Type | Payload |
|------------|---------|
| `approval.requested` | `{ request_id, capability_id, task_id, risk_level, reason }` |
| `approval.granted` | `{ request_id, granted_by }` |
| `approval.denied` | `{ request_id, denied_by, reason }` |
| `approval.expired` | `{ request_id }` |
| `approval.superseded` | `{ request_id, superseded_by }` |
| `approval.escalated` | `{ request_id, escalated_to }` |

### 2.6 Session Events

| Event Type | Payload |
|------------|---------|
| `session.created` | `{ session_id, context_snapshot_id }` |
| `session.resumed` | `{ session_id }` |
| `session.expired` | `{ session_id }` |
| `session.closed` | `{ session_id }` |
| `session.message.received` | `{ session_id, message_id }` |
| `session.reply.sent` | `{ session_id, message_id }` |

### 2.7 Plan Events

| Event Type | Payload |
|------------|---------|
| `plan.created` | `{ plan_id, title, stage_count }` |
| `plan.updated` | `{ plan_id, stages[] }` |
| `plan.completed` | `{ plan_id, duration_ms }` |
| `plan.failed` | `{ plan_id, error }` |

### 2.8 Artifact Events

| Event Type | Payload |
|------------|---------|
| `artifact.created` | `{ artifact_id, task_id, kind, name, size_bytes, content_hash }` |
| `artifact.updated` | `{ artifact_id, version }` |
| `artifact.deleted` | `{ artifact_id }` |

### 2.9 Verification Events

| Event Type | Payload |
|------------|---------|
| `verification.started` | `{ capability_id, task_id }` |
| `verification.passed` | `{ capability_id, evidence }` |
| `verification.failed` | `{ capability_id, evidence, failures[] }` |
| `verification.repaired` | `{ capability_id, repaired_by }` |

### 2.10 Sandbox Events

| Event Type | Payload |
|------------|---------|
| `sandbox.validated` | `{ task_id, boundary }` |
| `sandbox.rejected` | `{ task_id, reason }` |
| `sandbox.limit_hit` | `{ task_id, limit_type, current, max }` |

### 2.11 Evidence Events

| Event Type | Payload |
|------------|---------|
| `evidence.recorded` | `{ evidence_id, task_id, kind, content_hash, signature }` |
| `evidence.profile_updated` | `{ model_id, profile }` |

### 2.12 Run Events

| Event Type | Payload |
|------------|---------|
| `run.created` | `{ run_id, session_id }` |
| `run.started` | `{ run_id, user_input }` |
| `run.completed` | `{ run_id, trace_id, duration_ms }` |
| `run.failed` | `{ run_id, error }` |
| `run.cancelled` | `{ run_id }` |

### 2.13 Error Events

| Event Type | Payload |
|------------|---------|
| `error.occurred` | `{ error_id, domain, code, message }` |
| `error.recovered` | `{ error_id, recovery_action }` |

### 2.14 System Events

| Event Type | Payload |
|------------|---------|
| `system.startup` | `{ version, node_id }` |
| `system.shutdown` | `{ reason }` |
| `system.health_check` | `{ healthy, checks[] }` |

---

## 3. Entity Schemas

### 3.1 Entity Base
```typescript
interface EntityBase {
  id: string;
  schema_version: string;
  created_at: string;  // ISO 8601
  updated_at: string;  // ISO 8601
}
```

### 3.2 Key Entities
- **Conversation**: `{ id, title, session_id, model_id?, message_count, last_message_at, pinned, archived }`
- **Session**: `{ id, status, context_snapshot_id?, token_count, message_count }`
- **Message**: `{ id, conversation_id, session_id, role, content, model_id?, trace_id?, tokens_used?, cards[] }`
- **Task**: `{ id, name, status, priority, model_id?, node_id?, capability_id?, plan_id?, trace_id?, steps[], progress_pct, duration_ms?, error?, result_summary?, cancellation_requested, recoverable }`
- **Plan**: `{ id, conversation_id?, title, status, stages[], estimated_duration_ms? }`
- **Approval**: `{ id, request_id, capability_id, task_id?, status, requester, risk_level, reason, resolved_at?, resolved_by? }`
- **Artifact**: `{ id, task_id?, name, kind, mime_type, size_bytes, content_hash, url, preview_url?, version, verified }`
- **Verification**: `{ id, task_id?, capability_id, status, stages[], evidence, repaired_by? }`
- **Node**: `{ id, node_id, name, role, platform, arch, online, status, trust_status, connectivity_state, last_seen, capabilities[], active_task_count, total_task_count, network_latency_ms?, version, paired_at }`
- **Model**: `{ id, display_name, provider_id, provider_kind, state, health, capabilities[], probes[], calibration?, cost_per_1k_tokens_usd, avg_latency_ms, token_limit, recoverable }`
- **Evidence**: `{ id, task_id, verification_id?, kind, content_hash, signature, attested_by, chain_index }`
- **UsageRecord**: `{ id, model_id, task_id?, conversation_id?, tokens_in, tokens_out, cost_usd, period_start, period_end }`

---

## 4. Reconnect & Dedup Protocol

### Sequence Numbers
- Each domain maintains a monotonically increasing `sequence` number.
- The client tracks `cursors[domain]` — the last seen sequence per domain.
- On reconnect, client sends `since_event_id={cursor}` and receives missed events.

### Dedup
- Each event has a `dedup_key` (typically `{event_type}:{entity_id}`).
- EntityStore skips events where `sequence <= cursors[domain]`.
- Server guarantees idempotent delivery for a given sequence.

### Backfill
- On reconnect, client calls `GET /api/v1/events/stream?domain=X&since_event_id={cursor}&limit=200`.
- Loops until `events.length < limit` (all caught up).
- Merges into EntityStore with `updated_at` conflict resolution.

---

## 5. Engineering Constraints

1. **No frontend → Model Provider direct calls.** All model access goes through Runtime API.
2. **No fake Task success.** Task status only changes via Runtime Events from backend.
3. **Approval gates execution.** UI buttons call approval API; backend enforces the gate.
4. **Secrets never in frontend Store/logs/cache.** Use the existing Credential Governance boundary; do not infer production encrypted-storage or identity qualification from a software reference.
5. **No parallel frontend state machine.** EntityStore mirrors backend; never originates state.
6. **Backend compatibility.** Preserve valid contracts; document security corrections that reject unsafe or misleading previous behavior.


### Registered Node compatibility views

`GET /api/v1/nodes` and its detail route project the active OperationsPlane's
signed Node Relay Controller, including exact Node/public-key identity, trust,
connection and resource-report facts. They do not consult the early Connectivity
SQL registry/session cache. Legacy Connectivity classes and control endpoints
remain compatibility-only; they neither establish nor alter signed Relay trust.
Use Operations Add Node/one-time invitation and its governed revoke action for
current Nodes. No list, detail or query provisions an identity or grants execution.

`POST /api/v1/nodes/scan` is retained as a compatibility name for a registered-node
query. Bodyless or empty-object requests return counts, `scan_performed=false`
and `source=node_runtime.controller-status`. No LAN scan, port probe, discovery,
trust registration or router/DNS change occurs. Nonempty targets are refused;
unprovisioned/corrupt Controller facts return UNKNOWN errors, never legacy or
fabricated online fallback. First launch calls this a registered-node check.

The Desktop maps raw string capability declarations into existing entity records;
their availability remains unknown, not permission. Unobserved roles, versions,
pairing times and counters remain unknown/empty/null. Its conservative `online`
alias means trusted, connected, lease-valid ONLINE with fresh current resource
facts; the legacy page counts these as **ready**, while displaying connection
and trust separately. Current REST facts override cached event times; activity
alone cannot promote readiness or revive REVOKED trust. Persisted Node cache is
historical and restores no current online claim. In-flight reads check the current
Controller URL and configuration generation before publication. This does not
qualify real WAN/Windows/Jetson, native UI or all legacy multi-Controller caches.


The existing legacy Nodes page distinguishes loading, backend UNKNOWN/unavailable,
and an actually empty successful directory, with explicit read retry. A connection
configuration change hides the previous rows until the current response arrives.
Its REST snapshot replaces Node membership, including an empty current snapshot;
old entity or activity timestamps cannot retain a former Controller's Node set.
The retained ConnectScreen/SetupWizard uses registered-node wording; App's current
OnboardingWizard remains the bootstrap entry, not a second newly added workflow.

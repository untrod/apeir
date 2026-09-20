# Long-Running Project Specification v1.0

> Status: Draft — Phase 0.5
> Defines project, work item, checkpoint, and execution session contracts

---

## 1. Project

### 1.1 Schema
```json
{
  "project_id": "proj_20260713_a1b2",
  "name": "Add WebSocket support to Nous Runtime",
  "description": "Implement TLS WebSocket connectivity between Control Plane and Nodes",
  "status": "active",
  "owner": "user_main",
  "goals": ["..."],
  "milestones": ["..."],
  "current_plan_id": "plan_20260713_c3d4",
  "created_at": "2026-07-13T10:00:00Z",
  "updated_at": "2026-07-13T10:00:00Z"
}
```

### 1.2 States: `active | paused | completed | cancelled`
### 1.3 Rules
- Project state survives process restart (persisted to JSONL)
- All state transitions produce audit records
- Pausing stops dispatching new WorkItems; running items complete or pause
- Cancellation terminates all running sessions and marks project CANCELLED

---

## 2. ProjectGoal

### 2.1 Schema
```json
{
  "goal_id": "goal_20260713_e5f6",
  "project_id": "proj_20260713_a1b2",
  "description": "Nodes can connect via TLS WebSocket",
  "success_criteria": [
    "Node opens wss:// connection",
    "Heartbeat keeps session alive",
    "Reconnect works after disconnect"
  ],
  "priority": "high",
  "status": "in_progress"
}
```

### 2.2 Priority: `low | medium | high | critical`
### 2.3 Success criteria must be measurable and verifiable

---

## 3. Milestone

### 3.1 Schema
```json
{
  "milestone_id": "ms_20260713_g7h8",
  "goal_id": "goal_20260713_e5f6",
  "description": "Node daemon connects to Control Plane",
  "target_date": null,
  "status": "in_progress",
  "work_item_ids": ["wi_20260713_i9j0", "wi_20260713_k1l2"]
}
```

---

## 4. WorkPlan

### 4.1 Schema
```json
{
  "plan_id": "plan_20260713_c3d4",
  "project_id": "proj_20260713_a1b2",
  "created_at": "2026-07-13T10:00:00Z",
  "status": "executing",
  "work_items": ["..."],
  "dependency_graph": {"wi_2": ["wi_1"]}
}
```

### 4.2 States: `draft | approved | executing | completed | stale`
### 4.3 Plan becomes stale when new WorkItems are added without plan regeneration

---

## 5. WorkItem

### 5.1 Schema
```json
{
  "work_item_id": "wi_20260713_m3n4",
  "milestone_id": "ms_20260713_g7h8",
  "description": "Implement NodeDaemon class with WebSocket connection",
  "target_node": "personal_laptop",
  "required_capability": "process.run_sandboxed",
  "required_platform": {"os": "any", "arch": "any"},
  "required_files": ["nous_runtime/connectivity/node/*.py"],
  "required_tools": ["python3.10", "git"],
  "gpu_required": false,
  "budget": {"max_cost": 0, "max_tokens": 0, "max_time_ms": 3600000},
  "risk_level": "medium",
  "completion_condition": "NodeDaemon connects to test Control Plane, heartbeat works, tests pass",
  "status": "queued",
  "depends_on": ["wi_20260713_o5p6"],
  "created_at": "2026-07-13T10:00:00Z"
}
```

### 5.2 States: `pending | queued | assigned | running | completed | failed | cancelled`
### 5.3 Rules
- Target node must be online (or task remains queued)
- All `depends_on` must be completed before assignment
- Budget enforced: timeout kills task, cost overrun fails task
- Completion condition is human-readable but checkable

---

## 6. Checkpoint

### 6.1 Schema
```json
{
  "checkpoint_id": "cp_20260713_q7r8",
  "project_id": "proj_20260713_a1b2",
  "created_at": "2026-07-13T14:00:00Z",
  "description": "Phase 1a protocol contracts complete",
  "work_item_states": {
    "wi_20260713_i9j0": "completed",
    "wi_20260713_k1l2": "completed"
  },
  "artifact_hashes": ["sha256:abc123...", "sha256:def456..."],
  "immutable": true
}
```

### 6.2 Rules
- Append-only: never modified after write
- Stored as JSONL (append-only format)
- Contains snapshot of all WorkItem states at checkpoint time
- Artifact hashes provide content integrity verification

---

## 7. ExecutionSession

### 7.1 Schema
```json
{
  "session_id": "exec_20260713_s9t0",
  "work_item_id": "wi_20260713_m3n4",
  "node_id": "node_laptop_01",
  "started_at": "2026-07-13T10:01:00Z",
  "status": "running",
  "continuation_context": {"current_step": "implementing daemon.py", "files_modified": ["daemon.py"]}
}
```

### 7.2 States: `running | paused | completed | failed | cancelled`

---

## 8. ContinuationRequest & ResumeDecision

### 8.1 ContinuationRequest
```json
{
  "request_id": "cont_20260713_u1v2",
  "project_id": "proj_20260713_a1b2",
  "scope": "any_pending",
  "requested_at": "2026-07-13T10:00:00Z",
  "requested_by": "user"
}
```

### 8.2 ResumeDecision
```json
{
  "decision_id": "resume_20260713_w3x4",
  "request_id": "cont_20260713_u1v2",
  "resolved_work_item": "wi_20260713_m3n4",
  "resolved_action": "execute",
  "reason": "WorkItem wi_m3n4 is pending, all dependencies satisfied, target node online",
  "plan": null
}
```

### 8.3 Resolution Logic
1. Find all pending WorkItems for the project
2. Filter: all `depends_on` are completed
3. Sort: priority desc -> created_at asc
4. If exactly 1 item: `resolved_action = "execute"`, `resolved_work_item = item`
5. If 0 items: `resolved_action = "wait"`, `resolved_work_item = null`
6. If multiple items: `resolved_action = "plan"`, `resolved_work_item = null`, `plan = proposed_WorkPlan`
7. If project is paused: `resolved_action = "wait"`, reason = "project paused"

### 8.4 Ambiguous continuation always produces a plan, never arbitrary action

---

## 9. Pause and Resume

### 9.1 PauseRequest
- Pauses project: no new WorkItems dispatched
- Optionally pauses specific running ExecutionSession
- Running tasks complete current step, then pause

### 9.2 Resume
- Requires explicit user action (not automatic)
- Resolves continuation per §8
- If project was paused mid-task, that task's continuation_context is used to resume

---

## 10. ProjectArtifact

```json
{
  "artifact_id": "art_20260713_y5z6",
  "project_id": "proj_20260713_a1b2",
  "work_item_id": "wi_20260713_m3n4",
  "artifact_type": "diff",
  "path": "diffs/wi_m3n4.patch",
  "hash": "sha256:abc123...",
  "size_bytes": 2048,
  "created_at": "2026-07-13T14:00:00Z",
  "expires_at": null,
  "secret_free": true
}
```

### 10.1 Types: `diff | report | binary | log | test_results | scan_results`
### 10.2 `secret_free` verified by pre-export scan

---

## 11. ProjectStatusSnapshot

```json
{
  "snapshot_id": "snap_20260713_a7b8",
  "project_id": "proj_20260713_a1b2",
  "taken_at": "2026-07-13T14:00:00Z",
  "goals_completed": 2,
  "goals_total": 4,
  "milestones_completed": 1,
  "milestones_total": 3,
  "work_items_completed": 5,
  "work_items_total": 12,
  "work_items_failed": 0,
  "work_items_blocked": 1,
  "active_sessions": 1,
  "health": "ok"
}
```

### 11.1 Health: `ok | degraded | blocked | stalled`
- `degraded`: failures present but progress continues
- `blocked`: all pending items have unsatisfied dependencies
- `stalled`: no progress in 24 hours

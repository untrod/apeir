# Process Model — Nous Runtime

> **How computation is organized, isolated, and managed.**
> **Last updated:** 2026-08-06

---

## Process Hierarchy

```
System
  └── Runtime (1 per node)
        └── AgentProcess (1 per user session/workload)
              ├── Child AgentProcess (sub-tasks, delegation)
              │     └── ... (nested up to MAX_DEPTH)
              └── Workflow (DAG of tasks)
                    └── Task (unit of work)
```

## Process Lifecycle

```
CREATED → ADMITTED → RUNNING → PAUSED
                ↓         ↓        ↓
            REJECTED   FAILED   RESUMED
                                ↓
                           COMPLETED → ARCHIVED
                                ↓
                           CANCELLED
```

## Process Isolation

### Capability Inheritance
- Child processes inherit parent capabilities **narrowed only** (never widened)
- `CapabilitySet::narrower_than(&parent) -> bool` enforced at spawn
- Attempting to grant a capability the parent doesn't have → REJECTED

### Budget Enforcement
- Parent budget is a hard ceiling for all children combined
- Child cannot exceed: `min(parent.remaining_budget, child.requested_budget)`
- Budget exhaustion → Process paused with `BUDGET_EXHAUSTED` signal

### Resource Isolation
- Each process gets its own Context VM namespace
- Shared context pages require explicit `SHARED_READ` permission
- Workspace access scoped to process namespace

## Process Signals

| Signal | Effect |
|--------|--------|
| PAUSE | Suspend execution, preserve state |
| RESUME | Continue from last checkpoint |
| CANCEL | Graceful shutdown with checkpoint |
| KILL | Immediate termination (no checkpoint) |
| CHECKPOINT | Force state snapshot |
| RESTORE | Restore from checkpoint |
| BUDGET_UPDATE | Change resource allocation |
| CAPABILITY_NARROW | Remove capabilities |
| MIGRATE | Move to different node/device |

## Current Implementation Status

**RC7 (Python):** `nous_runtime/agent/` has `AgentExecutionRuntime`, `executor.py`, `lifecycle.py`. Functional but does not implement the full ProcessSignal model.

**RC8 (Rust):** `kernel/crates/nous-process/` has full `AgentProcess` with 13-state `ProcessStatus`, 11 `ProcessSignal`s, `CapabilitySet`, `Continuation`. Compiles but NOT wired into nousd or NKI.

**Gap:** Neither implementation matches the spec. Python agent is a simpler model. Rust process is orphaned. No code path actually spawns child processes with narrowed capabilities.

## Desktop Process Management

The Tauri desktop app manages two child processes:
1. **nousd** (Rust kernel daemon, port 8771) — optional, degrades gracefully
2. **Python runtime** (sidecar, port 8770) — required

Process tree cleanup uses `taskkill /PID /T /F` on Windows, `child.kill()` on Unix.

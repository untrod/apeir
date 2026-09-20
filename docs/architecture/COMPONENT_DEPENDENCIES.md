# Component Dependencies — Nous Runtime

> **What depends on what. Circular dependencies. Layering violations.**
> **Last updated:** 2026-08-06

---

## Dependency Layers (top-down)

```
Layer 7: Presentation
  desktop/src/         (React/TypeScript)
  nous_runtime/cli/    (Typer CLI)
  nous_runtime/api/    (HTTP API server)

Layer 6: Application
  nous_runtime/agent/          (Agent execution)
  nous_runtime/workflow/       (Workflow DAG)
  nous_runtime/planner/        (Task planning)
  nous_runtime/project/        (Workspace management)

Layer 5: Intelligence
  nous_runtime/intelligence/   (Routing, scheduling, profiles)
  nous_runtime/model_runtime/  (Model gateway, registry)
  nous_runtime/retrieval/      (Retrieval backends)

Layer 4: Governance
  nous_runtime/governance/     (Gate, approval, policies)
  nous_runtime/capability/     (Capability contracts, sandbox)
  nous_runtime/verification/   (Proof verification)

Layer 3: Platform
  nous_runtime/kernel/         (Object model, state machine)
  nous_runtime/context/        (Context store)
  nous_runtime/events/         (Event bus)
  nous_runtime/connectivity/   (Control plane, nodes)

Layer 2: Providers
  nous_runtime/provider/       (Model/tool/device adapters)
  nous_runtime/connectors/     (Git, web, etc.)

Layer 1: Foundation
  nous_runtime/compat/         (Legacy compatibility)
  remote_terminal/nous_core/   (Legacy P0 kernel)
  kernel/crates/               (Rust kernel crates)
```

## Layer Rules

1. Higher layers may depend on lower layers
2. Lower layers MUST NOT depend on higher layers
3. Same-layer dependencies allowed only through public interfaces
4. Circular dependencies are forbidden

## Current Violations

### CIRC-1: Bidirectional compat cycle
```
nous_runtime/compat/  ←→  remote_terminal/nous_core/
```
- `compat/` imports `nous_core.*` (via `from X import *`)
- `remote_terminal/` imports `nous_runtime.*` (in brain.py, tools.py, bridges)
- **Fix:** Make compat the single direction; remote_terminal must not import nous_runtime

### CIRC-2: Provider adapters bypass compat
```
nous_runtime/provider/adapters/  →  remote_terminal/ (direct)
```
- web.py, embed.py, device_pc.py, device_android.py, chromadb.py import `remote_terminal.*` directly
- **Fix:** Route through compat layer or remove dependency

### CIRC-3: New kernel depends on legacy
```
nous_runtime/kernel/  →  nous_runtime/compat/  →  remote_terminal/nous_core/
```
- kernel/ uses `compat.ids.make_id` and `compat.db.run_migrations`
- **Fix:** Move ID generation and DB migrations into kernel/; deprecate compat dependency

### CIRC-4: Desktop state mutation violates event sourcing
```
desktop EntityStore  →  (writes)  task status (bypasses runtime events)
```
- `TaskCenter.tsx:110` calls `entityStore.updateTaskStatus()` optimistically
- **Fix:** Remove all local state mutations; wait for runtime event confirmation

## Critical Dependency Paths

### Must NOT break:
- `CLI → kernel → events` (all commands flow through kernel)
- `Desktop → API → governance → capability → effect gate` (all effects gated)
- `Model request → NKI → admission → scheduler → engine` (all inference through kernel)

### Currently broken:
- Model request → `ModelGateway(use_nki=False)` → direct provider (bypasses kernel)
- Tool execution → strict sandbox boundary; `brain_exec.py` local compatibility execution is disabled by default and has no direct subprocess path
- Task state → `task/manager.py` flat status (bypasses kernel state machine)

## Consolidation Required

### Registry consolidation (30+ → ~15)
| Group | Keep | Deprecate |
|-------|------|-----------|
| Device | `kernel/device_model.py:DeviceRegistry` | `device/adapter.py:DeviceRegistry` |
| Model | `model_runtime/registry.py:ModelRuntimeRegistry` | `model/registry.py`, `router.py` config |
| Provider | `provider/registry.py:ProviderRegistry` | (keep, but route through kernel) |
| Node | `connectivity/control_plane/node_registry.py` | kernel RegistryBase[Node] example |

### Scheduler consolidation (22 → ~8)
- Keep 3 Python schedulers: model routing, task scheduling, learning
- Keep Rust scheduler policies as nousd implementation detail
- Deprecate remaining Python scheduler variants

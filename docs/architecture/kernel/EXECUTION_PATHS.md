# Nous Kernel Execution Paths

> RC4 Kernel Closure — verified 2026-08-04

## Unified Execution Model

```
                    ┌──────────┐
                    │  Client  │ (CLI / Desktop / HTTP / SDK)
                    └────┬─────┘
                         │ NKI Protocol (base64 JSON, length-prefixed)
                         │ UDS (Linux) / TCP (Windows) / QUIC (remote)
                         ▼
               ┌─────────────────┐
               │    nousd TCB    │
               │  (Rust daemon)  │
               └────────┬────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Validate │ │  Admit   │ │  Lease   │
    │ Schema   │ │ Resource │ │  Grant   │
    └────┬─────┘ └────┬─────┘ └────┬─────┘
         │            │            │
         └────────────┼────────────┘
                      │
                      ▼
              ┌───────────────┐
              │   Journal     │ (append-only SQLite)
              │   (Intent +   │
              │  Transitions) │
              └───────┬───────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Scheduler│ │ Memory   │ │ Engine   │
    │ Placement│ │ Fabric   │ │ Process  │
    └────┬─────┘ └────┬─────┘ └────┬─────┘
         │            │            │
         └────────────┼────────────┘
                      │
                      ▼
              ┌───────────────┐
              │   Execution   │
              │   (Phase by   │
              │    Phase)     │
              └───────┬───────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Verify   │ │ Artifact │ │ Commit/  │
    │ Output   │ │  Store   │ │Compensate│
    └──────────┘ └──────────┘ └──────────┘
```

## Verified Paths (RC4)

### Path 1: CLI Chat Request
```
nous run "hello"
→ NKIClient.submit_workload(WorkloadSpec{Chat, goal:"hello"})
→ [TCP:8771] nousd:handle_submit_workload()
→ AdmissionController.admit() [feasibility→availability→security→deadline]
→ LeaseManager.grant() [duplicate check→UUID v7→reserve resources]
→ Journal::append(Intent entry with full WorkloadSpec)
→ Journal::append(CREATED→VALIDATING→VALIDATED→ADMITTED)
→ Registry.insert(workload_id, spec, phase=ADMITTED)
→ NKIResponse{workload_id, phase:ADMITTED, lease_id}
```

### Path 2: Health Check (deep)
```
NKIClient.health_check(deep=true)
→ nousd:handle_health_check()
→ Journal::verify_integrity() [SHA-256 per entry]
→ LeaseManager::active_count()
→ MemoryFabric::tier_stats() [HBM/RAM pressure]
→ integrity::run_integrity_audit() [7 RC4 checks]
→ NKIResponse{healthy, components, rc4_audit}
```

### Path 3: Crash Recovery
```
nousd bootstrap
→ Journal::open() [WAL mode, schema creation, max(sequence) recovery]
→ recovery::recover(&journal) [identify interrupted workloads]
→ Rebuild registry from Intent entries
→ Execute RecoveryActions:
  Resume → mark workload RECOVERING
  Restart → mark workload CREATED
  MarkLost → mark workload LOST
  MarkFailed → mark workload FAILED
→ integrity::run_integrity_audit()
→ NKIServer::run() [accept connections]
```

### Path 4: Model Load
```
NKIClient.load_model(model_id, engine_id, device_id)
→ nousd:handle_load_model()
→ Verify model in registry
→ MemoryFabric::register(weight_object, HBM tier)
  → Content-addressable dedup check
  → Tier capacity check
  → Eviction if needed
→ Journal::append(VALIDATED→LOADED)
→ Registry update (phase=LOADED, instance_id)
```

## Known Bypass Paths (To Be Closed)

### Bypass 1: Direct Model Gateway
```
Workflow/Agent
→ nous_runtime/model_runtime/gateway.py
→ ModelBackendAdapter.invoke()
→ OpenAI/Anthropic/Ollama HTTP
(BYPASSES: NKI, WorkloadIR, Admission, Lease, Journal, Governance)
```

### Bypass 2: Direct Shell Execution
```
Agent executor
→ nous_runtime/capability/sandbox.py
→ subprocess.Popen()
(BYPASSES: Capability Manifest, Governance, Isolation Profile)
```

### Bypass 3: Parallel Python Kernel State
```
nous_runtime/kernel/task.py (22-state TaskPhase)
nous_runtime/task/models.py (7-state TaskStatus)
nous_runtime/events/stream.py (JSONL EventStream)
(BYPASSES: Rust WorkloadPhase, Journal as single source of truth)
```

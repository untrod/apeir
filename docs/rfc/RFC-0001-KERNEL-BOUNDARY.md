# RFC-0001: Nous AI Kernel Boundary

- **Status:** Draft
- **Date:** 2026-08-04
- **Author:** Nous Kernel Architecture
- **Target Release:** kernel-next

---

## 1. Problem

The current Nous Runtime (`nous_runtime/`) has no enforced kernel boundary:

1. **Three incompatible Task models**: `kernel.Task` (22 states), `task.Task` (7 states), `events.RunState` (11 states) — each used by different subsystems with no reconciliation.
2. **~30 registry classes**: despite `kernel.RegistryBase` existing, most subsystems maintain independent registries with their own persistence, indexing, and lifecycle.
3. **Two parallel event systems**: `RuntimeEventBus` (global SQLite pub/sub) and `EventStream` (per-run JSONL) with different schemas and no unified journal.
4. **Product layers bypass kernel**: Desktop, CLI, and HTTP API call Providers, tools, and capabilities directly — not through any kernel admission path.
5. **No trusted computing base**: All code runs in the same Python process with no isolation between kernel, engines, plugins, and product logic.
6. **Two checkpoint systems**: `kernel.checkpoint_store` (SQLite) and `checkpoint.store` (in-memory), each used by different Task models.
7. **Orchestration layer is disconnected**: `orchestration/` defines `TaskGraph`, `WriteLease` that duplicate kernel concepts but import from neither `kernel/` nor `task/`.

The result: there is no single place where correctness, security, resource management, or state consistency can be enforced. Every subsystem is its own island.

---

## 2. Constraints

1. **Must preserve existing functionality**: CLI, HTTP API, desktop, SDK, and all existing tests must continue to work during migration.
2. **Must preserve existing data**: Run records, conversations, workspaces, model registrations, and user configuration must be migratable.
3. **Cannot big-bang replace**: Python runtime must coexist with new Rust kernel during transition.
4. **Must support current platforms**: Windows ARM64 (Xiaomi tablet), Windows x86_64, Linux x86_64, Linux ARM64.
5. **Must not break public APIs**: Existing HTTP API, CLI commands, and Python SDK must remain compatible or have explicit deprecation paths.
6. **Existing plugins and providers**: Must continue to function through compatibility adapters.

---

## 3. Proposed Kernel Boundary

### 3.1 Definition

The **Nous AI Kernel** is the minimal trusted computing base that:

1. Owns all authoritative state
2. Enforces resource admission and isolation
3. Validates and executes Workload IR
4. Manages model, engine, and device lifecycles
5. Provides exactly one entry point (NKI) for all external requests

Everything outside the kernel is a **system service** or a **product application** and must communicate through NKI.

### 3.2 Kernel Components (Trusted Computing Base)

```
┌────────────────────────────────────────────┐
│                 Nous AI Kernel              │
│                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │  NKI     │  │  Security│  │  Journal │ │
│  │  Server  │  │  Gate    │  │          │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
│       │             │             │       │
│  ┌────┴─────────────┴─────────────┴─────┐ │
│  │         Workload Admission           │ │
│  └────┬─────────────────────────────────┘ │
│       │                                    │
│  ┌────┴─────┐  ┌──────────┐  ┌──────────┐ │
│  │ Resource │  │ Scheduler│  │  State   │ │
│  │ Manager  │  │          │  │ Machine  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
│       │             │             │       │
│  ┌────┴─────────────┴─────────────┴─────┐ │
│  │           Object Model                │ │
│  │  (types, IDs, Spec/Status, versions) │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │  Model   │  │  Device  │  │  Lease   │ │
│  │ Lifecycle│  │ Manager  │  │ Manager  │ │
│  └──────────┘  └──────────┘  └──────────┘ │
└────────────────────────────────────────────┘
```

**In TCB (must be correct for system integrity):**
- `nousd` main process
- Core types (`nous-types`): all kernel object definitions
- State machine (`nous-state`): journal, CAS transitions, fencing
- Resource manager (`nous-resource`): admission, reservation, enforcement
- Security gate: principal authentication, capability verification, default-deny
- NKI server: request validation, routing, response
- Lease manager: generation, expiry, renewal
- Minimum cryptography for identity and integrity

**NOT in TCB (runs in isolated processes):**
- Model engines (vLLM, llama.cpp, ONNX Runtime, etc.)
- Device drivers
- Third-party plugins
- Python runtime (becomes a client of the kernel)
- Product applications (desktop, CLI, web)
- AI/ML inference code
- Tokenizers
- File format parsers

### 3.3 Communication Architecture

```
┌──────────────────────────────────────────────────────┐
│  Product Layer (Desktop / CLI / Web / SDK)           │
│  Python process or separate application              │
└────────────────┬─────────────────────────────────────┘
                 │ NKI (UDS / Named Pipe / QUIC)
┌────────────────┴─────────────────────────────────────┐
│  System Services (Agent / Workflow / Knowledge)      │
│  Python compatibility layer over NKI client          │
└────────────────┬─────────────────────────────────────┘
                 │ NKI
┌────────────────┴─────────────────────────────────────┐
│                   Nous Kernel (nousd)                 │
│  ┌─────────────────────────────────────────────────┐ │
│  │  NKI Server ── Workload Admission ── Scheduler  │ │
│  │       │              │                │         │ │
│  │  State Journal ── Resource Mgr ── Security Gate │ │
│  └─────────────────────────────────────────────────┘ │
└──────┬──────────────────────────────┬────────────────┘
       │ Engine ABI                   │ Device ABI
       │ (IPC)                        │ (IPC)
┌──────┴──────────┐          ┌───────┴───────────┐
│  nous-modeld    │          │  nous-driverd     │
│  (engine host)  │          │  (device host)    │
│  ┌────────────┐ │          │  ┌─────────────┐  │
│  │ vLLM       │ │          │  │ CUDA        │  │
│  │ llama.cpp  │ │          │  │ ROCm        │  │
│  │ ONNX       │ │          │  │ CPU         │  │
│  │ OpenAI API │ │          │  │ Vulkan      │  │
│  └────────────┘ │          │  └─────────────┘  │
└─────────────────┘          └───────────────────┘
```

### 3.4 What the Kernel Does NOT Do

The kernel does NOT:
- Implement attention mechanisms or CUDA kernels
- Parse model weight formats (GGUF, safetensors — delegates to engine)
- Execute Python code from model repositories
- Run LLM inference directly (always via Engine ABI)
- Own UI, product, or domain logic
- Manage user preferences or workspaces (system services own these)
- Provide HTTP REST APIs directly (compatibility layer does this)
- Know about specific model architectures (engines declare capabilities)

### 3.5 Entry Point Unification

**Before (current):**
```
Desktop ──► Tauri Command ──► Python child process
Desktop ──► HTTP REST ──► api/routes.py
Desktop ──► WebSocket ──► control_plane/websocket.py
CLI     ──► typer ──► direct function calls
SDK     ──► Python import ──► direct class instantiation
```

**After:**
```
Desktop ──► NKI Client ──► NKI (UDS/Named Pipe) ──► nousd
CLI     ──► NKI Client ──► NKI (UDS/Named Pipe) ──► nousd
SDK     ──► NKI Client ──► NKI (UDS/Named Pipe) ──► nousd
Web     ──► HTTP Adapter ──► NKI Client ──► nousd
```

All external communication converges on NKI. The kernel has exactly one entry point.

---

## 4. Security and Ownership

### 4.1 Trusted Computing Base

The TCB is limited to `nousd` and its directly linked Rust crates:
- `nous-types` (0 external dependencies beyond serde)
- `nous-state` (SQLite or direct file I/O)
- `nous-nki` (protobuf + IPC transport)
- `nous-resource` (pure computation)
- `nous-security` (minimal ed25519 + TLS)

No Python, no ML framework, no GPU driver code in TCB.

### 4.2 Process Model

| Process | User | Capabilities | Network | Filesystem |
|---------|------|-------------|---------|------------|
| `nousd` | `nous` | minimal | NKI port only | journal + config (ro) |
| `nous-modeld` | `nous-model` | GPU access | none | model weights (ro) |
| `nous-driverd` | `nous-device` | device nodes | none | device sysfs (ro) |
| `nous-plugind` | `nous-plugin` | restricted | none | plugin dir (ro) |
| `nous-stated` | `nous-state` | none | none | journal (rw) |
| Python runtime | user | via NKI | via NKI | workspace (rw) |

### 4.3 State Ownership

Every durable state has exactly one authoritative owner:

| State | Owner | Storage |
|-------|-------|---------|
| Workload | nousd | Journal |
| Run | nousd | Journal |
| Task | nousd | Journal |
| ResourceLease | nousd | Journal |
| ModelPackage | nousd | Model Registry |
| EngineRegistration | nousd | Engine Registry |
| DeviceRegistration | nousd | Device Registry |
| Node | nousd | Node Registry |
| Principal | nousd | Auth Store |
| CapabilityGrant | nousd | Auth Store |
| Checkpoint | nousd | Journal + Snapshot |
| AuditRecord | nousd | Journal |

System services (Agent, Workflow, Knowledge, Conversation) own their data through NKI-submitted workloads, but the kernel owns the execution state.

---

## 5. Compatibility

### 5.1 Migration Path

```
Phase 1 (this RFC):  Define boundary. Create Rust workspace. Write schemas.
Phase 2:             Implement nousd with NKI, journal, state machine.
                     Python runs as before, but NKI client can echo-test.
Phase 3:             Model/Engine/Device registration migrates to NKI.
                     Python CLI/SDK use NKI client under the hood.
Phase 4:             Workload submission migrates to NKI.
                     HTTP API becomes compatibility facade over NKI.
Phase 5:             Full kernel takeover. Python is just a binding + services.
                     Old direct paths produce deprecation warnings.
Phase 6:             Remove deprecated paths (post stable release).
```

### 5.2 Backward Compatibility

- Existing Python API (`RuntimeRequest`, `RuntimeResponse`, CLI commands) preserved as compatibility wrappers
- HTTP REST API preserved as NKI HTTP adapter
- WebSocket event stream preserved as NKI event watch adapter
- Old `task.Task` and `kernel.Task` both mappable to kernel Workload
- Deprecated APIs marked with `warnings.warn()` and documented sunset date

### 5.3 Breaking Changes (Future)

After Phase 6 stable release:
- Direct `provider.invoke()` calls from product code
- Direct model registry access from non-kernel code
- Bypassing Workload IR for chat/inference
- Multiple parallel state stores for the same entity

---

## 6. Validation

### 6.1 Contract Tests

- NKI contract test: submit/get/cancel/list workload against nousd
- Journal contract test: append, replay, CAS transition, fencing
- State ownership test: every state has exactly one authoritative writer
- Isolation test: engine crash does not corrupt kernel state
- Migration test: old task/run data readable via new kernel

### 6.2 Architecture Tests

- **Import boundary**: No Python module outside compat/ imports `nous_runtime.kernel` internals directly
- **Bypass prevention**: No product code calls Provider/Tool/Device without going through NKI Workload submission
- **Registry audit**: All persistent state goes through a single RegistryBase-derived store
- **Event unification**: Only one event emission path (Journal) exists

### 6.3 Fault Injection

- Kill nousd mid-workload → recover from journal on restart
- Kill nous-modeld mid-inference → workload fails gracefully
- Corrupt journal entry → detect and quarantine
- Network partition between nousd and remote engine → lease expiry
- Simultaneous cancel and completion → exactly one terminal state

### 6.4 Acceptance Criteria

- [ ] Kernel boundary document published and reviewed
- [ ] Rust workspace compiles on Linux x86_64 and Windows ARM64
- [ ] NKI v1 schema defined in protobuf
- [ ] nousd starts, accepts NKI requests, journals state
- [ ] Existing Python test suite passes (with compat layer)
- [ ] 100% of kernel state transitions go through journal
- [ ] 0 occurrences of product code bypassing NKI for side-effect operations

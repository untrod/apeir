# Nous Kernel — Trusted Computing Base

> RC4 Kernel Closure
> Date: 2026-08-04

## TCB Definition

The Trusted Computing Base (TCB) for the Nous AI Kernel is the set of components that **must be correct** for the kernel's security and reliability guarantees to hold.

A bug or compromise in any TCB component can violate:
- Resource isolation (one workload cannot consume another's resources)
- State integrity (journal is append-only and non-repudiable)
- Governance enforcement (side effects require authorization)
- Lease enforcement (no execution without valid lease)
- Recovery guarantees (crash → recoverable state)

## TCB Components (Inside)

### Rust Kernel Crates (inside nousd process)

| Crate | Role | Why TCB |
|-------|------|---------|
| `nous-types` | Core object model, error codes, type definitions | All kernel objects validated through these types |
| `nous-state` | Journal, state machine, fencing, recovery | Single source of truth for all kernel state |
| `nous-nki` | NKI protocol envelope, methods, transport | Sole entry point; all external requests pass through |
| `nous-resource` | Admission control, lease management, resource domains | Enforces "no lease → no execution" |
| `nous-scheduler` | Placement, workflow, phase scheduling | Decides where and how workloads execute |
| `nous-memory` | Memory fabric, KV cache metadata | Manages memory residency and eviction |
| `nous-security` | Execution gate, capability manifest, security engine | Enforces capability-based access control |
| `nousd` | Kernel daemon main process | Orchestrates all subsystems; validates all transitions |

### TCB Properties

1. **Append-only journal** — once written, journal entries cannot be modified or deleted
2. **Monotonic sequences** — journal sequence numbers only increase
3. **Checksum verification** — every journal entry has SHA-256 checksum
4. **Fencing tokens** — CAS validation prevents stale writes
5. **Idempotency** — duplicate requests produce same result, not duplicate state
6. **Lease enforcement** — no workload executes without valid, unexpired lease
7. **Default-deny** — side effects require explicit capability grant
8. **State machine validation** — only valid phase transitions accepted
9. **NKI as sole entry** — all external requests go through versioned NKI
10. **Recovery from journal** — kernel state fully reconstructable from journal

## Non-TCB Components (Outside)

These components can fail or be compromised **without** violating kernel guarantees:

### Product Layers
- **CLI** (`nous_runtime/cli/`) — User interface; crash loses nothing but current command
- **Desktop** (`desktop/`) — Control plane UI; reads state from kernel, never owns it
- **HTTP API** (`nous_runtime/api/`, `nous_runtime/control_plane/`) — Stateless REST gateway
- **Python SDK** (`nous_runtime/`) — Convenience wrappers around NKI

### External Processes
- **Model engines** (llama.cpp, vLLM, Ollama) — Run as separate processes; engine crash cannot corrupt kernel state
- **Device drivers** (CUDA, Vulkan) — Vendor code; kernel validates before use
- **Plugins** — Third-party code; sandboxed with capability manifest
- **Connectors** — External integrations; kernel enforces limits

### Data
- **Model weights** — Read-only from kernel perspective; validated via SHA-256
- **User data** — Accessed through capability grants only
- **Provider credentials** — Stored encrypted; never logged

## Trust Boundary

```
┌────────────────────────────────────────────┐
│               TRUSTED (TCB)                │
│                                            │
│  nousd process:                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │  NKI     │ │  Journal │ │  Lease   │   │
│  │  Server  │ │  (SQLite)│ │  Manager │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘   │
│       │            │            │         │
│  ┌────┴────────────┴────────────┴────┐    │
│  │       State Machine + Fencing     │    │
│  └────────────────┬──────────────────┘    │
│                   │                       │
│  ┌────────────────┴──────────────────┐    │
│  │  Admission + Scheduler + Memory   │    │
│  └───────────────────────────────────┘    │
│                                            │
│  ─ ─ ─ Trust Boundary ─ ─ ─ ─ ─ ─ ─ ─ ─  │
└────────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │  Engine  │ │  Device  │ │  Plugin  │
  │ Process  │ │  Driver  │ │ Process  │
  │(separate)│ │(separate)│ │(separate)│
  └──────────┘ └──────────┘ └──────────┘
     UNTRUSTED    UNTRUSTED    UNTRUSTED
```

## What Is NOT in the TCB

1. **Python runtime interpreter** — Python code runs outside nousd; kernel validates all inputs
2. **Model inference engines** — Run as separate processes; kernel monitors, enforces timeouts
3. **GPU/NPU drivers** — Vendor code; kernel validates resource claims
4. **Desktop UI (Tauri/React)** — Reads state from NKI; never authoritative
5. **CLI tools** — Convenience wrappers; can be restarted
6. **Third-party plugins** — Sandboxed; capability-limited
7. **Network protocols (HTTP/QUIC)** — Transport only; kernel validates payloads
8. **Filesystem** — Kernel uses SQLite WAL; corruption detection via checksums

## TCB Size

| Language | Lines | Components |
|----------|-------|-----------|
| Rust | ~6,550 | 13 crates + 3 adapters + nousd |
| SQL | ~30 | Journal schema definition |
| Protobuf | ~2,000 | NKI, Engine ABI, Device ABI specs |

**Total TCB: ~8,600 lines** (excluding generated code, tests, and adapters)

## Verification Status (RC4)

| Property | Verified? | Method |
|----------|-----------|--------|
| Journal append-only | ✅ | SQLite WAL mode, no UPDATE/DELETE in code paths |
| Monotonic sequences | ✅ | Mutex-guarded counter |
| Checksum integrity | ✅ | SHA-256 verification on read |
| Fencing tokens | ✅ | CAS on every transition |
| Idempotency | ✅ | Unique index on idempotency_key |
| Lease enforcement | ✅ | Double-check pattern in grant(); has_valid_lease() |
| Default-deny | ⚠️ | Defined in security crate; runtime enforcement pending |
| State machine validation | ✅ | can_transition_to() with explicit valid transitions |
| NKI as sole entry | ⚠️ | Python bypass paths still exist (documented) |
| Recovery from journal | ✅ | Intent entries + phase reconstruction |

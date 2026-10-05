# ADR-0001: kernel-next Architecture

- **Date:** 2026-08-04
- **Status:** Accepted
- **Deciders:** Nous Kernel Architecture

## Context

The current Nous Runtime has evolved organically, resulting in:
- 3 incompatible Task state machines
- 22+ independent registry implementations
- 2 parallel event systems
- No resource admission control
- No stable kernel interface

The `kernel-next` branch establishes a new architecture that addresses these issues while preserving backward compatibility.

## Decision

1. **Rust Kernel Spine** — New kernel logic is written in Rust for safety, performance, and stable ABIs.
2. **Python Compatibility** — Existing Python code continues to work through a compatibility facade that translates old API calls to NKI requests.
3. **Spec/Status Pattern** — Every kernel object separates desired state (Spec) from observed state (Status), following the Kubernetes model.
4. **Append-Only Journal** — All state transitions are recorded in an append-only SQLite journal. Recovery replays the journal.
5. **NKI as Sole Entry Point** — All external communication goes through NKI. No direct Provider/tool/device access from product layers.
6. **Incremental Migration** — New kernel runs alongside old Python runtime. Gradual feature takeover. No big-bang rewrite.

## Consequences

- Rust toolchain becomes a build dependency
- Python runtime must run an NKI client (compat/nki_client.py)
- Journal becomes single source of truth; EventStream and RuntimeEventBus consolidated over time
- Engine and device adapters move to separate processes over Engine ABI / Device ABI

## Alternatives Considered

1. **Pure Python refactor** — Rejected: Python cannot provide the stable C ABI, process isolation, and performance needed for a kernel.
2. **Rewrite from scratch** — Rejected: Would break all existing functionality and take too long.
3. **Rust rewrite of everything** — Rejected: The Python ecosystem (ML libraries, existing plugins) is essential. Python remains the application layer.

## Related

- RFC-0001: Kernel Boundary
- RFC-0002: Kernel Object Model
- RFC-0003: Workload IR
- RFC-0004: NKI v1
- [APEIR Kernel repository](https://github.com/untrod/apeir-kernel)

# RFC-0008: Resource Model & Admission Control

- **Status:** Draft
- **Date:** 2026-08-04
- **Depends on:** RFC-0001, RFC-0002, RFC-0003

## Problem

No resource admission control exists. Workloads are dispatched without feasibility checks, resource reservation, or enforcement. A workload requesting more VRAM than available causes OOM at runtime rather than being rejected at admission time.

## Proposed Design

ResourceVector: 13 dimensions (cpu_cores, cpu_time, ram, pinned_ram, device_memory, kv_cache, storage, memory_bw, interconnect_bw, network_bw, power, thermal, time).

Pipeline: Estimate → Feasibility → Admission → Reservation → Placement → Lease → Execution.

Hierarchy: System → Tenant → Workspace → Agent → Workload.

Enforcement: Hard limits, soft limits, reservation, burst, pressure, backpressure, fair share, deadline, priority, preemption class.

## Key Principle

**NO LEASE → NO EXECUTION.** Every executing workload must hold a valid, unexpired ResourceLease.

## See Also

- `kernel/crates/nous-resource/src/admission.rs` — AdmissionController
- `kernel/crates/nous-resource/src/lease.rs` — LeaseManager
- `kernel/crates/nous-resource/src/domain.rs` — DomainHierarchy
- `kernel/crates/nous-types/src/resource.rs` — ResourceVector, ResourceLease

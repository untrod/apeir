# Nous Public API Compatibility Promise — v1beta1

> Version: 1.0.0-beta1
> Date: 2026-08-05
> Status: v1beta1 (public review)

## Purpose

This document defines what is STABLE (externally depended upon) and what is
INTERNAL (subject to change without notice) in the Nous platform. It is the
single source of truth for backward compatibility guarantees.

## Stable Interfaces (v1beta1)

These interfaces are frozen for the v1beta1 cycle. Breaking changes require
a major version bump and a documented migration path with at least one minor
version of deprecation notice.

### NKI v1beta1 (Nous Kernel Interface)

- Wire format: 4-byte big-endian length prefix + JSON body
- Envelope: `NKIRequest` / `NKIResponse` with `status: "success" | "error"` tagged enum
- Method names: PascalCase strings (SubmitWorkload, GetWorkload, …)
- All 26 method signatures (25 original + RenewLease)
- Error codes: 42 standard codes as defined in `nki.proto`
- Version negotiation: `nki_version` field, server rejects < MIN or > MAX
- Payload encoding: base64-encoded JSON
- MAX_MESSAGE_SIZE: 16 MB

### Workload IR v1beta1

- `WorkloadSpec` schema with all typed fields
- 19 `WorkloadType` variants
- 17-phase `WorkloadPhase` lifecycle with validated transitions
- `ExecutionGraph` with 21 `PhaseType`s and `EdgeCondition`s
- `ModelRequirements`, `DeviceRequirements`, `QualityRequirements`,
  `SecurityRequirements`, `ResourceRequirements`, `LatencySLO`,
  `EnergyBudget`, `CostBudget`

### Engine Provider ABI v1beta1

- 17 engine operations: probe, capabilities, validate_model, estimate_resources,
  compile, load_model, warmup, infer, stream_infer, cancel, pause, snapshot,
  restore, drain, unload_model, health, metrics
- `EngineSpec` / `EngineStatus` / `EnginePhase` lifecycle (8 states)
- `InferRequest` / `InferResponse` / `TokenStream` types

### Device Provider ABI v1beta1

- 14 device operations: discover, probe, verify, bind, initialize, allocate,
  free, submit, synchronize, reset, suspend, resume, unbind, health, telemetry, topology
- `DeviceSpec` / `DeviceStatus` / `DevicePhase` lifecycle (13 states)
- `ResourceVector` (13 dimensions)
- `TopologyLink` schema

### Model Package v1beta1

- `ModelPackageSpec` with all typed fields
- 13-phase import pipeline
- Supported formats: GGUF, SafeTensors, ONNX, PTE, TensorRT Engine
- Blocked: pickle, trust_remote_code
- SHA-256 + signature verification required

### Resource Model v1beta1

- `ResourceVector`: 13 dimensions with saturating arithmetic
- `ResourceDomain`: 5-level hierarchy (System → Tenant → Workspace → Agent → Workload)
- `ResourceLease`: time-bound with generation-based CAS
- `ResourceClaim` / `ResourceSlice`: demand/supply matching
- `PriorityClass`: System > Interactive > Batch > BestEffort
- `PreemptionPolicy`: Never / IfLowerPriority / Always

### Event Envelope v1beta1

- `EventEnvelope` structure: event_type, source, payload, metadata
- `JournalEntry` types: Intent, Transition, Observation, Commit, Compensate
- Sequence-based ordering with fencing tokens

### Error Model v1beta1

- 42 standard error codes (matching proto `ErrorCode` enum)
- `NKIErrorBody`: code, message, failed_phase, cause, retryable, recommended_delay_ms
- `RetryHint`: strategy + delay + max_retries

### Capability Manifest v1beta1

- `CapabilityManifest` fields: reads, writes, devices, network_destinations,
  credentials, side_effects, reversible, data_classification, requires_approval,
  resource_limits
- Default-deny: everything blocked unless explicitly granted
- Risk levels: low, medium, high, critical
- Reversibility classification

### Distribution Manifest v1beta1

- Package identity: name, version, vendor, license
- Kernel compatibility: kernel_version_min, kernel_version_max
- Content declarations: providers, engines, models, policies
- Security: security_baseline, isolation_default
- Updates: update_channel, update_url
- Signing: signing_key_id, SBOM URL

## Unstable Internals (may change without notice)

- Rust internal trait hierarchies
- Internal database schemas (SQLite table layouts)
- Internal scheduler implementation details
- Internal memory fabric implementation
- Crate/module directory structure
- Internal Rust types not exposed through NKI or ABIs
- `nousd` internal data structures
- CLI argument format (use the NKI protocol for automation)

## Deprecation Policy

1. A stable interface may be deprecated by announcing it in a release notes
   section titled "DEPRECATIONS" at least one minor version before removal.
2. During the deprecation period, the old interface continues to work and
   produces a warning (log message at WARNING level).
3. After the deprecation period (minimum: one minor version), the interface
   may be removed in a major version bump.
4. Security-critical deprecations may be accelerated with a security advisory.

## Versioning

- MAJOR: breaking changes to stable interfaces
- MINOR: new stable interfaces, deprecation notices
- PATCH: bug fixes, internal refactors, no interface changes

## Conformance

Providers, engines, devices, and distributions claiming compatibility with
this specification MUST pass the Nous Conformance Test Kit (nous-ctk) at
their claimed certification level.

## References

- `spec/nki/v1/nki.proto` — NKI protocol definition
- `spec/engine-abi/v1/engine_abi.proto` — Engine ABI definition
- `spec/device-abi/v1/device_abi.proto` — Device ABI definition
- `spec/public-api/v1beta1/golden-vectors/` — Golden test vectors
- `runtime-components.lock.json` — Distribution-to-Kernel revision and artifact identity

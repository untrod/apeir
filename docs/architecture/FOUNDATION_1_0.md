# Nous Foundation 1.0 architecture

Nous Foundation is an AI execution kernel, not an application framework. Chat,
agents, retrieval, desktop UI and workflow products are clients or adapters.
They do not own kernel execution state.

## Kernel boundary

The trusted computing base is `nousd`, `nous-types`, `nous-state`,
`nous-resource`, `nous-scheduler`, `nous-security`, `nous-nki`, the transactional
effect engine and the minimum cryptographic implementation. External products
communicate through NKI or an ABI adapter that submits NKI workloads.

## Single production path

```text
client or adapter
  -> NKI authentication and validation
  -> Workload IR
  -> safety envelope
  -> admission and Scheduler Core
  -> resource lease
  -> journaled execution intent
  -> engine, tool or device provider
  -> transactional effect verification
  -> journaled commit
  -> event, trace and result
```

No client-side completion, local registry update or provider response is an
authoritative state transition. The journal is the only production state owner.

## State and knowledge

`nous-state` owns mutable kernel state through append-only records, CAS
generations and fencing. Semantic State Fabric is a journal-backed materialized
view. Knowledge Fabric accepts assertions only when every evidence reference is
registered and content-addressed.

## Effects and credentials

Effects move through planned, authorized, prepared, verified and committed
states. Repeated idempotency keys resolve to the original transaction. A
credential broker stores references, not values, and provides capability-scoped,
short-lived in-memory leases to effectors.

## Scheduling and learning

Program, placement, workflow and phase decisions are scopes of one Scheduler
Core. Historical Scheduler 1, 2 and 3 labels are policy sets: deterministic,
state-aware and adaptive. Adaptive policy is unavailable unless learning is
enabled, governance approves promotion and the safety envelope passes. The
deterministic policy is the mandatory fallback.

## Deployment profiles

Core, Edge and Micro share contract identifiers and execution semantics. They
differ only in resource scale and optional capabilities. Micro uses NMP v1,
fixed storage and explicit safety/effect callbacks; Zephyr consumes the portable
C source directly. The FreeRTOS boundary is reserved at the same ABI.

## Compatibility

The frozen contracts are documented in `spec/contracts/v1`. Python and product
modules remain compatibility clients during migration. OpenClaw, ROS 2 and OPC UA
are upper-layer adapters and have no authority inside the kernel.

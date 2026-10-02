# Reality Architecture Audit

Status: foundation implemented; physical-device acceptance not yet performed.

## Decision

APEIR already has the authoritative Work, Capability, receipt, Observation,
Verification, Artifact and Node execution paths. The Reality layer therefore
adds a durable resource projection and device-management boundary; it does not
introduce a second execution system.

| Concern | Existing authority | Decision | Foundation work |
|---|---|---|---|
| Work | `node_runtime.distributed_work`, Work Runtime | REUSE | An `Operation` references an existing `work_id`. |
| Resource | `kernel.resource_model` compute vectors and leases | EXTEND | Add a generic graph projection without changing leases. |
| Node | `connectivity.protocol.NodeIdentity`, Node Runtime | REUSE | Graph nodes reference the existing cryptographic identity. |
| Device | Kernel compute-device model; device manifests; legacy adapters | EXTEND | Add managed-device identity and lifecycle; do not replace compute discovery. |
| Capability | `capability.CapabilityContract` | EXTEND | Add side-effect and observation declarations; retain scheduling fields. |
| Effect | Effect Gate and at-most-once effect bindings | REUSE | Operation records the expected effect; admission remains unchanged. |
| OperationReceipt | Existing `nous.operation-receipt/v1` producers and validators | REUSE | Verification consumes the existing receipt mapping. |
| Observation | `planner.observation.Observation` | REUSE | Device providers return the same authoritative Observation type. |
| Verification | Verification Runtime and deterministic verifiers | EXTEND | Add the narrow `MATCH / MISMATCH / UNKNOWN` effect comparator. |
| Provider | Provider SDK plus device adapters | EXTEND | Add a minimal device-specific discovery/identity/state interface. |
| Transport | Node protocol and specialized transports | MISSING | Add a device transport boundary; a locator is explicitly not identity. |
| Resource relationships | No unified persisted projection | MISSING | Add typed JSON-backed relationships, not a graph database. |

## Resource graph

The first graph contains `Resource` projections of existing or managed objects:

```text
Node --HOSTS--> Device
Node/Device --EXPOSES--> Capability
Node/Device --CONNECTED_TO--> Transport
Capability/Operation --REQUIRES--> Transport/Capability
Device/Operation --OBSERVED_BY--> Observation
```

The store uses the Runtime's established atomic JSON replacement pattern. It is
an index for discovery and reasoning, not a new source of execution authority.

## Node and Device boundary

- A Node is an execution host with the existing cryptographic `NodeIdentity`.
- A Device is a managed real-world resource that may be hosted by a Node.
- A transport locator describes how to reach a Device at this moment.
- USB port numbers, serial paths, network addresses and simulator locators must
  not be used as permanent Device identity.
- Device identity is derived from provider-scoped stable evidence such as a
  manufacturer serial, hardware key or other durable fingerprint.

## Lifecycle and safety

The Device Registry persists these states:

```text
DISCOVERED -> IDENTIFIED -> TRUSTED -> AVAILABLE
                     \-> DEGRADED / OFFLINE / REVOKED
```

`REVOKED` is terminal. Device availability does not grant permission to act;
Capability admission, approval, Kernel routing and receipts remain mandatory.

An effect may auto-commit only when an existing OperationReceipt is bound to
the Operation and an independently acquired Observation yields `MATCH`.
`UNKNOWN` is fail-closed and cannot auto-commit.

## Current scope

`SimulatedDeviceProvider` proves only the contract path:

```text
discover -> identify -> register -> read state -> Observation
```

It is not a complete simulator, an ESP32 integration, or evidence that M3.3 has
passed physical-hardware acceptance.

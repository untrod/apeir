# APEIR project constitution and Distribution boundary

APEIR is an open execution, governance and verification runtime for heterogeneous
intelligence and real-world resources. Intelligence may come from models,
external agents, algorithms or humans. APEIR owns Work/Operation semantics,
governance, evidence, observation, effect verification and recovery. Mature agent
harnesses, schedulers, policy engines, secret stores, identities and device
platforms are replaceable Providers, not competing authorities inside APEIR.

## Non-negotiable invariants

- Model is never authority.
- Discovery is not trust; trust is not authorization.
- Authorization is not execution; execution is not effect.
- Receipt is not observation.
- UNKNOWN is not success.
- An effect that may already have happened is reconciled, never blindly retried.

A plan proposes intent. A scheduler proposes placement. A resource graph projects
relationships. None grants capability authority. A Node executes admitted Work;
a Device is the resource observed or affected. Transport locators can change
without changing Device identity. Rediscovery cannot reduce trust or revive a
REVOKED resource.

## Two explicit execution scopes

APEIR Kernel is independently released and pinned by
[`runtime-components.lock.json`](../../runtime-components.lock.json). It owns
admission, permits, compute resource leases and durable execution/effect proof
for **Kernel-managed NKI workloads**. Distribution clients cannot fabricate or
write that journal, permits or resource leases. Unsupported NKI versions and
unavailable Kernel services fail closed for this scope.

Distribution owns the existing governed **runtime-service scope**, including
AgentSession coordination, durable Workflow, Distributed Work, Node delivery,
Reality resource lifecycle, Governance grants/approvals, Credential leases,
Artifact CAS and runtime evidence. These are authoritative for their own scope,
not fabricated Kernel state. Scope evidence must not claim Kernel traversal:
`execution_scope=runtime-service`, `kernel_traversed=false`. Python compatibility
models under `nous_runtime.kernel` are not an independent Rust execution kernel.

A CapabilityGrant is an authorization lease. It is not a Kernel compute-resource
lease, execution permission by itself, or proof of an effect. An approval does
not bypass execution admission, expiry/revocation checks, credential scope,
delivery journals or independent effect verification.

The Kernel stays unchanged for the M3–M7 development program. If a future
milestone proves a Kernel contract impossible to satisfy externally, stop and
report the evidence; do not autonomously modify Kernel or silently add a bypass.

## Ownership and replaceability

Reuse canonical Work, Workflow, Capability, Artifact, Verification, Recovery and
Agent paths. Extend a narrow existing contract before adding a subsystem. A
Provider can supply intelligence, execution, policy input, secret resolution,
identity evidence or device access. Provider output remains evidence or a
proposal; it cannot approve its own request or commit its own claimed effect.

Cloud acceptance uses fake credentials and explicit simulated scopes. Physical
Jetson/ESP32 acceptance is PENDING until real hardware and fault evidence exist.
An unexercised integration is prepared or pending, never reported as validated.

## Compatibility and local state

`nous_runtime`, `nous` CLI aliases, `NOUS_*` configuration and existing `nous.*`
wire identifiers remain compatibility names. Preserve valid existing contracts;
security corrections may reject previously unsafe behavior and must be documented.
Databases, logs, credentials, caches, models, artifacts and evidence are runtime
user data, excluded from public source and release source archives.

Read the [architecture index](README.md) for the minimal authoritative set,
[execution path](EXECUTION_PATH.md), [state ownership](STATE_OWNERSHIP.md),
[security contract](SECURITY_CONTRACT.md) and [Provider model](PROVIDER_CONTRACT.md).

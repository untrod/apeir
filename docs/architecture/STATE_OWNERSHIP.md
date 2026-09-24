# State ownership

Each mutable state domain has one production owner. Mirrors and compatibility
stores are non-authoritative.

| State | Authoritative owner | Durable record | Other layers |
|---|---|---|---|
| Workload lifecycle | `nousd` state machine | `nous-state` journal | read through NKI |
| Resource claims and leases | resource manager | journal transitions | scheduler proposes only |
| Scheduling decisions | Scheduler Core | decision event and journal | policies are stateless inputs |
| Semantic state | Semantic State Fabric | journal commit | clients use CAS generation |
| Knowledge assertions | Knowledge Fabric | evidence and assertion records | retrieval is a derived index |
| NKI Reality effect lifecycle | Kernel `DurableExecutor` | Journal Intent, accepted receipt, observation, verification, and commit | Distribution hosts Node transport, Adapter execution, and Artifact bytes but cannot self-commit |
| Python Runtime service effect | Runtime authorization and service boundary | EventStream and Artifact records | does not claim Kernel execution |
| Reality evidence bytes | `ContentAddressedArtifactStore` | immutable SHA-256 Artifact plus metadata | Kernel Journal stores only `EvidenceRef`, digest, identities, and verification facts |
| Credentials | Credential Broker | references and audit metadata only | values stay in scoped leases |
| Model, engine and device registration | `nousd` registries | journaled registration | SDKs submit through NKI |
| Learning policy lifecycle | Learning Governance | evidence and promotion records | learning can only propose |
| Safety policy | Safety Envelope authority | signed versioned envelope | learning cannot modify it |

## Product Runtime projections

The current Python product layer has explicit owners for state that has not yet
moved behind `nousd`:

| State | Owner | Record |
|---|---|---|
| Project and work item | Project Coordinator | `connectivity_projects` and `connectivity_work_items` |
| Conversation execution cursor | Project Execution Service | `connectivity_runtime_bindings` |
| Project checkpoint | Project Coordinator | `connectivity_checkpoints` |
| Runtime run and event | EventStream | workspace `.nous/events` journal |
| Work Harness recovery | Checkpoint Store | workspace `.nous/checkpoints.db`; `work_harness` and existing `agent_execution` checkpoints |
| Work progress projection | EventStream | `work.*` events; UI and CLI do not own a second lifecycle |
| Kernel recovery checkpoint | Checkpoint Store | kernel `checkpoints` table |

These records are projections of Runtime activity. Provider responses and UI
state cannot directly mark them successful; only the verified Runtime outcome
path may do so.

The desktop entity store, Python compatibility objects, OpenClaw session maps,
ROS 2 state and OPC UA subscriptions are caches or adapters. They cannot create
kernel truth.

## Write rules

1. Every write has an owner, actor, generation and idempotency key.
2. State transitions use compare-and-swap and fencing.
3. The durable journal is written before a materialized view is updated.
4. External effects require a verified receipt before commit.
5. Credentials and secret values are never serialized into state or events.
6. A signed Node result is only a candidate execution fact. Kernel independently
   validates Node trust and operation, Intent, EffectContract, TargetBinding,
   request, delivery, provider revision, and protocol bindings.
7. The Kernel's in-memory `TransactionalEffectEngine` is a domain/test reference,
   not a second production durability authority.

# Production execution path

APEIR exposes two explicitly named execution scopes. Model inference has one
authoritative Rust Kernel path:

```text
NKI request
  -> authentication, contract and deadline validation
  -> Workload IR normalization
  -> Safety Envelope
  -> admission
  -> Scheduler Core policy
  -> resource lease
  -> journaled intent
  -> provider execution
  -> transactional effect gate when applicable
  -> receipt verification
  -> journaled commit or compensation
  -> result, trace and metrics
```

Effectful NKI v3 operations extend that same Kernel path. Distribution hosts
the transport and storage mechanisms but cannot create `StepCommit`:

```text
Kernel TargetBinding admission
  -> external `apeir-remote-provider`
  -> durable Relay spool -> authenticated Node Protocol
  -> signed Node result -> RemoteExecutionReceipt candidate
  -> Kernel signature and binding admission -> OperationReceipt fact
  -> RealityAdapterRegistry observation
  -> ContentAddressedArtifactStore evidence
  -> independent verification -> Kernel MATCH-only commit
```

The remote provider does not observe, verify, or commit. Its spool request
remains durable until a signed result is materialized. An uncertain at-most-once
outcome is returned as `NOUS_NODE_UNCERTAIN_EFFECT` for Kernel to journal as
`RECOVERY_REQUIRED`; it is never automatically replayed.

Compatibility APIs that invoke models must translate to an NKI request. They
may not write the Kernel journal, grant a Kernel lease, select credentials or
mark a model workload complete.

Bounded local effects currently use the Python Runtime service scope:

```text
API or Chat tool request
  -> authenticated AuthorizationContext
  -> ExecutionAuthorizationGate
  -> optional one-use ApprovalBroker lease
  -> central RuntimeCapabilityExecutor
  -> Document / Environment / Network / Simulation / Scientific service
  -> EventStream + ArtifactRegistry evidence
```

This second path is real and governed, but it does **not** traverse the Rust
Kernel. Responses and UI status must report `execution_scope=runtime-service`
and `kernel_traversed=false`. It must not issue, emulate, or persist Kernel
permits, leases, receipts, or journal entries.

## Product execution projection

The Python product Runtime currently projects complex interactive requests
into the durable ProjectStore while the request itself follows the canonical
Runtime Pipeline and Model Gateway. The projection owns conversation-to-project
binding, work-item status, execution attempts, and project checkpoints. It does
not invoke providers, devices, or tools directly.

```text
Chat request
  -> Workload Profile
  -> Project / WorkItem binding
  -> Runtime Pipeline
  -> Gateway and governed tools
  -> verification
  -> attempt + checkpoint + project progress
```

The binding is a compatibility materialized view until project lifecycle is
hosted directly by `nousd`; it must never override a kernel journal outcome.

The Work Harness adds one durable orchestration projection without replacing
either execution scope:

```text
Work Goal + Task Assessment
  -> optional versioned Plan
  -> structured ModelGateway decision
  -> AgentExecutionRuntime model/tool boundary
  -> governed workspace or Runtime capability
  -> recorded observation
  -> completion verification
  -> EventStream projection + workspace checkpoint
```

Resume restores the latest Goal, Plan, observations, artifacts, and Agent
checkpoint, then produces a new deliberation against the current workspace.
The last requested tool action is not replayed automatically.

Tool discovery is progressive:

```text
ToolCatalog category summary
  -> catalog_expand(category)
  -> normalized tool schemas
  -> AgentExecutionRuntime invocation boundary
  -> existing governed executor
```

Discovery and MCP annotations are untrusted metadata. They do not replace the
capability, Workspace, Extension, or Kernel admission performed by the selected
executor.

## Current migration boundary

The Rust daemon is authoritative for model-workload and Reality-effect
admission, durable state, leases, verification acceptance, recovery, and commit.
Engine ABI adapters exist for llama.cpp and vLLM. Python ModelGateway remains a
compatibility client while out-of-process provider execution is moved fully
behind the provider host. A client-side provider response is not a kernel commit;
the compatibility model path must report its outcome through NKI. Local effect
services remain separate and are never described as Kernel-executed.

## Prohibited bypasses

- direct provider calls from product modules;
- tool or device effects outside the transactional effect engine;
- SQLite or journal writes outside `nous-state`;
- optimistic desktop lifecycle mutations;
- secret values in configuration, events, traces or state;
- adaptive policy activation without safety and governance approval.

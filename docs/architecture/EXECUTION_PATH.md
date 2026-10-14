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

Remote spool publication compares and writes the original Operation binding
under the existing per-file lock. Concurrent identical callers share one request;
changed bindings fail closed. Non-finite or invalid timeout inputs are rejected
before persistence. Polling happens outside the publication lock. Recovery reads
the bound cached result without republishing a possibly completed effect; cached
results still require exact Receipt binding and Kernel signature admission.

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

The existing Connector compatibility path honors its declared additional retry
budget. Non-idempotent calls have zero retries, including temporary errors after
an effect; an error response cannot authorize another invocation. Explicitly
idempotent calls keep their bounded retries. This does not turn Connector
metadata or a cached result into independent EffectVerification.

This second path is real and governed, but it does **not** traverse the Rust
Kernel. Responses and UI status must report `execution_scope=runtime-service`
and `kernel_traversed=false`. It must not issue, emulate, or persist Kernel
permits, leases, receipts, or journal entries.

## Governed Distributed Reality path

The M3 runtime-service vertical slice extends the existing coordination and Node
path; it is not a Kernel proof or an Agent-to-Provider shortcut:

```text
Agent Goal -> TaskPlan proposal -> existing durable Workflow
  -> Operation policy and exact bound GovernanceRequest
  -> explicit human Approve Once / Deny when required
  -> pause/resume the original Workflow and Work/Operation
  -> existing Distributed Work -> placement-only Node selection
  -> Node journal and fresh execution admission
  -> current-Operation CredentialContext when needed
  -> Device Provider effect -> existing signed result/OperationReceipt
  -> separately authorized independent read Work -> fresh Observation
  -> deterministic EffectVerification -> MATCH-only Work COMMITTED
```

The model cannot approve or resolve credentials. Scheduling an eligible Node does
not authorize a mutation. Execution success and a Receipt do not prove the effect.
MISMATCH and UNKNOWN remain uncommitted. Recovery first consults persisted
Work/Node evidence; an effect that may already have happened is never blindly
executed again merely because an approval/grant remains valid. See
[Runtime Coordination](RUNTIME_COORDINATION.md),
[State/failure semantics](STATE_OWNERSHIP.md) and
[Reality acceptance](../acceptance/REALITY_ARCHITECTURE_AUDIT.md).

## Bounded Automation consumer

The explicit `simulated-reality` Automation template compiles a structured
TaskPlan with the existing `PlanWorkflowBridge`: read simulated firmware, propose
its update, then independently observe and verify through
`RealityOperationWorkflowHandler`. The existing fixed simulator factory isolates
Node/Device/relay state under `.nous/automation-simulation`; Workflow and current
Governance remain workspace-owned. Only that simulated Node and Device are
enrolled. No real resource is trusted and no approval or grant is issued by the
factory or consumer. This is runtime-service simulation, not physical acceptance.

`AutomationConsumer` stores an immutable definition digest and trigger-to-original
Workflow run relation in the existing `WorkflowStore`. The relation, original
run, inputs and idempotency key commit together before handlers can run. A manual
trigger requires an explicit bounded key. `run_due` consumes at most ten one-shot
UTC due proposals; it never resumes an already consumed due trigger. Repeated
keys and restart reuse the original run and Work. Every distinct firmware Work
requires its own current approval; prior Approve Once cannot authorize another.

CLI execution requires `--simulation`. HTTP management uses the existing live
trusted human session, exact mutation nonce and `control.automation.manage`
permission; listing and history require `control.automation.read`, including
empty, legacy-only and mixed HTTP stores. The existing Governance
human boundary also requires `governance.approve` for the workspace resource.
Service bearer authentication, constructed actor claims, `approved_steps`, a
legacy `enabled` flag and arbitrary text/capabilities cannot supply this authority.
Management revalidates before and after simulator startup; the original Operation
revalidates again at Node admission. Cancellation uses the original Governance
interruption and Workflow cancellation; an effect that may already have occurred remains
unresolved until evidence is reconciled. Explicit `reconcile` reads the original
Node journal/receipt and acquires independent observation without entering a
mutation handler. History verifies original CAS references and the committed
Work's semantic binding to the original Workflow definition, Governance request,
Capability, Device, input, signed receipt and independent Observation. The exact
original CAS EffectVerification must match the Work, and the existing v1 verifier
must reproduce its semantic fields from that receipt and Observation. Historical
signature checks omit transport clock freshness; later grant revocation does not
invalidate lawful recorded evidence. History opens no transport and performs no
new execution admission, provider call or effect. These local integrity checks
do not resist a host owner rewriting all stores and signing keys. MISMATCH and
UNKNOWN cannot commit Work.

Before opening transport, the consumer checks every unresolved effectful Work in
the shared isolated Automation relay store against its original Node journal.
Node terminal records use `COMPLETED` or `FAILED`, distinct from Controller Work
states. The original journal key, Work/Operation, Node assignment, dispatch/request
digest and bound receipt must agree with existing Governance and relay evidence.
Missing, malformed, incomplete or changed evidence fences the run as UNKNOWN
before delivery opens. An unbound pre-start `CANCELLED` record cannot resolve an
uncertain effect. Starting another Automation cannot reopen unsafe original
delivery from the shared spool. Valid terminal evidence is still reconciled
through the existing signed Node result path and independently observed; the
preflight issues no authority and cannot commit an effect.

The existing Operations Console now consumes these same HTTP endpoints. Its
Automation pane displays structured simulated definitions, original run history,
pending approvals and receipt/observation/verification evidence. Approve Once or
Deny addresses the original approval, then resumes that exact run. An uncertain
trigger response retains its original key and queries persisted history instead
of creating another trigger. Session expiry, logout and Controller configuration
changes invalidate retained views and mutations, including an address/token ABA
change. The browser stores no private run or identity state; simulator and
runtime-service labels do not imply Kernel or physical execution.

The existing free-text Automation JSON stays `UNQUALIFIED` configuration. A
background timer, recurring Cron/event/webhook triggers, general executable Skill
workflows and a semantic action recorder are unimplemented. Other production
Workflow handlers require their own trusted factory and exercised contracts;
the consumer introduces no general capability executor or model fallback. See
the [runnable Workflow example](../../examples/hello_workflow/README.md).

## Product execution projection

RuntimePipeline dispatch requires the existing Gate to return both EXECUTE and
`allowed=True`. RECOMMEND, UNKNOWN, invalid decisions and unavailable Governance
cannot invoke a product handler, including on preview/CLI surfaces. The existing
workspace resolver binds file-tool scope before dispatch; request metadata
`workspace_path` cannot replace the resolved resource. Handler registration and
an admitted model call still grant no authority for downstream effects.
The Runtime HTTP entry initializes that Orchestrator with the configured host
root; a public selector remains subject to the same resolver boundary.

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

Work result admission requires explicit, agreeing boolean `ok`, `success` or
`passed` fields. Error, contradictory and unknown envelopes cannot become a
successful observation or verification merely because the handler returned.
Scalar payloads retain their data without an invented success flag. An ambiguous
effect response or an exception after dispatch retains the original pending
action for recovery; a recovery discovery flag cannot override invalid evidence.
A completed failed write, execute or unknown tool response also retains recovery:
failure alone cannot prove that no effect occurred. Only the selected host
Workspace runtime and exact persisted original proposal/approval binding can
establish the existing pre-effect proposal pause. Provider-returned hints cannot
authorize a new attempt.
Process recovery also requires the selected canonical ProcessSession owner and
the original pending Work/action/invocation binding. The host-prepared command,
workspace cwd and environment profile digests are persisted before dispatch;
recovery compares them with the original session and host specification, then
uses the existing process identity observation. A generic `found=true` response,
another valid host for the same Work/action, or a missing legacy binding remains
RECOVERY_REQUIRED. Recovery neither launches nor controls a process, and a
changed Work checkpoint (including cancellation) stops continuation. This does
not expose the currently unsupported `shell_start` tool or qualify a live PTY.
Unplanned tool Work still passes the existing recorded-work completion gate.
Coding verification uses current Plan evidence: tests and diff review must follow
the latest recorded change, and a process started before it does not gain
freshness from later polling. Test success requires EXITED with exact integer
exit code zero. These records remain software evidence, not an independent
Reality Observation or physical-effect commitment.

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

Skill disclosure follows the same boundary:

```text
SkillRegistry summary
  -> skill_search / skill_list
  -> skill_load(skill_id)
  -> instructions + packaged resource names in durable Work context
  -> governed Tool or Environment execution
```

Loading a Skill does not execute its scripts and does not grant its requested
capabilities. Installed packages retain Extension provenance and a pinned
Artifact Runtime source-bundle reference.

Runtime Context delivery uses the same resolved workspace and current live
identity as the request. ContextGuard admits source access before collection;
serialized actor metadata is not authentication. Whole selected items retain
source/permission/version provenance through the Gateway input manifest. Required
context that exceeds its admitted bound blocks dispatch rather than silently
clipping constraints. Before a later Chat model invocation, the original
snapshot checksum, identity, workspace, purpose and current item permissions
are revalidated. An access change pauses the existing Agent checkpoint. Neither
a context snapshot nor an incremental update grants authority, proves source
freshness or certifies a Provider received the input.

Web execution uses the existing governed network boundary:

```text
web_search / web_fetch
  -> network.fetch capability admission
  -> ResearchEvidenceService
  -> SSRF-resistant WebGateway
  -> normalized untrusted response
  -> ContentAddressedArtifactStore evidence
  -> bounded model observation + immutable evidence_ref
```

If the network request or evidence write fails, the Web Tool returns failure and
does not publish a successful observation without its evidence artifact.

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

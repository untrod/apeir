# Runtime coordination

APEIR coordinates long-running intelligent work without granting a model direct
execution authority. The coordination layer binds existing planning, workflow,
event, and Compute Mesh contracts; it does not replace them.

## Authority path

```text
AgentSession
    -> TaskPlan
    -> durable Workflow
    -> capability handler
    -> local or Distributed Work
    -> Governance and explicitly selected execution scope
    -> receipt, evidence, and verification
```

An `AgentSession` may propose a plan and observe outcomes. It cannot dispatch a
tool, write to a Node, forge a receipt, or commit an artifact. Those effects
remain owned by the established capability and Distributed Work paths.

## AgentSession

`AgentSession` is a durable coordination record. It stores references and
bounded observations rather than copying the authoritative state of other
subsystems. Its durable fields include:

- agent and model identity;
- objective and scoped context;
- budget and policy scope;
- subscribed event patterns;
- plan revision history;
- Workflow and Work references;
- pending approvals;
- bounded observations and the final result.

Session state follows this lifecycle:

```text
CREATED -> ACTIVE -> PLANNING -> SUBMITTING_WORK -> OBSERVING -> COMPLETED
                    ^                                  |
                    |------------ REPLANNING ----------|

ACTIVE / OBSERVING -> WAITING -> OBSERVING
any non-terminal state -> FAILED or CANCELLED
```

A failed Workflow is recorded as an observation. The session remains in
`OBSERVING` so a caller can submit an explicit revised plan. The coordinator
does not silently retry effects.

## Plans and Workflows

The coordination layer uses the existing `TaskPlan` contract. A plan remains a
proposal: it contains steps and dependencies but has no execution authority.
`PlanWorkflowBridge` compiles it into the existing durable Workflow Runtime,
which provides dependency ordering, checkpoints, bounded retries,
compensation, and approval gates.

Workflow capability handlers are the execution boundary. A handler may use an
existing local capability or `DistributedWorkflowAdapter`. The latter creates
durable Distributed Work, selects an eligible Node deterministically, verifies
the returned receipt and artifact digests, and commits only verified results.

## Events

Workflow events are persisted in the per-run `EventStream`. The same events can
also be projected onto `RuntimeEventBus` for live subscribers. The durable
per-run copy remains authoritative; the projection is not a second state
store.

An active session may subscribe to bounded event patterns such as `node.*` or
`artifact.*`. A matching event wakes a waiting session into `OBSERVING` and is
stored once by event ID. Subscriptions are reconstructed from the session store
after Runtime restart.

## Persistence and recovery

Sessions are stored in `.nous/agent_sessions.db`. Workflow definitions, runs,
and checkpoints remain in `.nous/workflows.db`; Distributed Work and artifacts
remain in their existing stores. Recovery therefore reloads references to
authoritative records rather than replaying an unknown effect.

The coordination layer deliberately does not persist model secrets, raw hidden
reasoning, Node private keys, or capability credentials.

## Current scope

The coordination contract established at M3.1 remains authoritative:

- durable Agent sessions;
- existing plan-to-Workflow compilation;
- approval pause and resume on the same Workflow run;
- explicit observation and replan semantics;
- event-driven wake-up with durable subscription definitions;
- multi-step, multi-node artifact orchestration through existing handlers.

M3.2 reliability, M3.3 Reality, M3.4 Governance/credentials, M3.5 Control Plane
and M3.6 SDK extend this same path. For Reality mutations, approval pauses the
original run and exact Work/Operation. Approve Once resumes it without silently
replanning. Delivery/Node journals precede execution; lost-response recovery
reconciles persisted evidence and acquires a new independent Observation.
MISMATCH and UNKNOWN cannot commit. See the [Reality audit](../acceptance/REALITY_ARCHITECTURE_AUDIT.md)
and [Security Contract](SECURITY_CONTRACT.md). Physical acceptance remains PENDING.

## Work Harness

`apeir work` is the product-level entry for goal-directed work. The Harness is
a thin composition layer over existing Runtime owners:

```text
Work request
  -> TaskAnalyzer
  -> Goal + optional versioned Plan
  -> ModelGateway structured decision
  -> AgentExecutionRuntime invocation boundary
  -> existing governed tool/capability runtime
  -> observation + verification
  -> EventStream projection + SQLite checkpoint
```

The Harness is not an authority. Tool availability, model output, plan metadata,
and skill guidance cannot grant permission or bypass Kernel/Runtime admission.
Simple tasks may complete without a Plan. Long-running runs persist Goal, Plan
revision history, observations, artifacts, blockers, and Agent checkpoints in the
workspace and reassess current state before acting after resume.

The Desktop Task Center reads those same Work checkpoints through a bounded
projection: state, current step, versioned Plan tasks, progress, and Artifact
references remain owned by `WorkHarness`. Desktop pause and cancel requests
write back through `WorkHarness`; the UI does not maintain a competing Work
state machine.

`ToolCatalog` is the Work-facing discovery projection over existing tool
runtimes. It publishes compact capability categories first and exposes full
schemas only through `catalog_expand`. Invocation is delegated to the original
Workspace or governed Extension/MCP executor; catalog metadata always carries
`authority=none` and cannot make an unavailable or unauthorized action legal.
The first concrete providers expose bounded workspace file discovery, read-only
Git queries when strong sandboxing is available, and the existing workspace
ContentAddressedArtifactStore. Catalog inspection itself does not initialize an
Artifact store or execute a process.

`SkillRegistry` is the corresponding progressive Skill projection. It reads
legacy JSON Skills through the existing Extension adapters, discovers project
and user `SKILL.md` packages, verifies installed packages through
`ExtensionRegistry`, and exposes catalog entries as untrusted summaries. Full
instructions and resource names enter Work context only after `skill_load`.
Installation never executes packaged scripts: the existing Extension supply
chain path validates and copies the package, while a deterministic bundle is
stored and pinned in the existing workspace Artifact Runtime. Declared
capabilities remain requests with `authority=none`.

`WebRuntime` provides the Work-facing `search` and `fetch` seam. Its default
executor traverses the existing `network.fetch` capability and
`ResearchEvidenceService`/`WebGateway`; it does not issue direct HTTP requests.
Every successful response is classified as untrusted external content and
closed into the workspace `ContentAddressedArtifactStore` before a successful
Tool result is returned. The model-facing response is bounded, while the full
redacted evidence remains available by digest.

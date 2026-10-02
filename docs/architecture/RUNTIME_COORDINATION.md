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
    -> policy and Kernel boundary
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

This layer establishes the M3.1 coordination boundary:

- durable Agent sessions;
- existing plan-to-Workflow compilation;
- approval pause and resume on the same Workflow run;
- explicit observation and replan semantics;
- event-driven wake-up with durable subscription definitions;
- multi-step, multi-node artifact orchestration through existing handlers.

Resource graphs, device lifecycle, leases, disconnected execution, effect
verification, and expanded governance remain separate follow-on gates. They
must not bypass the authority path described above.

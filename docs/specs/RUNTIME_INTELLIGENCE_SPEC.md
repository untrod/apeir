# Runtime Intelligence Spec

Nous is an Open Intelligence Runtime.

P5 introduces a policy-driven decision layer for runtime behavior. The goal is not to make a hidden scheduler. The goal is to make runtime choices explicit, explainable, replayable, and auditable.

## Scope

Runtime Intelligence decides:

- whether retrieval should run
- whether memory, provider, model, capability, execution, retry, fallback, or approval paths should be selected
- which provider candidate is preferred for the current context
- how retry and fallback should react to a classified failure

The first version is deterministic. It does not execute arbitrary expressions and it does not let a model bypass policy validation.

## Decision Contract

The core contract is:

- `DecisionRequest`
- `DecisionContext`
- `RuntimeDecision`
- `DecisionCandidate`
- `DecisionReason`
- `DecisionConstraint`
- `DecisionOutcome`

Every decision includes:

- stable `decision_id`
- `task_id`
- `decision_type`
- selected outcome and alternatives
- confidence
- policy identity and version
- input snapshot
- reason codes

The same request and policy set should produce the same decision.

## Policy Engine

Policy types:

- `StaticPolicy`
- `RulePolicy`
- `CompositePolicy`
- `FallbackPolicy`
- `OverridePolicy`

Rule policy conditions use a restricted structured DSL:

```json
{
  "field": "context.task_kind",
  "operator": "in",
  "value": ["research", "question"]
}
```

Supported operators are `eq`, `neq`, `in`, `contains`, `exists`, `gt`, `gte`, `lt`, and `lte`.

Policy priority order:

- explicit override
- higher priority registered policy
- runtime default

The engine never uses `eval`.

## Built-in Decisions

Retrieval decision:

- disables retrieval when no active generation is available
- enables retrieval for project, document, research, code, and repository-oriented prompts
- includes backend, generation, context budget, query, and reason codes in metadata

Provider decision:

- scores candidates using capability fit, health, historical success, locality, and latency
- returns selected provider and fallback chain

Recovery decision:

- classifies failures as `TRANSIENT`, `PERMANENT`, `POLICY`, `AUTH`, `RATE_LIMIT`, `TIMEOUT`, `BACKEND`, `VALIDATION`, `SECURITY`, or `USER_CANCELLED`
- maps categories to retry, retry once, fallback, or stop

## History And Replay

Decision history is stored under `.nous/decisions/`:

- `decisions.jsonl`
- `outcomes.jsonl`
- `metrics.jsonl`

Replay uses the saved input snapshot and the current policy engine. This supports regression checks and policy change review.

## CLI And Inspector

Commands:

- `nous decision test`
- `nous decision policy-test`
- `nous decision list`
- `nous decision show <decision_id>`
- `nous decision explain <decision_id>`
- `nous decision replay <decision_id>`
- `nous decision compare <left_id> <right_id>`
- `nous decision metrics`
- `nous inspect decisions`

Read-only API:

- `GET /api/inspector/decisions`

## Pipeline Integration

`DecisionPipeline` creates a retrieval runtime decision before planning. The decision is exposed in:

- `PipelineResult.decisions`
- `Plan.metadata["runtime_decisions"]`

This does not change task execution behavior yet. It makes decisions available to TaskGraph and later execution policies through a stable data contract.

## Non-goals

P5 does not add autonomous policy mutation.
P5 does not implement device orchestration.
P5 does not introduce model-based policy execution.
P5 does not replace TaskGraph execution.

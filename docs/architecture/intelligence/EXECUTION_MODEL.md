# Execution Model v1.2

## Complete Chain

```
Request
  ↓
Policy Check        <- ALLOW / DENY / REQUIRE_APPROVAL / SANDBOX
  ↓
Goal Analysis       <- Understand intent
  ↓
Planning            <- Decompose into tasks
  ↓
Task Graph          <- Build dependency DAG
  ↓
Scheduling          <- Organize into waves
  ↓
Capability Resolution  <- Find matching capabilities
  ↓
Provider Routing    <- Select best provider
  ↓
Execution           <- Run through provider
  ↓
Evaluation          <- Score against criteria
  ↓
Experience Update   <- Store for future optimization
  ↓
Audit               <- Record decision trail
```

## Trace Propagation

Every step shares a trace ID for end-to-end observability.

```python
from nous_runtime.kernel.tracing import TraceContext, ExecutionTimeline

with TraceContext(goal_id="goal_001") as ctx:
    timeline = ExecutionTimeline(trace_id=ctx.trace_id)
    timeline.add("planning", capability_id="model.reason")
    timeline.add("executing", provider_id="openai", duration_ms=450)
    # All operations correlated by ctx.trace_id
```

## Error Flow

Errors propagate with structured codes:
- `NOUS_CAPABILITY_NOT_FOUND` -> try alternative capability
- `NOUS_PROVIDER_UNAVAILABLE` -> route to backup provider
- `NOUS_TIMEOUT` -> retry with backoff
- `NOUS_PERMISSION_DENIED` -> require human approval

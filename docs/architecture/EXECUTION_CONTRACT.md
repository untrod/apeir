# Execution Contract v1.0

## Pipeline

```
Goal
  ↓
Plan              <- Decompose goal into tasks
  ↓
Task Graph        <- Build dependency graph
  ↓
Schedule          <- Assign timing + resources
  ↓
Dispatch          <- Route to executor
  ↓
Execute           <- Run via Provider
  ↓
Evaluate          <- Check results against success criteria
  ↓
Experience        <- Record for future planning
```

## Goal

```yaml
metadata: {id, kind: "Goal", ...}
spec:
  description: "string"     # What to accomplish
  success_criteria: []      # How to know it's done
  constraints:
    max_steps: 50
    max_time_seconds: 3600
    require_approval: false
status:
  phase: "pending"          # pending | planning | active | completed | failed | cancelled
```

## Plan

```yaml
metadata: {id, kind: "Plan", ...}
spec:
  goal_id: "goal_..."
  tasks: []
  strategy: "sequential"    # sequential | parallel | dependency_graph
status:
  phase: "building"         # building | ready | executing | completed | failed
```

## Task

```yaml
metadata: {id, kind: "Task", ...}
spec:
  plan_id: "plan_..."
  capability_id: "model.reason"
  params: {}
  depends_on: []            # Task IDs that must complete first
  retry_policy:
    max_retries: 3
    backoff: "exponential"
status:
  phase: "pending"          # pending | scheduled | running | completed | failed | cancelled
```

## Execution

```python
# Execution is always:
#   capability_request -> provider_selection -> execution -> audit

def execute_task(task: Task) -> ExecutionResult:
    # 1. Security admission
    admission = security.check(task.capability_id, task.params)
    if admission != "ALLOW":
        return ExecutionResult(denied=True, reason=admission)

    # 2. Provider selection
    provider = router.select_provider(task.capability_id)

    # 3. Execution
    result = provider.invoke(task.capability_id, **task.params)

    # 4. Audit
    audit.log(task, provider, result)

    # 5. Evaluate
    evaluation = evaluator.evaluate(task, result)

    return ExecutionResult(task=task, result=result, evaluation=evaluation)
```

## Rules

1. Every execution has a trace ID
2. Every execution is audited
3. Every execution goes through security admission
4. Provider selection is pluggable (round-robin, cost-based, latency-based)
5. Failures are recorded as Experience for future planning
6. The LLM is ONE participant in planning, not the ONLY planner

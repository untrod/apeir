# Planner Engine 2.0

## Pipeline

```
User Goal -> Goal Understanding -> Planning -> Task Graph ->
Capability Resolution -> Provider Selection -> Execution -> Evaluation -> Experience
```

## Goal Model

```yaml
goal_id: goal_YYYYMMDD_XXXXXXXX
objective: "Analyze this project"
status: created -> understanding -> planning -> executing -> completed
constraints:
  max_steps: 10
  timeout: 300
  require_approval: false
```

## Plan Model

A Plan decomposes a Goal into Tasks with dependencies.

```yaml
plan_id: plan_YYYYMMDD_XXXXXXXX
goal_id: goal_...
tasks:
  - task_id: task_...
    description: "Inspect repository structure"
    capability_id: device.shell
    depends_on: []
  - task_id: task_...
    description: "Analyze code architecture"
    capability_id: model.reason
    depends_on: [task_...]
  - task_id: task_...
    description: "Generate report"
    capability_id: model.reason
    depends_on: [task_..., task_...]
```

## Task Graph

DAG with dependency edges:
- Sequential: A -> B -> C
- Parallel: A, B -> C
- Mixed: A -> B, A -> C -> D

## Scheduler

Waves-based execution: each wave contains parallel-ready tasks. Waves execute sequentially.

## Dispatcher

Routes each task through: Capability Resolution -> Provider Selection -> Execution -> Experience Recording

## Evaluator

Scores plans on:
- Completion rate (0.6 weight)
- Error-free execution (0.2 weight)
- Time budget adherence (0.2 weight)

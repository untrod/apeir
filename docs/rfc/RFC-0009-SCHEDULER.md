# RFC-0009: Multi-Level Scheduler

- **Status:** Draft | **Depends on:** RFC-0001, RFC-0003

## Three-Level Architecture

1. **Global Placement Scheduler** — Node, Device, Engine, Model Revision, Parallelism, Resource Lease, Data/KV location
2. **Workflow Scheduler** — DAG, Agent Program, Critical Path, Parallel, Conditional, Tool Deps, Human Approval, Checkpoint
3. **Phase Scheduler** — Encoder, Prefill, Decode co-location vs disaggregation

## 10 Baseline Policies

FIFO, Priority, WeightedSum, Multiplicative, Pareto, CacheAware, DeadlineAware, CriticalPathAware, ContextualBandit, MOBO.

All policies implement `SchedulerPolicy` trait. See `kernel/crates/nous-scheduler/src/policy.rs`.

## Selection Output

Every selection returns: candidate set, rejection reasons, score breakdown, confidence interval, prediction source, out-of-distribution flag, fallback strategy.

## Experiment Framework

All scheduling algorithms in `experimental/` with feature flags. Must compare against baselines. No single algorithm hard-coded as kernel logic.

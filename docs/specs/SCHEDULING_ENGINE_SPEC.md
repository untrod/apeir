# Scheduling Engine Spec

Nous is an Open Intelligence Runtime.

## Pipeline

The deterministic scheduler executes these phases:

1. candidate discovery
2. eligibility validation
3. hard-constraint filtering
4. policy evaluation
5. Pareto reduction
6. normalization
7. contextual scoring
8. stable ranking
9. selection
10. fallback-plan generation
11. explanation generation

The scheduler does not require an LLM.

## Hard Constraints

Supported constraints include:

- required capability
- modality
- context-window requirement
- tool-calling requirement
- structured-output requirement
- maximum cost
- maximum latency
- locality requirement
- privacy requirement
- data-residency requirement
- allowed and denied providers
- allowed and denied models
- risk ceiling
- approval requirement
- availability requirement

Hard constraints are evaluated before selection. A forced candidate must still pass non-overridable safety constraints.

## Policy Inputs

Policies can express:

- deny
- prefer
- avoid
- require approval
- force candidate

Policy traces are recorded in `SchedulingResult`.

## Integration

Initial integrations:

- retrieval strategy selection
- deterministic provider candidate evaluation
- recovery strategy candidate evaluation
- CLI scheduler simulation
- read-only Inspector decision views

Live provider execution routing remains compatible with existing behavior.

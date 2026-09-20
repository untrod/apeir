# APEIR Engineering Loop

## Research question

Can a governed runtime improve the reliability, recoverability, and evidence
coverage of AI-assisted engineering work that uses existing professional
tools?

APEIR does not replace an EDA system, compiler, instrument driver, model, or
manufacturing service. It coordinates their effects and preserves the state
needed to verify what actually happened.

## Boundary

```text
intent -> planner -> APEIR contracts -> adapter -> professional tool
                     |                         |
                     +-> policy/admission      +-> artifacts/observations
                     +-> task state            +-> independent verification
                     +-> receipt/evidence <----+
```

The first experiment may use adapters for a hardware-as-code frontend, KiCad
CLI, a SPICE CLI, ESP-IDF, esptool, and a small SCPI surface. An adapter invokes
and observes a tool; it does not become a new Kernel subsystem.

## Existing contracts

Engineering work maps to the 0.1 Task, Capability, Artifact, Event, Policy, and
OperationReceipt contracts. Design sources, schematics, reports, firmware,
manufacturing files, measurements, and logs are artifacts. Tool invocations
are governed effects. Verification outcomes and raw observations are evidence
references attached to receipts.

The research implementation must not create a second authority path or write
Kernel-owned state directly.

## Expected and observed effects

Experiment 001 represents an expected effect as data associated with a task
operation. Examples include a boot marker, an allowed voltage interval, or a
required DRC result. The corresponding observation records the verifier, raw
evidence artifact, timestamp, and measured value.

The comparison result is one of `MATCH`, `PARTIAL`, `MISMATCH`, or `UNKNOWN`.
This is initially an experiment-layer payload on existing receipts. Promotion
to a Kernel contract requires evidence from repeated experiments that the
existing representation cannot preserve a required invariant.

## Failure semantics

A tool exit code, timeout, cancellation, failed verifier, missing observation,
or expected/observed mismatch is a normal recorded outcome. The planner may
propose a recovery step, but that step receives a new admission decision and a
new receipt. Model text alone never changes a failed state to success.

## Promotion rule

Research code is eligible for promotion only when Experiment 001 demonstrates
measurable improvement over both ungoverned baselines in false-success rate,
recovery, reproducibility, or evidence coverage. Device count and feature count
are not promotion criteria.

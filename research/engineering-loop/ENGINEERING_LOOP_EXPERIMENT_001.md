# Engineering Loop Experiment 001

Status: `not_run`

## Objective

Evaluate whether APEIR adds measurable value to a small, reproducible hardware
engineering workflow without implementing a new EDA engine or modifying the
0.1 Kernel authority boundary.

## Reference task

Produce and verify the source design, schematic, PCB checks, BOM, firmware,
fabrication package, and test specification for a small ESP32-S3 sensor board
with USB-C power, a 3.3 V rail, one I2C temperature sensor, a status LED, a
button, and debug pads.

Physical manufacturing is outside the initial run. The first run uses a
deterministic simulated fixture. Physical bring-up is allowed only after the
digital experiment passes its acceptance criteria.

## Compared systems

- A: model-assisted shell and KiCad workflow without APEIR;
- B: model plus the selected hardware-as-code frontend without APEIR Kernel;
- C: the same tools through APEIR admission, state, artifacts, receipts, and
  verification.

Inputs, model policy, tool versions, time budget, and success criteria must be
held constant across the three systems.

## Deterministic fault set

1. 3.3 V rail reports 0 V.
2. The I2C device is missing.
3. Firmware enters a boot loop.
4. The pull-up value violates the declared design constraint.

Each run must observe the fault, propose or perform an admitted action, and run
an independent verifier. Test fixtures may not be edited during a run.

## Required evidence

- immutable input and output artifact hashes;
- tool name, version, arguments, environment, exit status, and duration;
- policy decision and effect receipt;
- expected effect and observation payloads;
- raw ERC, DRC, firmware build, serial, and simulated measurement outputs;
- final verifier result and every human intervention.

## Metrics

The benchmark records completion, unsupported-action rate, false-success rate,
recovery rate, verification coverage, human interventions, engineering
iterations, token usage, model cost, compute time, and tool runtime.

## Acceptance

The experiment passes only if system C completes the deterministic workflow,
detects every injected fault, records no unsupported effect as successful, and
improves at least one primary metric over both baselines without regressing
false-success rate or evidence coverage.

If these conditions are not met, the result is published as failed or
inconclusive and the research scope is not expanded.

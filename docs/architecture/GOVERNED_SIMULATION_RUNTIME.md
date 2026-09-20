# Governed Simulation Runtime

Status: P19 integrated-host implementation (2026-09-01)

## Purpose

The Simulation Runtime gives Nous a typed, governed and reproducible scientific
execution path. It composes the existing Runtime, Governance, Environment
Runtime, EventStream and ArtifactRegistry authorities; it does not create a
parallel scheduler, policy engine, event log or artifact store.

The first stable reference model is `spacecraft-thermal/v1`, executed with a
deterministic explicit-Euler solver. The contract and provider boundary are
model-neutral so later scientific providers can be added without weakening the
governance boundary.

## Ownership and execution flow

- A caller proposes a simulation contract.
- Runtime strictly validates and persists the immutable contract.
- Governance authorizes create, run, replay and cancel mutations.
- Runtime creates and starts an owned `nous.environment/v1` environment.
- A bounded worker receives a staged canonical input and writes only to that
  environment's output directory.
- Runtime validates outputs, registers artifacts, records reproducibility
  metadata and destroys the owned environment.
- EventStream is the authoritative lifecycle history.
- Desktop is an authenticated control and inspection surface.

All API mutations require `runtime.execute` and `simulation.compute`.
One-use approvals are consumed before handlers run.

## Stable contracts

P19 registers:

- `nous.simulation/v1`;
- `nous.simulation-run/v1`.

Unknown fields are rejected. IDs, model/provider/environment combinations,
solver settings, parameter names, sweep dimensions, numerical tolerances and
resource budgets are bounded. The current provider accepts only
`local-deterministic`, `local-sandbox`, `explicit-euler` and no network.

The resource contract bounds CPU, memory, wall time, cases, retries and output
bytes. Retries are limited to 0-3 and every retry is visible as
`simulation.retrying`. Parameter sweeps use a deterministic Cartesian plan
and reject plans that exceed the declared case budget. Integration is capped at
100,000 steps per case.

Persisted simulation and run records contain canonical SHA-256 digests and fail
closed when tampered.

## Reproducibility

Every completed run captures:

- code, model, input, parameter and contract hashes;
- environment contract hash and environment fingerprint;
- staged input hash and optional container image digest;
- Python and detected scientific dependency versions;
- deterministic seed;
- Runtime, Kernel, NKI and Event schema versions;
- CPU, GPU, architecture and operating system;
- capture timestamp;
- absolute and relative numerical tolerances.

Packaged one-file builds compute a stable worker code hash from loaded Python
code objects and the model version. This avoids relying on a source file that
does not exist beside a PyInstaller executable. Native packaged validation
found the original source-path assumption; it was fixed and covered by focused
tests and the final packaged replay.

Replay executes the frozen simulation contract again, compares the result
digest and numerical values, and records whether the contract matches and all
values remain within tolerance. It never silently substitutes a different
model, input, provider or tolerance.

## Outputs and evidence

A successful run produces and registers:

- `result.json` with per-case summaries;
- `series.csv` with the deterministic time series;
- `temperature.svg` with a portable plot;
- a run manifest artifact containing the reproducibility record.

Artifact bytes are bounded and independently SHA-256 verified. Cancellation,
timeout, worker failure, exhausted retry and tamper paths are persisted. Owned
environments are stopped and destroyed even when work fails.

The lifecycle starts with the shared run envelope and emits
`simulation.started`, zero or more `simulation.retrying`, artifact events,
then `simulation.completed` or `simulation.cancelled` /
`simulation.failed`. Replay additionally emits `simulation.replayed`.

## Desktop workbench

The Simulation Workbench supports:

- parameter and sweep editing;
- explicit creation and execution;
- one-use approval retry;
- active cancellation;
- replay and tolerance inspection;
- case metrics, artifact links and reproducibility metadata;
- an explicit Windows integrated-host containment warning.

The UI does not claim hard isolation that the provider cannot supply.

## Security and honest boundaries

The worker receives no network capability, no shell string and no unbounded
resource request. Relative paths are normalized as forward-slash paths and
cannot escape the Environment work directory. Staging and collection are
bounded, atomic where applicable and reject symlinks. Runtime verifies record
and artifact digests before trusting them.

On the current Windows 10 x64 machine, local evidence is
`native-packaged-windows-10-x64-integrated-host`. It does not claim a hard
network or filesystem namespace. Docker and Podman are unavailable and WSL2 is
not operational, so no OCI execution evidence is claimed. The installer is
built but its install/uninstall lifecycle has not been executed. No GitHub
upload, tag or release was performed.

## Validation anchor

The machine-readable native evidence is
`artifacts/build-logs/p19-simulation-native-validation-20260901.json`.
The human-readable release report is
`docs/archive/pre-apeir/release-evidence/p19/SIMULATION_RUNTIME_NATIVE_REPORT.md`.

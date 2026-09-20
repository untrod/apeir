# Governed Scientific Runtime

Status: P20 integrated-host implementation (2026-09-01)

## Purpose

The Scientific Runtime closes the governed path from a completed Simulation
run through independent numerical analysis, Claim/Evidence creation, and
render-verified DOCX/PDF reporting. It composes the existing SimulationRuntime,
EnvironmentRuntime, Governance, EventStream, ArtifactRegistry,
ClaimEvidenceGraph and DocumentRuntime authorities. It does not create a
parallel execution, evidence, document, event or artifact subsystem.

The first reference task is `spacecraft-thermal-analysis/v1` over completed
`spacecraft-thermal/v1` runs.

## Stable contracts and API

P20 registers and enforces:

- `nous.scientific-analysis/v1` for immutable analysis requests;
- `nous.scientific-result/v1` for persisted results;
- `scientific.analyze` as an authenticated, privileged, local-write capability;
- `/api/v1/scientific/status`, `/api/v1/scientific/analyses`, and analysis
  detail/create routes.

Unknown fields are rejected. Simulation run identifiers, analysis type,
reference solver, report formats and tolerance are bounded. The current
reference solver is `scipy.solve_ivp` with DOP853; tolerance is constrained
between `1e-6` and `10 K`, with `0.05 K` as the default. Mutations require
`runtime.execute` and `scientific.compute` and consume one-use approvals before
the handler executes.

## Provider qualification

The status and result contracts report availability, version, capabilities and
error details separately for:

- NumPy: arrays, statistics and error metrics;
- SciPy: ODE reference integration and numerical validation;
- pandas: bounded CSV/table inspection;
- SymPy: symbolic thermal equation and radiative equilibrium;
- Matplotlib: headless PNG comparison plots.

Analysis fails closed if any required provider is unavailable. The final frozen
Windows package qualified NumPy 2.4.5, SciPy 1.17.1, pandas 3.0.3, SymPy
1.14.0 and Matplotlib 3.10.9.

## Execution and evidence flow

1. Runtime loads a completed Simulation run and verifies its record digest.
2. `result.json` and `series.csv` are checked against their registered
   Artifact identity and SHA-256.
3. Runtime creates an owned local-sandbox Environment with no network, bounded
   CPU/memory/time and no device access.
4. Input, Simulation artifacts and the scientific worker are staged.
5. The worker uses pandas/NumPy/SciPy/SymPy/Matplotlib to compute the
   independent analysis and writes JSON, CSV and PNG only inside its output
   directory.
6. Runtime collects bounded outputs, destroys the Environment, verifies the
   reference tolerance and registers all three Artifacts.
7. Each case creates a Claim. The Simulation result is `derived_from` evidence
   and the independent analysis Artifact `supports` the Claim.
8. DocumentRuntime creates and structurally verifies a DOCX and PDF technical
   report.
9. A digest-protected scientific result record and canonical event history are
   persisted.

Artifact-only evidence is allowed only after ArtifactRegistry validation.
Snapshot evidence still requires its Source authority. A supported scientific
Claim therefore remains traceable without fabricating a web Source.

## Determinism, failure and packaging

The worker records a stable code hash, exact provider versions, equation,
equilibrium expression, per-case statistics, reference error and safety margin.
Input and output bytes are bounded; symlinks and paths outside the active
workspace are rejected. Tampered Simulation Artifacts or scientific records
fail before trusted reuse. Owned Environments are released on both success and
failure.

Native validation found and fixed two frozen-package defects:

- PyInstaller excluded `unittest` and `pydoc`, which current SciPy/Matplotlib
  import paths require. The final spec excludes only `tkinter`.
- The hidden `scientific-worker` command was not registered in the Typer entry
  point. It is now registered and covered by a CLI regression test.

The lifecycle uses the shared run envelope and scientific events:
`scientific.started`, three `artifact.created` events,
`scientific.reference_verified`, Claim events,
`scientific.claims_created`, `scientific.report_rendered`,
`scientific.completed`, then `run.completed`.

## Desktop workbench

The Simulation Workbench now loads Scientific Runtime/provider status, lists
prior analyses and submits approval-gated analysis requests. It displays case
count, reference error, Claim count, Environment cleanup state and verified
DOCX/PDF status. The UI is an authenticated control surface over Runtime APIs;
it does not execute scientific libraries directly.

## Honest boundaries

Evidence on this Windows 10 x64 host is
`native-packaged-windows-10-x64-integrated-host`. The local sandbox uses
process and Job Object controls but is not a hard network/filesystem namespace.
Docker and Podman are unavailable and WSL2 is not operational, so no OCI, Linux
container, GPU, hardware-in-the-loop or production evidence is claimed. The
installer was built but not executed. No GitHub upload, tag, release or other
remote mutation was performed.

## Validation anchors

- `artifacts/build-logs/p20-scientific-native-validation-20260901.json`
- `docs/archive/pre-apeir/release-evidence/p20/SCIENTIFIC_RUNTIME_NATIVE_REPORT.md`
- `artifacts/windows-x64/release-manifest.json`

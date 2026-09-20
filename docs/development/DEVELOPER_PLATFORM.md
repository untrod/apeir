# Developer Platform

The Nous Developer Platform is a control surface over the Runtime. It does not
own a second scheduler, project database, model registry, or execution path.

## Surfaces

The desktop `Develop` page provides five views:

- **Workbench** provides workspace-scoped file browsing, UTF-8 editing, unified diff preview, compare-and-swap atomic writes, and fixed-profile strict execution.
- **Research** provides approval-gated public web fetch, persistent sources, immutable snapshots, artifacts, injection scan results, and run evidence.
- **Projects** uses the durable project coordinator and project store.
- **Runs** reads canonical records reconstructed from the Runtime event stream.
- **Experiments** stores specifications and measured statistical summaries.
- **Model Lab** combines the model registry with recorded execution observations.

Equivalent API endpoints are available under `/api/v1/developer/`.

## Interactive project execution

Code, workflow, and device requests submitted through Chat are promoted to a
durable project execution cursor. The cursor binds the conversation, project,
work item, Runtime run, and latest checkpoint. The Runtime remains the only
executor; the project service records lifecycle and recovery state.

When a governed tool-step budget is reached, Nous marks the work item as
`recovery_required`, creates a checkpoint, and pauses the project. Continuing
in the same conversation resumes that work item with a new run identifier.
Successful and failed requests also create checkpoints so the Developer
Platform can display evidence instead of inferring progress from chat text.

## Scheduling boundary

Workloads carry a bounded profile containing required capabilities, target
nodes, trust and privacy constraints, and a maximum parallel-lane count. The
joint scheduler ranks complete model-and-node paths. The collaboration runtime
uses the same lane bound for manager, worker, and reviewer calls through the
Model Gateway.

Device and defensive-security work are not privileged shortcuts. Defensive
work requires an explicit authorized asset set and supports only inventory,
audit, assessment, analysis, detection, containment, remediation, recovery,
and compliance actions. Credential theft, persistence, propagation,
exfiltration, ransomware, and public-target exploitation are outside the
Runtime contract.

## Experiment evidence

Experiment evaluation requires paired baseline and candidate measurements. The
Runtime reports sample size, mean improvement, confidence interval, p-value,
and effect size. It does not generate substitute measurements when evidence is
missing. Result summaries are stored under the active workspace at:

```text
.nous/experiments/
  specs/
  results/
```

Raw credentials and provider secrets are not part of an experiment record.

## Model evidence

Model Lab distinguishes declared capability metadata from measured execution
observations. A model without observations is shown as awaiting evidence; a
zero sample count must not be interpreted as a zero quality score.

## Current boundary

This release does not include model training, weight merging, dataset hosting,
or a visual workflow graph editor. Those systems may integrate through stable
Runtime contracts, but they must not bypass the Gateway, EventStream,
governance gate, or workspace boundary.

## Professional Workbench

The Workbench is a real execution surface, not a capability mock. Its Runtime
endpoints are:

- `GET /api/v1/developer/workspace/files`
- `GET /api/v1/developer/workspace/file`
- `GET /api/v1/developer/workspace/search`
- `POST /api/v1/developer/workspace/preview`
- `POST /api/v1/developer/workspace/write`
- `POST /api/v1/developer/workspace/run`
- `GET /api/v1/developer/capabilities`

Writes require an expected SHA-256 when editing an existing file. A stale hash
fails with `NOUS_WORKSPACE_CONFLICT`; it never silently overwrites newer data.
Successful replacements are atomic and keep a recovery copy under
`.nous/backups/workbench/<run_id>/`.

Execution is not an arbitrary terminal. Callers choose an installed fixed
profile (`python`, `python-compile`, `pytest`, `node`, or `cargo-test`) and a
workspace-relative target where applicable. Runtime resolves the executable,
disables network access, applies time/output bounds through ProcessSandbox, and
returns both output and an EventStream `run_id`.

Capability counts distinguish registry declarations from live usability. A
provider capability requires a healthy provider that declares it; a subprocess
capability requires a complete immutable command and an installed executable;
a node capability requires a connected execution node; a Runtime capability requires an importable built-in service authority.

The Event Ledger authority and replay contract are defined in
`docs/adr/ADR-0002-event-ledger-authority.md`.

The governed outbound network boundary is defined in docs/architecture/GOVERNED_NETWORK_GATEWAY.md and ADR-0003.

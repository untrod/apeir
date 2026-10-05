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


## M3.6 public runtime SDK audit

Starting Distribution: `242acf84bb51aa7d1f60b49359093c7231b8af16`.
Kernel remains `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.

| Existing boundary | Classification | Milestone treatment |
| --- | --- | --- |
| Distributed Work, signed Node protocol, Node service | REUSE | Public SDK reexports the canonical classes; no second executor |
| Reality Device/Operation, Observation, EffectVerifier, Artifact CAS | REUSE | Same identities, evidence and fail-closed verification |
| Capability 2.0, Governance, credentials, durable Agent/Workflow | REUSE | Admission remains at existing gates; SDK is not authority |
| Provider/NKI Python SDK packages | EXTEND | Correct Distribution dependency and additive runtime facade |
| Provider metadata validation and CTK | EXTEND | No implicit execution; skipped required probes cannot certify |
| Third-party Work/Node/Reality imports | MISSING → supplied | `nous_provider.runtime` exposes canonical runtime types |
| Runtime contract conformance | MISSING → supplied | Seven opt-in target-backed suites on the existing CTK |
| Controller/node/CLI/desktop packaging | REUSE | Existing role entrypoints and independent desktop package |
| Native provider/hardware qualification | MISSING | Explicitly pending; contract reports cannot substitute for it |

Install `nous-provider-sdk` for `nous_provider.runtime` and
`nous_provider.conformance`; developers do not import internal Runtime modules.
The SDK implementation imports the authoritative Runtime contracts. It does not
copy them. Legacy `nous_provider.Device` remains a Kernel compute resource;
`nous_provider.runtime.ManagedDevice` is a Reality resource. Legacy
`nous_provider.ExecutionProvider` remains the NPA inference interface.

### Packaging and compatibility

Controller, Node and CLI share the existing `apeir-distribution` wheel and its
`apeir-controller`, `apeir-node`, and `apeir` entrypoints. Splitting their state or
execution paths into independently implemented packages is unnecessary. The
Provider SDK and NKI SDK are independently built wheels, depending explicitly on
`apeir-distribution>=0.1.0rc1,<0.2`. Desktop remains the existing separate Tauri/Web
package. Native sidecars still require the pinned component-lock verification.

The Node wire protocol is `nous-node` version `1.0`; Distributed Work uses
`apeir.compute-mesh-work/v1`; Observation uses the existing schema registry.
Unknown Node versions and Work schemas are rejected by their canonical parsers.
A compatible wheel version does not grant Node trust or Operation authority.
There is no downgrade negotiation or invented compatibility shim.

### Conformance evidence

`register_runtime_suites(runner, target)` adds Work, Node, Device, Provider,
Capability, Execution and Evidence suites without changing the five legacy CTK
suites. Missing targets report SKIP and cannot certify. Results explicitly report
`validation_level=contract` and `execution_performed=false`: these probes inspect
records, verify signed envelopes and CAS integrity, and independently recompute
EffectVerification from the original Operation, Receipt and Observations.
A contract report is not hardware, throughput, or production qualification.

Provider `validate()` checks metadata only. Legacy execution conformance requires
an explicit host-supplied `execution_probe`; a `test_mode` parameter does not
prevent an effect. The host must submit through existing governed Work admission.
Providers and test callbacks cannot authorize themselves. The acceptance test
uses the existing simulated Agent → Workflow → Governance → Distributed Work →
Node → Device execution, then consumes the resulting evidence through public SDK
imports. Wrong-operation receipts and missing observations fail conformance
without executing the effect again.

### M3.6 validation record

Local focused SDK/CTK: **79 passed** (14 new milestone cases). Affected M3.1–M3.5,
workflow, recovery, artifact and architecture regressions: **646 passed, 3 skipped**.
Full repository: **3596 passed, 35 skipped, 9 failed**; the nine failures match the
starting-baseline reproduction (managed interpreter path, read-only HOME storage
and orphan-process cleanup). They remain visible and unchanged.

Ruff, changed-file formatting, compile, documentation/link, comment, identity,
Git metadata, release-version and security checks pass; security reports zero
findings. Component-lock contract tests: **3 passed**. Native component verification
remains blocked by the already missing locked Windows sidecar binaries; no lock
or Kernel code changed. Distribution, Provider SDK `1.0.0b2` and NKI SDK `0.1.1`
wheels build and install in an isolated consumer; public imports and optimized
Python fail-closed conformance pass. CI is checked after push and reported with the
resulting Distribution SHA. Physical acceptance remains **PENDING**.

### Canonical Work read correction

The first SDK commit `9f829b004ec6ef68a2daa7894dab3b2242dbb755` passed Desktop CI
(Windows **3607 passed, 28 skipped**; Linux/macOS **3600 passed, 35 skipped**).
Its multi-architecture Windows job recorded **1 failed, 3318 passed, 28 skipped,
272 deselected**: the existing firmware revocation test stopped before approval
because the distributed Work store was unreadable. The failure is retained at
[the original CI run](https://github.com/untrod/apeir/actions/runs/37282398853).
The log does not expose the underlying Windows error number.

Inspection identified a reproducible read/write exclusion defect: Work writers
held the existing file lock while reads could concurrently replace the instance's
working snapshot. Reads, counts, listing and restart loading now use that same
canonical lock; mutation methods use an internal read under their already-held
lock, avoiding recursive acquisition. This introduces neither a new lock system
nor effect retries. Four concurrent-reader regression cases cover the correction;
the pre-fix read path demonstrably enters during a write.

Latest local validation: reader/revocation targets **6 passed**; affected
regressions **650 passed, 3 skipped**; full repository **3600 passed, 35 skipped,
9 unchanged baseline failures**. Ruff, changed-file formatting, compile and the
isolated Distribution wheel build pass. The corrective SHA and its CI outcome
are checked after push. Kernel and the component lock remain unchanged.

The corrective commit `6960175c2a554d813047ea7c462f0447bc204584` passes both
[Desktop CI](https://github.com/untrod/apeir/actions/runs/37285404969) and
[Multi-Arch CI](https://github.com/untrod/apeir/actions/runs/37285405037), first
attempt: Windows Python **3611 passed, 28 skipped**; Linux Python 3.10/3.12 and
macOS Python **3604 passed, 35 skipped** each; Linux amd64/ARM64 matrix
**3315 passed, 36 skipped, 272 deselected** each plus **13 platform tests** each;
Windows amd64 matrix **3323 passed, 28 skipped, 272 deselected**. Frontend remains
**47 passed**. Native bundle jobs are conditionally skipped, not qualified.
M3.6 software acceptance passes; native/physical qualification remains PENDING.

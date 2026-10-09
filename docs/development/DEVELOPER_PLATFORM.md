# Developer Platform

Current overall milestone status is authoritative in [ROADMAP](../../ROADMAP.md).
Acceptance counts below are dated, scoped records, not broader qualification.

The APEIR Developer Platform is a control surface over the Runtime. It does not
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
`docs/rfc/adr/ADR-0002-event-ledger-authority.md`.

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

### Source SDK onboarding

Use the [Source Quick Start](../operations/getting-started/QUICK_START.md#public-sdk-examples)
for the single recommended installation path and runnable public SDK examples.
The additive SDK facade reexports the existing ProviderRegistry, Governance
contracts, SkillRegistry/SkillToolRuntime and Workflow step types; it implements
none of them again. Access to a class is not authority. The example's local host
owns explicit read-only policy and Node admission; adapter code receives input
only. Skill installation/load records instructions and CAS provenance, not
permission or execution. Removal/disable and error paths are tested.

### CI scope and measured cost

Core, Desktop and Security required contexts remain present on every PR. Feature
branches run these on `pull_request` instead of duplicating the same work on
`push`; main, release branches and dispatch retain their broader validation.
Only known root/docs Markdown and listed example README files select the
documentation path. Skill instructions, code, tests, configuration, workflows,
unknown paths and mixed changes select full regression. Deletions and both ends
of renames participate; invalid Git revisions fail the job. Security checks and
the collection floor still run on documentation PRs. Main never uses the narrow
path; Multi-Arch and Release gates are unchanged.

Baseline PR #21 used 13 active source jobs and 2,555 aggregate job-seconds, with
1,064 seconds from the first source workflow start to all source checks complete.
Its feature push plus PR ran five full Python jobs and two frontend builds.
The new feature-PR shape runs one full Python job and one frontend build, with
three workflows instead of six. Actual after-change timing is attached to the
PR acceptance evidence; different workloads and runner scheduling limit direct
latency comparisons. No Relay, SQLite or fsync durability tuning is included:
the existing three-round startup baseline measured CLI-ready median 1.214 seconds
and the 1,000-record benchmark measured context-write median 0.382 ms and p95
0.567 ms. Those synthetic local results do not justify weakening persistence.

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

### Supported development environment

Developer Preview PR #23's source checks passed, but its initial main
`25aed7c34cb1c4173476d660ccccc032b3fb0452` exposed two failures in untouched
baseline files. Windows Core recorded **1 failed, 4000 passed, 53 skipped,
4 warnings**: the existing EventStream writer's 10-second process-exit assertion.
Windows Multi-Arch recorded **1 failed, 3711 passed, 53 skipped, 272 deselected,
4 warnings**: WebGateway passed `30.000000000000057` seconds to transport against
an exact 30-second bound. Original failed Actions runs
[37972025588](https://github.com/untrod/apeir/actions/runs/37972025588) and
[37972025503](https://github.com/untrod/apeir/actions/runs/37972025503) are retained.

A controlled constant clock reproduces the timeout overflow on unchanged
Gateway code. Transport now receives at most the original request bound;
the total deadline, retry, network/credential and authority rules are unchanged.
A controlled failed first writer also proves the old test leaves other started
children unreaped. The test now cleans every child and records construction,
writing and completion phases for future failures. Four writers, forty events,
exact sequence assertions and the original 10-second exit check remain intact.
EventStream, fsync and Kernel are unchanged. This fixes test cleanup and adds
diagnostics; it does **not** prove the original Windows termination timing cause
resolved. SDK acceptance requires a separate corrective PR and successful native
source/main checks; original failures are not erased or rerun into acceptance.

The environment cleanup audit reuses the existing workspace configuration,
daemon constructor, pytest fixtures and Kernel process identity semantics.
The MCP adapter extends only trusted base-interpreter selection: CPython's
actual base executable replaces the invalid `base_prefix/executable-name`
layout assumption. Missing, relative or non-executable base paths fail closed;
there is no PATH fallback. Existing strong isolation, `-I`/`-S`, explicit
read-only package bootstrap and local permit boundaries remain intact.
Behavioral tests launch that interpreter and reject cwd/PYTHONPATH shadowing.

Persistence tests use independent temporary workspaces rather than shared HOME.
Production defaults are unchanged. A supported local environment also needs a
writable checkout, named user and resolvable hostname for existing state and
identity/resource probes. A read-only checkout is not the full development
environment: existing core bootstrap and compatibility tests write local state.
For an offline container, supply a test user and local hostname mapping; these
environment facts do not enroll a trusted identity or grant authority.

Process lifecycle acceptance requires an init/reaper. On unchanged Runtime,
the same two orphan-process assertions passed **2/2** with Docker `--init` and
failed **2/2** without it. A dead orphan's retained creation identity is not
permission to weaken the assertion or modify Kernel. Use an initialized Linux
environment, for example `docker run --init --hostname apeir-test
--add-host apeir-test:127.0.0.1 ...`, with a provisioned user, installed test
dependencies and writable temporary storage. The ellipsis denotes normal image,
mount and pytest arguments, not a separate validation framework.

Local qualification on 2026-10-06: focused MCP/desktop/daemon cases **137 passed**;
coordination, Work, Workflow, Reality, governance and extension regressions
**679 passed, 17 skipped**; Node/control-plane/Artifact **228 passed**;
repository checks **244 passed**, component-lock contracts **3 passed**.
Full managed host regression (real OPA/OpenBao references enabled) recorded
**3805 passed, 36 skipped, 2 failed, 4 warnings**. The two unchanged orphan
identity assertions still fail under its bare PID 1; the original seven other
failures no longer occur. No tests were skipped or weakened to hide them.

Full initialized-container regression recorded **3796 passed, 47 skipped,
4 warnings**, exit zero. It used pinned Python 3.12 image
`python@sha256:ddb0207ae1f0356c2b724d740769b0c5f5f51cc54a0525178f721825f78fe74c`,
UID 1000, fake local USER/LOGNAME, `apeir-test` hostname mapped to loopback,
`--init`, no external network, dropped capabilities, no new privileges,
read-only rootfs, writable checkout and temporary storage. Existing installed
test dependencies and Git were mounted; no secret or Docker socket was supplied.
The eleven real OPA/OpenBao service cases explicitly skip there, while the host
run exercises them. These separate run counts must not be summed.

An initial container with no named user/hostname was interrupted after **97
failed, 1457 passed, 31 skipped, 32 errors, 1 warning**. After supplying those
facts, a read-only checkout probe completed with **40 failed, 3756 passed,
47 skipped, 4 warnings**, including read-only SQLite/state writes and resulting
missing registration facts. Both unsuccessful configurations remain evidence;
they are not hidden baseline regressions or qualified environments.

Ruff lint, compile, 232-document links, hygiene, identity, Git metadata, version
and security checks passed; security found zero findings in 1891 files. Source
`55fc890` Security CI failed its existing changed-file format gate: full-file
checks flagged `tests/conftest.py` and `tests/test_production_suite.py`, also
reproduced on their untouched starting versions. The required formatter was then
applied to those two already changed test files; ASTs before/after are identical.
All five changed Python files now pass full-file formatting; no CI requirement,
assertion or Runtime behavior was weakened. Actual native component hashes remain BLOCKED by the missing locked
Windows sidecar. Kernel and the component lock are unchanged. Source/PR and
resulting-main CI must pass before checkpoint publication and issue #9 closure.

An additional Windows timing failure occurred on source `5ae10f4` Core CI:
**1 failed, 3802 passed, 40 skipped, 4 warnings**. The legacy connectivity
vertical slice slept 0.8 seconds after start and mistook TCP readiness for a
received WELCOME/session. A controlled 1.1-second WELCOME delay reproduced the
same assertion on unchanged Runtime (**1 failed, 2 warnings**). The test now
awaits the current native session and actual send queue within the existing
10-second receive budget, rejects prior session/queue state after reconnect,
and always cleans up its Node. Hold/release cases retain zero echo invocations
before WELCOME and require exactly one completed echo after delivery. Focused
connectivity module: **16 passed**. Final controlled stress: **60 passed over
20 rounds**; affected connectivity/Node/control-plane/Reality/governance
regressions: **595 passed**. After the synchronization tests, full managed host
regression recorded **3808 passed, 36 skipped, 2 unchanged bare-PID-1 failures,
4 warnings**; full initialized-container regression recorded **3799 passed,
47 skipped, 4 warnings**, exit zero. These supersede the earlier run counts
for current qualification without erasing those historical results. Final whole
Ruff lint, all six changed Python files' formatting, compile and standard
docs/link/hygiene/identity/Git/version/security checks pass; the final security
scan records zero findings in 1893 files. This is test synchronization, not a new
authentication or execution contract.

The first hold/release probes (**2 failed, 14 passed**) also exposed legacy
Gateway assignment before send-queue readiness. Waiting for actual queue
readiness preserves the handshake test's scope; the early-submission Runtime
gap is not claimed repaired. Its evidence and broader latency qualification
remain OPEN in [issue #4](https://github.com/untrod/apeir/issues/4#issuecomment-6012448219).
The original nine Cloud failures and these additional failures are separate.

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

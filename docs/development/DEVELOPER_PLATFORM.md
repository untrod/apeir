# Developer Platform / 开发者指南

Use APEIR Studio to work on a project, run a supported workflow, or build an
extension. The interface uses the same Runtime services as the CLI and public
API. Start with the task you want to do; the architecture can wait until you
need to extend it.

从实际任务开始：连接模型、打开工程、审查修改，或编排已有能力。
本页保留界面中的英文名称，方便对照中英文版本；完整安装命令在 Quick Start。

| Your goal | Start here |
| --- | --- |
| Find the implementation | [Current code entry points](RUNTIME_MODULE_MAP.md#current-code-entry-points) |
| Download and launch | [Quick Start](../operations/getting-started/QUICK_START.md) |
| Arrange panels and dashboards | [Studio](../operations/guides/USER_GUIDE.md) |
| Connect an API or local model | [Models and Providers](../operations/guides/PROVIDER_GUIDE.md) |
| Watch model and tool activity | [Watching a request](../operations/guides/USER_GUIDE.md#watching-a-request) |
| Check Tokens and cost | [Usage](../operations/guides/CONTEXT_AND_USAGE.md#model-usage-and-cost) |
| Review a code change | [Workspace changes](../operations/guides/USER_GUIDE.md#reviewing-workspace-changes) |
| Build a workflow | [Workflow Builder](../operations/guides/WORKFLOW_GUIDE.md) |
| Install a Skill | [Skills](#skills-and-tools) |
| Create a panel or widget | [UI Extension SDK](STUDIO_UI_EXTENSIONS.md) |
| Write a Provider | [Public SDK](#source-sdk-onboarding) |

APEIR is the platform; **Studio** is its workspace, **Runtime** owns execution and
Governance, and **Kernel** is the separately pinned controlled-execution component.
[ROADMAP](../../ROADMAP.md) owns milestone status. Detailed historical tests and
failures belong in [Engineering Review](../acceptance/ENGINEERING_REVIEW.md).

## Surfaces

Studio combines existing views: Chat, Files, Workflow, Tasks, Models, Nodes,
Devices, Environment, Evidence, Usage, Documents and Simulation. Operations Console
provides the original governed controls. A visible panel does not make an
unconfigured Provider, disconnected Node or unsupported handler available.

### APEIR Studio

See [APEIR Studio](../operations/guides/USER_GUIDE.md#apeir-studio) for the current task guide.

#### Overview / 概览

See [Overview / 概览](../operations/guides/USER_GUIDE.md#overview--概览) for the current task guide.

### Watching a request

See [Watching a request](../operations/guides/USER_GUIDE.md#watching-a-request) for the current task guide.

### Visual Workflow Builder

See [Visual Workflow Builder](../operations/guides/WORKFLOW_GUIDE.md#visual-workflow-builder) for the current task guide.

### First-use configuration and model tests

See [Models and Providers](../operations/guides/PROVIDER_GUIDE.md) for configuration,
credential references, exact model identities and deliberate inference tests.

### Inspecting actual model input

See [Inspecting actual model input](../operations/guides/CONTEXT_AND_USAGE.md#inspecting-actual-model-input) for the current task guide.

### Model usage and cost

See [Model usage and cost](../operations/guides/CONTEXT_AND_USAGE.md#model-usage-and-cost) for the current task guide.

## Skills and tools

Use **Operations Console → Skills** for the canonical local and reviewed HTTPS
catalogs. Review the exact source, version, digest, requested capabilities and
compatibility, then install. Loading instructions, enabling, disabling and
uninstalling are separate operations. Current human permissions are required;
a service token alone is observe-only for these controls. Passive refresh does
not download remote catalogs.

Follow [Hello Skill](../../examples/hello_skill/README.md) for the runnable local
catalog example and the [acquisition contract](../architecture/SECURITY_CONTRACT.md#skillextension-acquisition-before-publication)
for reviewed HTTPS packages. Changed content needs review again. Provenance/CAS
integrity is not publisher certification. This is not an unrestricted public
marketplace or permission to run every third-party package.

An **Instruction Skill** supplies text. An **executable Tool/Provider** needs its
own supported implementation and current execution permission. Installed,
loaded, authorized and executed are four different states. The
[UI Extension SDK](STUDIO_UI_EXTENSIONS.md) below adds declarative panels;
it does not turn a Skill into a Shell or grant device writes.

## Reviewing workspace changes

See [Reviewing workspace changes](../operations/guides/USER_GUIDE.md#reviewing-workspace-changes) for the current task guide.

## Professional Workbench

See [Professional Workbench](../operations/guides/USER_GUIDE.md#professional-workbench) for the current task guide.

The fixed `python-unittest` profile is shared by the Workbench and the governed
`project.run_tests` capability (`run_project_tests` in the model tool catalog).
It requires a qualified strict sandbox and a project-relative test directory.
The model cannot supply arbitrary command arguments or approve its own request.
Results keep the original Run ID, test counts and an inspectable Artifact.
No tests, all skipped tests and incomplete records remain `UNKNOWN`.

Evaluation reads those original records; it does not launch project code.
`apeir evaluate project --id <project-id> --test-run-id <run-id>` inspects
a Run in the active workspace. An exit code or pasted success message is not a
receipt. 先审批、再执行、最后检查原始记录。测试未运行时，绿色勾不会自己长出来。

The test verdict is separate from the wider quality report. Default evaluation
leaves unmeasured quality dimensions for review and never recommends replaying
an operation merely to fill missing evidence.

## Interactive project execution

See [Interactive project execution](../operations/guides/USER_GUIDE.md#interactive-project-execution) for the current task guide.

## Scheduling boundary

Scheduling proposes placement within declared profiles, trust/privacy
constraints and lane limits. It cannot grant execution permission. Explicit
model choice is preserved. Manager/worker/reviewer outputs are proposals or
evidence, not independent approval.

## Experiment evidence

Experiments require actual paired baseline/candidate measurements. Sample size,
uncertainty and effect size accompany recorded results; missing data gets no
substitute report. Specifications/results live under `.nous/experiments/`.
`TestValidator` uses pytest outcome fields, not duration/warning counts. Exit 0
with only skips or missing pass evidence remains unverified. The scientific
reference also requires its qualified strict environment.

## Model evidence

Model Lab distinguishes declared capabilities, availability metadata and measured
observations. Zero samples is not zero quality. Context reads need a live
AuthorizationContext, matching actor/purpose and current Governance decision;
private data additionally needs its explicit owner and trusted human boundary.
A model profile, copied identity claim or successful health probe supplies none
of that authority.

Performance history belongs to the selected workspace. Its observation and
ranking endpoints do not use the legacy process-wide writer; rankings retain
their requested minimum sample count. `ModelObservationStore.record()` reports
unconfirmed persistence with `ModelObservationError`. Inspect the original
record; never repeat a Provider request to repair a telemetry failure. Unreadable
history is unavailable, not an empty success. These records are not the billing
ledger; [Usage](../operations/guides/CONTEXT_AND_USAGE.md#model-usage-and-cost) remains the accounting view.

## Current boundary

Runtime state stays in the selected workspace, not the presentation layout.
Explicit `NOUS_WORKSPACE_ROOT` takes precedence over cwd discovery; ambiguous,
external, linked or corrupt selections fail rather than silently reading another
project. Database/sidecar path admission rejects links and nonregular files;
SQLite file URIs preserve literal filename characters. These local checks do not
qualify cross-host NFS/SMB state or defeat an OS owner replacing paths later.

Trusted handler registration may declare bounded retry safety or
`WorkflowHandlerPolicy(reconcile_started=True)` only for a handler that consults
original durable Work/effect evidence. Task/model data cannot supply that policy.
Consult [state ownership and recovery](../architecture/STATE_OWNERSHIP.md#failure-and-recovery)
and [execution paths](../architecture/EXECUTION_PATH.md) before writing an adapter.
Training, weight merging, arbitrary executable UI and complete Codex Harness
recovery are not qualified by this release. A visual graph editor is available
within the handler limits above.

## M3.6 public runtime SDK audit

The historical SDK audit and dated validation counts are preserved in
[Engineering Review](../acceptance/ENGINEERING_REVIEW.md#developer-sdk-qualification-archive--2026-10-06).
The public SDK reexports canonical contracts; it adds no executor or authority.

### Source SDK onboarding

Use [public SDK examples](../operations/getting-started/QUICK_START.md#public-sdk-examples)
and [Hello Provider](../../examples/hello_provider/README.md). Install the Provider
SDK from the same checkout. `nous_provider.runtime` exposes Work, Node,
ManagedDevice, Governance, Capability, Skill and Workflow contracts without
requiring consumers to import private Runtime modules. Legacy
`nous_provider.Device` still means a Kernel compute resource.

### CI scope and measured cost

Studio's checked-in browser tests start two owned model-disabled Runtime
processes and sandboxed Chromium. From `desktop`, with the Distribution installed
in the selected Python environment:

```bash
npx playwright install --with-deps chromium
npm run test:e2e
```

`APEIR_TEST_PYTHON` can select its absolute interpreter path. Tests cover real
HTTP/layout/draft/Controller and supported Workflow/extension paths; their output
is source-browser evidence, not installed Windows acceptance. The existing
[shared-Usage benchmark](../acceptance/ENGINEERING_REVIEW.md#shared-usage-transport-measurement--2026-10-24)
keeps its paired methodology and component-only limits.

Known documentation-only PRs use the existing narrow checks; code, mixed and
unknown paths receive broader regression. Main retains full platform checks.
Historical job-cost observations and unresolved timing evidence are in the
[SDK archive](../acceptance/ENGINEERING_REVIEW.md#developer-sdk-qualification-archive--2026-10-06).
A diagnostic workflow cannot satisfy a production/Core check by name alone.

### Packaging and compatibility

Controller, Node and CLI share `apeir-distribution`: `apeir-controller`,
`apeir-node` and `apeir`. Provider/NKI SDK wheels depend on the compatible
Distribution. Desktop remains the existing Tauri/Web package; native components
must match the lock. `nous_runtime`, `nous`, `NOUS_*` and `nous-node/1.0` remain
compatibility names. A compatible package does not establish Node trust.

### Conformance evidence

The existing CTK adds Work, Node, Device, Provider, Capability, Execution and
Evidence suites through `register_runtime_suites`. Missing targets report SKIP,
not certification. Contract probes inspect records and original evidence;
`validation_level=contract` does not imply execution or hardware acceptance.
An explicit governed execution probe is required to exercise effects.

### Supported development environment

Use an executable trusted CPython base interpreter, writable checkout and test
storage, named user and resolvable hostname. Keep HOME unchanged; tests use the
existing workspace configuration. Linux process-lifecycle containers need
`--init` or an equivalent reaper. The ProcessSession host reaps its own original
workload group; unconfirmed cleanup stays RECOVERY_REQUIRED. This is not permission
for escaped processes or a change to Kernel isolation.

### M3.6 validation record

Dated source, installed-wheel and contract results remain in the
[SDK archive](../acceptance/ENGINEERING_REVIEW.md#developer-sdk-qualification-archive--2026-10-06).
Current-head CI must qualify current changes; old green runs cannot do so.

### Canonical Work read correction

The [archived SDK evidence](../acceptance/ENGINEERING_REVIEW.md#developer-sdk-qualification-archive--2026-10-06)
retains the original startup/fresh-report correction and Windows failure logs.
Node readiness uses current authenticated connection/resource facts; a persisted
report alone does not make a reconnected Node ready.

## MCP access to the existing Runtime

Install the existing `mcp` extra and start the normal authenticated Runtime using
[the source quick start](../operations/getting-started/QUICK_START.md). A host operator supplies
its existing service credential to the stdio bridge through
`APEIR_MCP_API_TOKEN`; never put it in a prompt, tool argument, checked-in MCP
configuration or command argument. The bridge delegates that credential only to
one host-configured Controller origin:

```bash
apeir extension serve-mcp --runtime-url http://127.0.0.1:8770
```

Remote Controller origins require HTTPS and the platform certificate trust
store. Plain HTTP is limited to numeric loopback; redirects, URL credentials,
query strings and alternate paths are rejected. The official MCP SDK owns the
stdio protocol. The bridge has a whole-call HTTP deadline and closes its request on cancellation.
It owns no execution worker, state database, approval,
trust store or verification authority. It never automatically retries HTTP calls.
The Controller authenticates every call to its existing API before dispatch.

All tools require an explicit current PermissionEngine rule for the authenticated
service subject, exact tool action and resource below. Missing policy fails
closed; discovering a tool does not grant it. Configure permissions through the
existing host-owned Governance policy, not through MCP or model output. The
credential remains protected bridge-process material: these rules scope MCP
calls, not every legacy API that the same service credential could access.
Exposing that credential or an unrestricted host terminal to an external agent
is not qualified by this interface.

| Tool | Input | Permission resource / original owner |
| --- | --- | --- |
| `apeir.nodes.list` | none | `workspace:<SHA-256 of canonical workspace path>`; existing Controller facts, never invented online state |
| `apeir.devices.inspect` | `device_id` | `device:<id>`; existing Reality DeviceRegistry |
| `apeir.work.submit` | `objective`, `idempotency_key` | workspace resource; original WorkSupervisor, read-only tool profile, maximum 8 iterations |
| `apeir.work.status` | `run_id`, optional `owner` | `work:<id>` for default `work-harness`, `distributed-work:<id>` for explicit `distributed` |
| `apeir.evidence.read` | same as status | original checkpoint/EventStream or DistributedWorkStore evidence references; never another verifier |

Work submission additionally passes the **original** `runtime.execute` API
Governance Gate. A required human approval remains pending in the existing
approval UI/CLI; no MCP approval tool exists. An authenticated retry of the same
scoped key and identical effective inputs returns the original Run without a
new model/tool invocation or a new approval. Changed inputs, damaged bindings or
interrupted initialization fail closed. This fence is in the existing verified
checkpoint store and survives ordinary retention; it is not a new Work registry.
Missing HTTP responses or client cancellation do not imply failure of the
original Work. Query its status/evidence before any explicit recovery action.

Results are centrally redacted and bounded to 1 MiB. Evidence exposes original
records/references; execution success, receipt, file checksum and physical MATCH
remain distinct. `owner` never falls back to another Work system. This first
interface supplies no arbitrary host command, file transfer, approval, grant or
physical operation API. A Work's own tools continue through their existing
permissions and execution boundaries. Selected-file Chat disclosure qualification
does not automatically qualify every Work Harness model-input path.

Reproduce the stdio/HTTP, scope, negative-security, approval and original-request
recovery contracts:

```bash
python -m pytest -q tests/extensions/test_runtime_mcp_server.py tests/work/test_work_submission.py
```

The official Codex App Server 0.163.0 was separately exercised with direct MCP
calls: thread start, tool discovery, current Node projection, original Distributed
Work query and a new Work stopped at human approval. **No model Turn ran.** This
is MCP interoperability evidence, not complete authenticated Codex Harness,
workspace-isolation, paid usage, cancellation or recovery qualification. Official
CLI authentication metadata was available, but scoped filesystem/credential and
native tool admission must be qualified before enabling a model Turn; an
instruction prompt is not that boundary.

## Declarative UI Extension SDK

See [Declarative UI Extension SDK](STUDIO_UI_EXTENSIONS.md#declarative-ui-extension-sdk) for the current task guide.

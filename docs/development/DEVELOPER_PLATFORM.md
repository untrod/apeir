# Developer Platform

Current overall milestone status is authoritative in [ROADMAP](../../ROADMAP.md).
Acceptance counts below are dated, scoped records, not broader qualification.

The APEIR Developer Platform is a control surface over the Runtime. It does not
own a second scheduler, project database, model registry, or execution path.

## Surfaces

The desktop `Develop` page provides the following views:

- **Workbench** provides workspace-scoped file browsing, bounded multi-file UTF-8 editor tabs, unified diff preview, compare-and-swap atomic writes, and fixed-profile strict execution.
- **Research** provides approval-gated public web fetch, persistent sources, immutable snapshots, artifacts, injection scan results, and run evidence.
- **Projects** uses the durable project coordinator and project store.
- **Runs** reads canonical records reconstructed from the Runtime event stream.
- **Experiments** stores specifications and measured statistical summaries.
- **Model Lab** combines the model registry and performance observations with a
  read-only projection of the existing model usage journal.

Equivalent API endpoints are available under `/api/v1/developer/`.

### First-use configuration and model tests

The existing native setup wizard reads `/api/v1/health/detailed` from the selected
Runtime. Platform/architecture are reported Runtime facts; rendering a page is
not WebView, native package or sandbox qualification. Kernel, Provider and
execution admission remain separate. Local workspace selection uses the existing
native initializer/restart, then confirms the selected path through the Runtime
workspace API. A remote Controller retains its existing workspace; the wizard
does not manage that remote host through local filesystem commands.

**Configure model later** leaves existing Providers unchanged and opens the
workbench without an API key. Completion saves configuration once; it creates no
conversation and performs no inference. A Controller/session version change
invalidates the pending setup, including address/token changes that return to the
original values. An uncertain restart stays unresolved without another mutation.

`POST /api/v1/providers/validate` now validates reference-only configuration; it
performs no network request, credential resolution or inference. It returns
`validation_scope=configuration`, `authentication=UNKNOWN` and
`model_inference=NOT_RUN`. This corrects the old direct inference probe.
Provider base URLs must be HTTP(S), without embedded credentials, query parameters
or fragments. Secrets belong in the existing credential reference path.

Provider Doctor/catalog reads and `provider ping` are endpoint metadata probes;
they do not prove authentication or inference. Explicit `provider test` uses the
existing model-test service only when the current strict NKI Gateway and original
Provider/model/endpoint/credential-reference/capability mappings agree. A changed
Gateway is fenced before dispatch. Unregistered, changed or direct compatibility
configurations return `NOUS_PROVIDER_NKI_REQUIRED`, without a direct POST fallback.
Save configuration and use **Models → Test** through the same existing Gateway.
Kernel availability, credentials and actual Provider support are still required.

Saved Provider creation, `PATCH /api/v1/providers/{provider_id}` and governed
deletion now update the original `providers.json`, existing Registry and current
Gateway. Gateway construction reads a locked snapshot of the original Registry
without invoking adapter health/credential callbacks. Updates preserve unedited
adapter settings; deletion does not remove a
credential from its separate store or cancel already admitted requests. It takes
effect in the current process and survives reload. Other running processes are
not silently synchronized. The existing file lock serializes cooperating writers;
invalid configuration is rejected instead of replaced with an empty mapping.
Invalid edits and failed writes preserve the previous registration. If persistence
succeeds but runtime refresh fails, the request reports failure and clears the
current Gateway: inspect saved configuration before retrying. This is not a
claim of transactional rollback across files, processes and in-flight effects.
Unsupported `enabled` edits are rejected rather than falsely reported as applied.

The model catalog exposes `provider_model` only when recorded in its descriptor.
Setup uses that exact vendor model ID for the selected Provider, through the
existing bounded catalog reader. It does not send a Gateway ID or display name
as a vendor parameter, guess a missing ID, or mix another Provider's models.
Template suggestions and saved model metadata do not prove remote availability.
The desktop `anthropic` identity maps to the existing Claude/Anthropic adapter;
root, `/v1` and full messages URLs normalize to the original messages endpoint.
Previously saved configurations are not silently rewritten: explicitly review
and resave an incorrectly configured template. The unimplemented native Gemini
protocol template is disabled; compatible endpoints can use the existing
OpenAI-compatible configuration. This is protocol configuration, not live-account
qualification.

Model tests retain the original request ID after dispatch failure and do not
retry it automatically. Explicit completion is required; UNKNOWN is not healthy.
Missing Token usage and unmeasured cost remain null/unknown, including the legacy
`tokens_used` projection. Its redaction exception accepts only null/nonnegative
integers; strings and structured values remain redacted. Inspect original usage
and request evidence before another potentially billed call. Software tests use
fake responses and native IPC; they do not establish a real account, installed
Windows credential store, native executable or release acceptance.

### Inspecting actual model input

Chat and the Workbench's read-only assistant expose **Inspect model input** on
a recorded response and **Inspect active input** during a request. Workbench's
**Recorded model input** selector also opens a recent canonical Run after restart,
including in the browser Operations Console without making a new model call. The inspector
replays the existing EventStream for the original Run; reopening a persisted
conversation retains that Run binding independently of its Trace ID. It does
not call a model, build a new ContextSnapshot or grant authority.

Each admitted Chat Gateway iteration records a content-free input manifest:
message roles, character counts, estimated tokens and SHA-256; declared tools;
selected context chunks marked included or omitted by the Context Builder's
admitted input and item bounds; and preceding tool results. Selected chunks
reach the Gateway whole, without a second character clipping pass. Historical
manifests with partial chunks remain readable. A successful
`read_file` result identifies the relative file, selected lines and original
file digest computed from the same bounded bytes as its selected content.
This does not prevent later edits or prove an atomic filesystem snapshot.
Failed reads never appear as successful file access. Source IDs
are hashed, not copied; message text, file contents and tool arguments are not
duplicated into this manifest. Available tool declarations are not permission.

The manifest identifies the application Gateway input after Agent admission,
not the provider's final HTTP envelope or proof of provider receipt. Retries,
provider-specific formatting and collaborative worker/reviewer calls are not
covered by this Chat manifest. Token estimates include structured calls and
tool definitions; normalized Runtime usage, cache counters, latency and cost are
separate recorded telemetry. Counter and cost measurements distinguish Provider
reported, derived, estimated and unknown values; missing counters remain null.
Unclassified legacy values cannot establish a Provider measurement.
Missing usage, legacy/unsupported manifests,
replay errors and missing terminal events remain UNKNOWN. Input inspection
does not verify an effect or restore expired authority.

Details are bounded to 256 messages, 64 tools and 128 selected context sources
per invocation; counts and the input digest cover the complete Gateway input.
The UI replays up to 1,600 events with cursor pagination and explicitly labels
truncation. Old events remain readable without fabricated manifests. A selected
workspace selection is an exact saved path/SHA-256 reference. **Send** carries
`workspace_file_refs` through the existing Chat API and requests current source
read and Provider transfer admission; selection alone sends no file bytes. The
inspector records selected/read/sent/rejected/budget-limited states without source
text or raw paths. Sent identifies the Gateway Provider boundary, not confirmed
Provider receipt. Saved-file delivery reuses the safe workspace reader on POSIX
and Windows; missing required APIs keep delivery BLOCKED without ordinary-file
fallback. Canonical private-source checks and conservative Windows alias rejection
precede bytes, and read permission never implies Provider transfer permission.
The Windows saved-file/Context/HTTP path and owner-policy ACL path require their
native qualification tests; ordinary Windows file-read tests alone do not
qualify delivery.

The stock Controller creates no file-sharing permissions. A trusted maintainer
can explicitly select an owner-only policy under the current Governance `.nous`
directory using `NOUS_PERMISSION_POLICY` before starting Runtime; see
[configuration](../operations/configuration/CONFIG_REFERENCE.md#context-permission-policy).
On Windows, the selected file must pass the same-handle owner/protected-DACL
contract documented in the configuration reference. Merely having a safe source
reader does not admit a policy, and the default installed-user permission setup
remains a separate qualification.
This feeds the existing PermissionEngine, not a second authority. It is re-read
at checks, so expiry, revocation or corrupt configuration blocks later dispatch.
The permission-status API describes configuration with UNKNOWN grants when no
subject/action/resource request was evaluated. File selection and those labels
never grant access. Real Provider, strong sandbox and native qualification remain
separate prerequisites.

Runtime source collection requires the trusted entry point's live authenticated
context. Serialized actor claims cannot supply that proof. Normal initialization
declares `context.read` in the existing Capability Registry; it creates no
permission or grant and preserves a disabled reader. Current ContextGuard
admission precedes collection and binds the request, actor, workspace and purpose.
Memory, project, Agent and decision readers use the selected workspace's existing
`.nous` state; no source registry or cache store is added. Context audit records
also stay under `.nous`. An older explicitly placed Context database is retained,
not deleted or copied into source context.
The CLI uses the same configured host root and its trusted local-owner
attestation. API/Chat pass the already validated context; a generic SDK request
does not automatically become a human. Context-loaded Run events and Trace
entries contain only snapshot IDs, counts, checksum and admission references;
they do not copy source text or identity attestations.

Snapshots retain source identity/version, owner, permission, content digests,
source positions and omission reasons. Required objective, plan and governance
items remain whole; if they cannot fit, dispatch stops with
`context_budget_exceeded`. Estimates are not Provider token measurements.
Retained Runtime context is rechecked before each Chat model invocation and
collaboration entry. Revoked access pauses the existing Agent execution before
the next Provider call; it cannot retract bytes already sent. Snapshot integrity
and permission revalidation alone do not establish current filesystem freshness.
Explicit saved-file references additionally re-read their exact bounded version
and revalidate read/transfer permission after setup at every actual Gateway
attempt, including retries, fallback and NKI submission.
Incremental snapshot updates require the same binding and supplied current
source versions; they remain read data, not execution authority or a qualified
cross-task cache.

Work Harness decisions have a separate 96,000-character prepared-input bound.
The complete compacted JSON must fit; it is never sliced in the middle of a
Goal, constraint or decision schema. Overflow pauses the original Work in
`WAITING_USER` before Provider dispatch, with a count/limit diagnostic and its
original Goal/checkpoint retained. Reduce selected context or explicitly split
the task rather than silently replacing its requirements. This is a character
admission bound, not a Provider token measurement or automatic long-task summary.

Parallel Gateway requests keep each child's original parent binding and limit
its dispatch to the remaining aggregate deadline. The requested `min_successes`
controls aggregate success; a retained partial answer does not satisfy a larger
threshold. Partial output and usage remain available for inspection. Cancellation
and missing responses do not prove that a dispatched Provider incurred no cost.
For failed or cancelled children, aggregate usage is projected from all original
CostController attempts and unsettled reservations. Missing or corrupt evidence
stays UNKNOWN and prevents later budgeted candidates from dispatching; confirmed
non-dispatch remains zero. Cancelling the parent cancels and joins its original
children and retains their unsettled accounting. This does not qualify durable
replay of an entire parallel parent request: do not resubmit a lost fan-out as a
new invocation; inspect original request/Work evidence first.
A child cancelled by its Provider is a failed child, not cancellation of the
parent. Its original uncertain accounting still stops later budgeted admission;
ordinary independent fan-out otherwise retains the existing minimum-success
policy. Actual parent cancellation continues to cancel and join its children.
Parallel numeric limits reject ambiguous types and non-finite values; a zero
aggregate cost/token budget prevents even the first child dispatch. Positive
aggregate budgets stop later admission and cancel pending work, but cannot undo
charges from concurrent requests already dispatched. Per-request/daily budget
reservations remain owned by CostController; this is not a vendor billing cap.

The Desktop's public model list projects the active Gateway registry. Declared
availability is not a successful health probe; absent benchmark price/latency
remain `null`/`UNKNOWN`, while explicit measured zero remains zero. Model choice
uses canonical `enabled` state. The client reads all advertised pages before
replacing list membership, bounded to 20 pages/10,000 records. Inconsistent or
changing pagination and a changed Controller are errors, not complete snapshots.
This live list neither grants permission nor replaces dispatch-time admission.

The current Chat handler supports text, model choice and execution mode. File
attachments and Node/privacy/per-request-budget controls are disabled because
this request path does not deliver them. Drop/paste and stale or crafted values
are refused before dispatch; the Composer preserves the draft. Existing saved
Workspace references, protected read tools and governed model/provider
configuration remain the supported route. Conversation attachment metadata is
not model input, and installation or selection grants no permission.

### Model usage and cost

The browser Operations Console exposes **Model Lab / Usage** (模型实验室 / 用量)
through the same read-only Model Lab pane, with UTC day selection and receipt
details. Opening this view preserves an unsaved workspace draft and exposes no
project or experiment mutation controls.

Model Lab's usage day selector and the native Desktop status bar read the same
`CostController.from_environment().summary()` journal exposed by
`GET /api/v1/usage`; Model Lab attaches that read as `usage_accounting`.
The Desktop never adds legacy observation costs into a second billing total.
An empty journal means no recorded cost measurement, and failed or unsupported
reads leave spend UNKNOWN. A changed Controller connection invalidates pending
reads and clears prior billing data.

The view separates reported, estimated and derived cost subtotals, unknown
receipts, pending requests and outstanding reservations. Nullable token totals
retain known and estimated subtotals without converting missing counters to zero.
Receipt detail preserves request, attempt and receipt references, model identity
and per-counter measurements without prompts or credential material. Lists show
at most 256 recent receipts while the existing Controller owns day aggregates.
Provider reported values are telemetry, not independently verified invoices.

Budget and price readiness come from the existing Controller policy. Host-selected
`APEIR_MODEL_PRICING_FILE` entries supply estimates; loaded entries do not prove
that every selected model is priced. Explicit token-only operation requires both
existing `APEIR_MAX_DAILY_COST_USD` and `APEIR_MAX_RETRY_COST_USD` to be
`none`. This read view never changes limits, installs a price registry or
reveals private configuration errors.

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

The existing `TestValidator` reports counts from pytest outcome fields. Runtime
duration and warning counts are not executed test counts. A zero exit code with
only skipped tests, or missing passing-test evidence, remains unverified. Its
own reporting contracts use a small actual child pytest suite; the full Runtime
and security suites still run through the normal CI matrix.

## Reviewing workspace changes

Open **Operations → Workspace**, edit saved files, and choose **Review draft
files**. The review uses the existing Workflow, Governance/Broker, Artifact CAS,
Workbench and deterministic verifier. Inspect exact paths, original/replacement
hashes and diffs. **Approve Once** uses the existing trusted human boundary;
**Deny** changes no files. A valid approval resumes that original Workflow.
A service permission policy may additionally be required; the feature never
creates permission rules or grants for itself. Installation and model output
are not execution authority.

**Ask** keeps collaboration read-only. **Edit** exposes proposal tools to a
configured, admitted model. It does not send unsaved editor contents automatically.
The model stops at approval and records the original proposal/approval/Artifact
IDs. Existing Work Harness checkpoints resume the original file operation after
approval, retain Work/Plan provenance, and record fresh file observation and
verification refs. An uncertain or partially applied write cannot re-enter the
model's write tool. An unavailable Kernel/model remains an explicit blocker.

Original bytes and replacement bytes live in CAS; Workflow inputs hold refs.
All existing files require their original SHA-256. Protected paths, secret
material, changed versions, expired/revoked authority and mismatched bindings
fail closed. Lists omit diffs; opening a detail computes the full reviewed diff
and checks its immutable artifacts. Both retain current file observations.

File MATCH is a checksum result in **runtime-service** scope. It is not a test
result, physical observation or Kernel execution. Multi-file edits are not a
universal atomic rollback: per-file intentions precede changes, and recovery
observes the original attempt without writing again. Cancellation fences later
admission and remains recorded even if an earlier effect is independently found.
A Chat project's remaining checks are not silently completed by a file MATCH.
Cancelling the source Work also cancels its original proposal Workflow, and late
tool results cannot revive the cancelled Work. A paused Work cannot admit edits
until explicitly resumed. Every file admission rereads the original Work and
manifest/Plan binding. A newly created Plan is bound from persisted Work when
the proposal is prepared, not from an earlier tool-construction snapshot.

The Runtime process has one Governance Gate. Configure `NOUS_WORKSPACE_ROOT`
before startup; an explicit proposal workspace can initialize that same Gate.
Once initialized, a different workspace cannot silently retarget its authority.
Normal capability seeding includes `project.read_file`; this declaration does
not grant `workspace.read` or approve a write.

Model-facing directory/move/remove/command/process-start/control shortcuts with
no qualified durable admission are unavailable. Existing trusted process
lifecycle helpers and governed Workbench fixed profiles remain distinct paths;
they do not certify a persistent PTY or an available strong sandbox.

## Model evidence

Model Lab distinguishes declared capability metadata from measured execution
observations. A model without observations is shown as awaiting evidence; a
zero sample count must not be interpreted as a zero quality score.

Context reads through `ContextGuard` require a caller-supplied authenticated
`AuthorizationContext`, a matching actor and a stated purpose. The guard uses
the existing Governance Gate and verifies the persisted decision binds the
current proposal and identity. Only `EXECUTE` admits a read; missing authority,
pending approval, unknown decisions and unavailable audit storage deny delivery.
Private items additionally require their explicit owner and a current trusted
local-human or authenticated human-session context. A copied identity claim is
insufficient. Agent policies come from the registry in the selected workspace.
This contract check does not itself wire every context producer into the guard,
grant access to workspace files or establish Provider receipt of a context.

## Current boundary

An explicit Runtime workspace root takes precedence over cwd/ancestor project
discovery. The existing registry may select an active child within that root;
an external registered workspace requires an explicit matching ID/name. Unknown,
ambiguous, pathless, linked or corrupt selections are unresolved, never a fallback
to a different project. The existing reserved `default` intent selector stays
within the configured root. Relative registry paths are anchored there. This is
scope selection, not file permission. A Chat conversation namespace remains an
ownership key in ConversationStore; it cannot choose a filesystem root.
Agent and Decision context providers read
the selected existing stores; an Agent profile is not a dictionary or authority.

Context, Evaluation and Experience state APIs retain an explicitly configured
`NOUS_WORKSPACE_ROOT` when that existing project has no `.nous` directory yet.
Their existing stores initialize only under that selected root, including direct
default store constructors and snapshot creation. Explicit store paths retain
their existing meaning; unconfigured constructors retain their cwd defaults.
Default Context collection binds its project readers through the same `project.workspace`
resolver. An invalid or unavailable configured root, resolver error, linked
`.nous` or non-directory state produces an error instead of reading cwd state.
The default initialized-only `find_workspace()` contract and unconfigured
cwd/ancestor discovery remain compatible. This extends existing store selection;
it adds no state owner, workspace registry or permission grant.

The existing Context, Evaluation and Experience SQLite connection boundaries
also reject symbolic/reparse links, multiply linked or nonregular database/sidecar files and a replaced linked
state directory before opening or creating state. A real `.nous` directory alone
does not certify the files within it. Healthy empty stores still return normal
empty history and zero statistics; an Evaluation initialization/list/statistics
failure or Experience list/statistics failure now raises its existing domain
exception so the API can report an error. These read models cannot establish
Operation authority or replace recorded EffectVerification. Read-only SQLite
connections use an encoded absolute file URI, preserving literal `#`, `?`, `%`,
spaces and Unicode names instead of interpreting filename text as URI control
syntax. Write connections retain their plain filesystem paths. This is static local
path admission, not protection against an OS owner changing a path after the
check, Windows ACL qualification or a new storage subsystem.

The same literal-path URI encoding is used by the existing GovernanceStore,
SQLiteRuntime (including integrity metrics), CapabilityRegistry, legacy Network
Registry and explicit SQLite Connector. This does not transfer trust or permission
between those owners; the Connector retains its explicitly selected database.
Nonlocal UNC URI authority is not qualified and unsupported SQLite builds fail
closed. NFS/SMB or cross-host shared runtime state remains unsupported.

Trusted Workflow handler registration can supply `WorkflowHandlerPolicy` from
the existing `nous_runtime.workflow` package, or a typed policy on the registered
host callable. A matching Capability contract declares retry safety and a bounded
retry budget. `reconcile_started=True` is reserved for handlers that consult the
original durable Work/effect journal; it is not permission for another effect.
Task inputs and model output cannot supply either declaration. On uncertain
failure, inspect the original run and checkpoints instead of submitting a new
operation. See [failure semantics](../architecture/STATE_OWNERSHIP.md#failure-and-recovery).

This release does not include model training, weight merging, dataset hosting,
or a visual workflow graph editor. Those systems may integrate through stable
Runtime contracts, but they must not bypass the Gateway, EventStream,
governance gate, or workspace boundary.

## Professional Workbench

Editor tabs reuse the existing file endpoints. Up to 12 open files retain
independent drafts, original digests, previews and write records in memory.
Selecting a cached tab does not call a model or read the file again; external
changes remain subject to the original backend hash conflict checks. Close and
reopen to read the current file. Arrow keys, Home and End navigate the tabs.
Dirty inactive tabs participate in exit, Environment navigation and execution
guards. Closing a dirty tab requires explicit discard; pending approval locks
navigation and retains the exact original write. Cached tabs cannot be reopened
under another Controller. File contents and drafts are not layout preferences or
browser-persisted state. Editor drafts are separate from the reviewed proposal
flow above; neither claims a universal atomic multi-file transaction.

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

Actual full-code PR #23 source cost was five active jobs, **513 job-seconds /
392 seconds feedback**. The initial documentation-only head of PR #25
(`406ca499e9b4b9a22d1ffa54ee20834d3928758d`) exercised the narrow path with all
three workflows passing: five active jobs, **122 job-seconds / 86 seconds
feedback**. Its later Console/preflight code commit selects full regression;
the resulting main still runs all platforms. These are observed workflow costs,
not a controlled runtime performance comparison or a reduced main quality gate.

The Product Closure main regression at `1a66e2514c222f432534b5362ae590ab789d20d7`
recorded **1 failed, 4083 passed, 53 skipped** on Windows in
[Core CI](https://github.com/untrod/apeir/actions/runs/38101910531): the existing
Model Gateway timeout test expected provider cancellation within a 10 ms total
request budget. That budget also includes routing and evidence recording; a
request that expires before dispatch must not invoke or cancel a provider.
The original log does not establish which deadline phase occurred. Tests now
control only Gateway accounting to cover both phases explicitly: a real asyncio
10 ms in-flight deadline still requires cancellation and lease cleanup, while a
controlled pre-dispatch expiry requires zero invocations and zero leases.
The provider's 100 ms delay, production timeouts, retry policy and runtime code
are unchanged. This test correction does not qualify Windows network timing or
close issues #4 and #8; their separate Relay failure evidence remains open.

For an explicit Windows Skill HTTP investigation, the existing Core workflow also
accepts `gh workflow run core-ci.yml --ref <reviewed-branch> -f diagnostic=windows-skill-http`.
It runs the original owned HTTP/TLS cases with bounded payload-free phase traces.
This diagnostic has separate check names and never supplies `Core gate` evidence;
default dispatch and main/release regression keep their existing full selection.
A passing fresh fixture cannot close the unresolved full-suite Windows timing
issue. See the [engineering review](../acceptance/ENGINEERING_REVIEW.md#windows-skill-http-phase-investigation--2026-10-21).

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
resolved. SDK acceptance requires a separate corrective PR and successful
source/main platform checks; original failures are not erased or rerun into acceptance.

Preview PR #25's resulting main `5ccbb6a4aec9deca9fcaec5c2c92af740932ea8c`
passed Core/Desktop/Security, but its [Windows Multi-Arch run
38007732190](https://github.com/untrod/apeir/actions/runs/38007732190) recorded
**1 failed, 3725 passed, 53 skipped, 272 deselected, 4 warnings**. The untouched
firmware response-loss/revoked-grant test stayed WAITING after its new observation
Work timed out; it neither repeated the effect nor falsely committed success.
This is additional evidence for [Issue #4](https://github.com/untrod/apeir/issues/4),
not a successful main Gate or a failure hidden by rerunning.

A controlled held REGISTER proves both the Demo and simulation fixture accepted
a persisted RESOURCE_REPORT as startup readiness before the new connection was
authenticated. Three controlled cases fail on that exact main, including a
four-second restart delay longer than the original three-second Work wait.
Startup now waits for an actual connection and a different signed RESOURCE_REPORT
message ID verified by the existing relay. The original fifteen-second readiness,
three-second Work wait, thirty-second Operation bound, heartbeat, fsync,
authority and at-most-once assertions are unchanged. This corrects a demonstrated
startup race; it does not prove every Windows observation/receipt deadline issue
resolved or close Issue #4. A corrective PR must pass source/dispatch and resulting
main matrices before the Preview checkpoint can be issued.

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

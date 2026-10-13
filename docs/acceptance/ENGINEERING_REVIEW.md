# Engineering review and research comparison

Review date: 2026-10-09. Read-only baseline: Distribution
`5c9cdd987af3823d4be9e6909311af65b9be2299`; frozen Kernel
`87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
[ROADMAP](../../ROADMAP.md) remains the sole current milestone-status source.
This record distinguishes reproduced defects, inspected risks and unqualified
external dependencies. It is not an exhaustive proof that the repository is
bug-free, a physical acceptance, or production certification.

## Product wiring audit — 2026-10-11

Read-only starting main was `e5424305ec90fb0a072f21fbef371ebd5bc110f6`;
local/remote HEAD matched and the worktree was clean. Requeried branches, open
PRs, Issues and latest main CI before editing. Issues #1/#2/#4/#8 remained open;
there were no open PRs. Kernel and the component lock remain frozen. This audit
extends the existing review, rather than creating another roadmap.

The repository is **not comprehensively product-qualified**. A registered route,
class, UI panel or passing fixture does not establish an installed, connected
product. A temporary route inventory found 422 callable registered handlers and
no missing complete URL references in the Desktop API client (78 on the starting
tree, 81 after three evidence helpers). Two dynamically assembled Research URL
prefixes were checked against their existing routes separately. This is a
registration check, not execution acceptance for all 422 endpoints.

| Surface and authoritative source | Classification | Exercised or inspected boundary / remaining gap |
| --- | --- | --- |
| Work/Workflow/AgentSession: `work/runtime.py`, `workflow/runtime.py`, `agent/coordination.py` | REUSE | Durable owners and recovery tests exist; local Work checkpoints and distributed Work are distinct scopes, not interchangeable success records |
| Governance/credentials: `governance/`, `control_plane/human_sessions.py` | REUSE | Existing approval, nonce, grant/lease, revocation and negative-security suites; real deployed IdP qualification remains unavailable |
| Verified Demo: `reality/preview.py`, `tests/reality/test_verified_preview.py` | REUSE | Real simulated mutation through signed Distributed Work, receipt, independent read and MATCH-only commit; no physical acceptance |
| Task filtering: `desktop/src/components/TaskCenter.tsx` | FIX | Counts included queued/planning/verifying, warning completion and verification failure while filters hid those rows; one shared status grouping now drives counts and rows |
| Task route composition: `api/routes.py`, `api/desktop_routes.py` | FIX | Later Control Plane registration hid the durable Work list and replaced Artifact reads with a newly constructed empty registry. The public routes now bind the existing Work/CAS projections, preserving pagination, status counts and legacy `total`. Actual HTTP tests cover the selected route, not merely a directly imported helper |
| Task timeline: `api/task_center_routes.py`, `events/stream.py` | FIX | The view read nonexistent `RunEvent.data` and discarded payloads; now retains original event/run/task/actor/sequence and the compatible `data` field. Task-ID and all-runs queries read bounded persisted evidence; legacy projected records are labelled |
| Run/Trace navigation: `App.tsx`, `TaskCenter.tsx`, `DeveloperWorkbench.tsx`, `DetailDrawer.tsx` | FIX | Search returned EventStream Run IDs but opened the unrelated ExecutionTracer endpoint. Run search now opens persisted activity; local Work activity opens its real task inspector. Workbench Chat Trace links now use the existing Trace inspector rather than querying a Run; original Controller changes are refused |
| Artifact search/detail: `api/routes.py`, `artifact/registry.py`, `artifact/content_store.py`, `DetailDrawer.tsx` | FIX | Search used only the legacy in-memory registry and detail was a static placeholder. Existing durable metadata and CAS are now searchable/readable; CAS bytes are checked by the existing store. Missing/corrupt records cannot display fake availability or a physical-effect claim |
| Task Artifact association: `api/task_center_routes.py` | FIX | Filesystem guesses omitted registered metadata/CAS. Existing task/work/operation provenance is now included; unregistered legacy files remain explicitly unverified metadata |
| Effect status: `api/task_center_routes.py`, `node_runtime/distributed_work.py` | FIX | A passing EvaluationRecord formerly set `verified=true`. Evaluation stays separate; only a bound recorded Reality MATCH can set that flag, with committed state shown separately. Reading this view performs no new Observation or verification |
| Operations Console: `control_plane/operations.py`, `OperationsConsole.tsx` | REUSE | Real owner projections, approvals, recovery, local Skills and Node pairing; source-browser acceptance is not installed EXE qualification |
| Workspace editor: `workspace/workbench.py`, `DeveloperWorkbench.tsx` | REUSE / EXTEND | Real bounded read/search/diff/governed save, hash conflicts, CAS backup, semantic activity and explicit metadata-only discussion. Up to 12 independent in-memory editor tabs now retain drafts/digests/diffs and exact pending approvals. Symbols, history/rollback UI and a model-generated multi-file proposal flow are not complete |
| Model context/cost: `context/`, `model_runtime/bridges.py`, `model_runtime/gateway.py` | EXTEND | Chat now records a content-free per-iteration input manifest after Agent admission, including rendered-context truncation and preceding file-read provenance. The inspector replays original EventStream Run IDs, retained through Conversation restart, and separates estimates from Provider usage. This covers application Chat Gateway input, not provider receipt, every collaborative invocation or a newly built Context snapshot |
| Context read admission: `context/security.py` | FIX | Bound caller identity and purpose, canonical persisted Governance decision, workspace-local Agent profile, current private owner and durable audit are required. Unauthenticated, copied, revoked, expired, mismatched and unknown reads deny. This is the public guard contract; complete RuntimePipeline integration remains separate |
| Chat input controls: `Composer.tsx`, `ChatView.tsx`, `lib/api.ts` | FIX / DEFER | File chips were selected locally but ignored by Chat dispatch; Node target, privacy and per-request budget selections were likewise ignored. Disable these unconnected controls and refuse stale/crafted values before model dispatch. Saved Workspace references and existing governed read remain usable; controlled attachment delivery is not implemented by this fix |
| Skill/Provider: `skills/`, public SDK, `tests/control_plane/test_skill_center.py` | REUSE / EXTEND | Reviewed local catalog install/load/enable/disable/uninstall with integrity and Governance. Instruction loading is not automatic executable Skill permission; general remote catalogs and real account-backed Providers need qualification |
| Pairing/mesh: `node_runtime/relay.py`, `node_runtime/service.py`, `tests/node_runtime/` | REUSE | Persistent stable Ed25519 identity, once invitations, atomic consumption, revoke-preserving trust and signed Relay exist. Real Windows/Jetson/WAN/CGNAT acceptance and timing Issues #4/#8 remain open |
| Environment: `environments/`, `EnvironmentInspector.tsx` | REUSE / DEFER | Lifecycle/contracts/evidence and governed UI exist. Default strict process isolation is unavailable here; engine presence alone does not qualify the existing OCI control boundary. Python/scientific/embedded/robotics template promises cannot be inferred from a selector |
| Terminal: `cli/terminal_session.py`, `cli/shell.py` | REUSE / EXTEND | Existing bounded sessions/commands; the workspace fixed-profile execution panel is not a persistent PTY or complete local/remote/container Terminal Studio |
| Automation API: `api/desktop_routes.py` | DEFER | `automations.json` CRUD persists configuration; inspection found no consumer of that file driving the canonical Workflow Runtime. Enabled configuration is not an executed schedule or Workflow Recorder |
| Legacy v2 research/plugin/genome endpoints: `api/v2_routes.py` | DEFER | Six handlers explicitly return `NOUS_NOT_IMPLEMENTED`; they are not functioning integrations. Research Claims and reports use the existing v1 Evidence/Document owners |
| Research/reporting: `evidence/`, `documents/`, `scientific/`, `simulations/` | REUSE / DEFER | Numerical claims, independent reference, Artifact and report contracts exist; strict-sandbox numerical qualification stays blocked, and manually supplied experiment scores are not a completed engineering-loop experiment |
| Native Desktop/release: component lock, `desktop/src-tauri/`, build runbook | DEFER | Two exact locked Windows Kernel binary files remain missing; no native hash, NSIS, installed UI, uninstall or production-signing qualification can be inferred from frontend CI |

The subsequent Context admission correction reuses the existing Gate, permission
engine, GovernanceStore, ContextStore audit, AgentRegistry and trusted human
session boundary. Controlled pre-change checks retained **15 failures**. Final
Context/Governance/human-session regressions have **464 passed**, and repository
contracts have **262 passed**. Global Ruff, changed-file formatting, compile,
documentation/link/comment/identity/git hygiene and eight version manifests pass.
Security scanning retains **0 HIGH / 3 unchanged MEDIUM** findings. The Kernel
and component lock are unchanged. These results cover the guard contract; they
do not establish complete context-pipeline wiring, real IdP qualification or
native binary integrity. Required PR/main CI is a separate integration gate.

PR #47 passed Core, Desktop and Security CI; its full Linux regression had
**4194 passed, 49 skipped, 4 warnings**. Merge
`999c36f51afcaadba4065aafa1e3de39d2a1f905` subsequently exposed a Windows
timeout in the pre-existing `TestValidator` reporting test, which launched the
entire Context directory under the outer test's unchanged 60-second deadline.
The [failed main run](https://github.com/untrod/apeir/actions/runs/38204677255)
is retained. That log identifies the waiting child, not its exact internal slow
test; the main Gate must not be represented as green.

The corrective reporting test uses a real bounded pytest fixture with passing,
skipped, failing and collection-error cases, and strengthens evidence assertions.
All Context/security tests remain in the ordinary full CI suite. No timeout or
assertion is relaxed. The existing validator now counts outcome fields instead
of duration digits, and an all-skipped result cannot claim test success. Local
Context/evaluation/repository regressions have **590 passed**. The original
reporting case took **3.87 s** locally with the full Context directory; the
focused child case took **0.26 s**. These are individual test observations, not
a claim about total CI savings, model cost or Windows qualification. Corrected
PR and main CI remain required.

Workspace scope correction (**REUSE / FIX**) keeps the existing Registry,
resolver and Context providers. Nine pre-change cases fail and three pass:
a configured host root can be displaced by cwd discovery, external active
registrations and unresolved selectors; linked/corrupt records are not fenced.
Final workspace/Runtime/Context regressions have **245 passed**. They preserve
legacy discovery without an explicit root and the existing reserved `default`
selector while refusing unknown/pathless/ambiguous selections, relative-path
misbinding, prefix siblings, symlink escapes and corrupt authority files.
Actual registered Agent profiles now produce context in the selected store;
Decision health and collection consult the same selected store. A second integration check exposed four cases where Intent resolution had
filled a cwd-derived workspace ID before the host root was available. Runtime
now uses the explicit request selector and records its actual resolved scope.
Selection alone never grants file access or proves model delivery. Kernel and lock are unchanged;
required CI remains an integration prerequisite.

The first scope PR full run retained **1 failed, 4254 passed, 49 skipped,
4 warnings** ([CI evidence](https://github.com/untrod/apeir/actions/runs/38239019364)).
The failed project-restart flow exposed another existing conflation: Chat used
its conversation namespace as a filesystem workspace selector. Chat now keeps
that namespace for conversation ownership and uses its trusted Runtime root for
execution. The original restart/evidence assertions are unchanged, and a new
case proves an external-looking namespace cannot select another filesystem.
Expanded scope/Context/Chat/conversation/project-restart regressions have
**271 passed**. Corrective PR and resulting main CI remain required.

Workflow recovery hardening reuses `WorkflowRuntime`, `WorkflowStore`, the
existing TaskGraph, AgentSession coordinator, and journal-backed distributed,
Reality and external-agent handlers (**REUSE / FIX / EXTEND**). Pre-change
recovery diagnostics retained repeated effects; the initial affected regression
also exposed an unclassified pure dictionary fixture (**1 failed, 457 passed,
25 skipped**). That fixture now declares its actual host-owned pure Capability
contract. The new negative Agent case separately proves an uncertain effect
cannot enter replanning or execute again after restart.

Definition, input, checkpoint, output and handler-policy bindings are checked;
parallel completion, cancellation, durable attempt limits, process restart,
missing completion evidence, copied policy and model-supplied retry flags are
covered. Started generic effects become UNKNOWN; only existing journal-backed
handlers can reconcile their original Work. An approval never establishes retry
safety. Legacy unfinished completion evidence with missing bindings is fenced,
not silently promoted to success. Focused contracts have **50 passed**; affected
Agent/Workflow/intelligence/Reality/Node/interoperability/Control Plane regressions
have **672 passed, 25 skipped**; repository contracts have **265 passed**.
Ruff, changed-file format, compile, docs/235 link targets, hygiene, eight version
manifests and security (**0 HIGH / 3 unchanged MEDIUM**) pass locally. Required
PR and main CI remain separate prerequisites. Automation configuration consumption,
installed Desktop, native hashes, real identity and physical hardware are not
qualified by this correction. Kernel and the component lock remain unchanged.

Reviewed multi-file changes (**REUSE / EXTEND / FIX**) now compose existing
Workflow/Store, Governance/Broker, Work Harness/Agent execution, Artifact CAS,
Workbench, EventStream and deterministic verification. The Desktop exposes draft
review plus Ask/Edit collaboration. Model file tools prepare immutable proposals;
they cannot apply files or issue approvals. Original Work resumes the exact
paused operation after valid human approval. Partial writes remain UNKNOWN;
complete lost responses are reconciled with fresh byte evidence, without
another write. Deny, conflicting versions, wrong Work/Plan/authority, expiry,
revocation, cancellation, tampered CAS and registered fake-secret leakage are
covered. Unsafe model-facing host effect shortcuts remain blocked; this is not
persistent Terminal qualification or a replacement executor.

Focused proposal/Work/API contracts: **45 passed**, including **9 API contracts**
and the protected real HTTP round trip. Affected model/Work/Workflow/Governance/
Control Plane/Reality/Node regressions: **930 passed**; repository contracts:
**267 passed**. Desktop: **135 passed in 31 files**, lint/typecheck/build pass.
The initial implementation integration retained **10 failed, 111 passed,
2 skipped**: eight legacy assumptions about implicit model authority and two
unchanged bare-host orphan failures. Authority assertions now require original
human approval or prove no launch/mutation; original process identity assertions
remain intact. Later model integration retained **2 failed, 134 passed** before
its fixtures were updated to review original operations rather than assume a
model response authorized writes. The passing model/Work/file subset has
**136 passed**. Real HTTP qualification uses a fake service token and the
existing trusted local-human test context; it does not authenticate a remote IdP.

A measured list microbenchmark used 20 pending proposals, five reads before and
five after, and zero model calls/effects. CAS resolutions per list changed
**100 → 60** by deferring diffs until detail inspection. These local source API
observations are not general latency, token, billing or remote-scale claims.
Ruff/changed-file format/compile/docs/hygiene/security/version and required CI
remain the integration gate. Known native, strong-sandbox, account-backed model,
physical and production blockers remain unchanged; Kernel and component lock
are frozen. Chat project completion still requires its actual remaining checks,
not merely file MATCH; Source-browser/HTTP checks do not certify installed EXE.

The review correction retained three failing cancellation/Plan cases and one
additional cancellation-during-preparation race. A late tool checkpoint could
otherwise revive a cancelled Work. The existing Work checkpoint owner now
serializes updates with the existing file lock and keeps cancellation monotonic;
new evidence can be retained without reauthorizing execution. Cancellation of
the source Work also fences its original proposal Workflow. Each file admission
rechecks the original Work, pause/cancel state, pending manifest and current
Plan. Tools obtain the Plan binding from persisted Work at preparation time.
Already recorded effects remain observable and cannot be blindly replayed.

Two first-use defects were also reproduced: cwd could initialize Governance
outside the selected workspace, and ordinary capability seeding omitted the
existing `project.read_file` declaration used by proposal inspection. Default
Governance now honors the configured host root, an explicit workspace can
initialize the one process Gate, and an existing different Gate is rejected
rather than replaced. Normal seeding declares read semantics; it grants no
permission. The API tests now use that seeding instead of manually registering
the missing capability. Focused proposal contracts have **53 passed**; the
proposal, original Work and collaboration subset has **83 passed**. A paused
source Work is blocked before execution admission; explicit resume retains the
original approval and file operation. Expanded affected regressions have
**955 passed**; lifecycle-seeding/API/repository checks have **282 passed**.
The initial
PR full regression retained **1 failed, 4303 passed, 47 skipped, 4 warnings**
([CI evidence](https://github.com/untrod/apeir/actions/runs/38250757991)).
Its legacy batch-write test now proves no mutation before original human
approval and verifies real admission, file observation and CAS evidence after
approval. No deadline, isolation or process-identity assertion is relaxed.

The resulting main `d19a22e876eeba66517b13f9e3e7ac06d2e1465c` retained
Windows failures: Core **3 failed, 4304 passed, 51 skipped, 4 warnings**
([run](https://github.com/untrod/apeir/actions/runs/38273450895)); Multi-Arch
Windows **2 failed, 4012 passed, 51 skipped, 272 deselected, 4 warnings**
([run](https://github.com/untrod/apeir/actions/runs/38273451016)). Two failures
came from new fixtures using translated text writes while expecting an LF byte
hash. Runtime correctly refused the mismatched original bytes. The correction
uses explicit bytes and covers LF, CRLF, unchanged original CAS/backup bytes and
rejection of a normalized digest. It does not change hashing or conflict checks.
The remaining Core failure first timed out awaiting the lost response result;
its final short freshness-lease assertion masked that earlier timeout. This is
unresolved Relay timing evidence, not grounds to extend deadlines or close
Issues #4/#8. The full main Gate is not green at this commit.

A separate execution-boundary review (**REUSE / FIX**) reproduced six failures
and one passing server-denial case: compatibility surfaces could dispatch after
a Governance exception, and UNKNOWN, a missing/false allow flag or RECOMMEND
could continue. Only explicit `allowed=True` plus EXECUTE now admits dispatch.
Exceptions fail closed on every surface and report only their type. A further
controlled file-read case read outside the resolved workspace through request
metadata `workspace_path`. Runtime now binds tool scope to its existing resolver;
metadata cannot retarget it. No new permission or execution system is added.
The public Runtime API also now passes its configured host root to the same
Orchestrator; another pre-change fixture confirmed that entry left the root
empty. Existing caller identity/spoofing checks remain intact.
The final local affected regression has **898 passed**; the byte-version and
proposal/Workbench subset has **67 passed**. Required CI remains a separate Gate.

The multi-file editing slice reuses the existing Workbench endpoints and keeps
draft state within the existing component; it adds no filesystem, proposal store,
permission or execution authority. Seven new frontend cases cover independent
drafts/digests/previews, inactive-draft exit and execution protection, exact
approval binding, keyboard navigation, changed Controllers, failed reads, the
12-tab bound and explicit discard/reload. Five initial cases fail before the
feature; the original discard-before-switch test is strengthened to verify
preserved contents and renamed paths across tabs instead of requiring discard.
Local validation has **129 Desktop tests in 30 files** and **264 repository tests
passed**, with lint/typecheck/build, global Ruff/compile, all 235 Markdown links,
document/comment/identity/git hygiene, eight version manifests and **0 HIGH /
3 unchanged MEDIUM** security findings. No Python or Runtime owner changes;
the preceding full bare-host regression and its two orphan failures remain
recorded below. Browser candidate qualification uses actual protected Runtime
file reads and diff endpoints, confirms independent drafts and explicit discard,
no file mutation, no model calls for editor navigation, and no 390px overflow.
It remains source-browser qualification with the explicit test-only fake model
adapter, not installed Desktop, real IdP or a multi-file model proposal Gate.

The focused correction reproduces the old timeline payload loss, false
evaluation/effect equivalence and missing registered Task Artifacts before
changing the implementation. It replaces both evidence drawer placeholders,
surfaces load errors, clears stale detail data when the selected ID changes,
and disables approval actions when the original record cannot be loaded.
No new registry, permission source, verifier, workflow or executor is introduced.
CAS integrity is distinct from effect verification; the UI states explicitly
that recorded evidence does not acquire a fresh observation.

The subsequent Context Inspector slice reuses `ContextExplainer`, the admitted
Chat Gateway, ConversationStore and EventStream. Only their input-manifest
helper, Chat invocation boundary and additive conversation Run/task projection
change Python semantics; other changes in those files are the existing required
formatter. The Workbench can inspect a recorded Run without a model account or
a new inference call. Live/response Chat inspection retains separate Run and
Trace identities. Missing manifests/usage, denied reads and truncated replay
cannot display invented access or success.

The October 12 Context delivery audit classifies the existing ContextGuard,
Builder, snapshots, default readers, Runtime/Chat entries and input inspector as
**REUSE / EXTEND**; actor-claim fallback, silent Gateway clipping and default
state-path/record-shape mismatches are **FIX**. The normal reader declaration,
live identity forwarding, whole-item budget selection, source/owner/version
checksums and continuation admission extend those owners. Real Provider cost
comparison, cross-task cache qualification and installed Desktop remain
**DEFER / BLOCKED**, not claimed performance improvements.

Normal-source probes first retained **2 failed**: initialization omitted the
reader, so an owned source never reached the product handler. After declaration,
the actual JSONL memory API exposed a second defect: its mappings were treated
as attribute objects and active facts were dropped. The existing MemoryProvider
now reads both canonical mappings and legacy objects. A real memory writer and
project configuration reach the real Runtime handler with live local-owner
attestation; source permissions still deny by default when configured, disabled
capabilities stay disabled, and no attestation is serialized. CLI additionally
binds its configured host root and current local attestation. A negative probe
also proved source text was copied into general Context telemetry; those events
and Trace entries now carry only snapshot IDs, counts, checksum and admission
references. Actual source text remains in the admitted live input. The Context,
reader, CLI and product focused subset has **72 passed**. Long-item, item-budget,
secret-filtering, checksum, identity and between-call revocation cases retain
fail-closed evidence. This is a software input boundary, not authenticated live
model, native Desktop or physical qualification. The expanded Context/Runtime/
Governance/model/Agent/Work/Control Plane/Chat/proposal regressions have **1015
passed**. The final local repository contracts have **276 passed**. Ruff, changed-file format,
compile, 235 Markdown links, document/comment/identity/git hygiene, eight version
manifests and security (**0 HIGH / 3 unchanged MEDIUM**) pass locally. Required
PR and resulting main checks remain separate integration evidence.
An installed editable `apeir runtime run status --json` in a fresh temporary
workspace exits zero and records the actual project context and private Context
audit location. It makes no model call and does not qualify Kernel/native health
or a physical effect.

Local candidate validation: **19 focused / 819 affected / 262 repository tests
passed**, **110 Desktop tests in 29 files passed**, lint/typecheck/build,
Ruff/changed-file format/compile and all 235 Markdown link checks passed.
Full bare-host regression: **4126 passed, 60 skipped, 2 existing orphan-process
failures, 4 warnings**. The two failures remain the unsupported PID-1/reaper
conditions documented in CONTRIBUTING; no assertion or test selection changed.
Security scan: **0 HIGH / 3 unchanged MEDIUM**. Actual native hash verification
still fails on missing locked Windows bytes; component-lock contracts pass.

An actual sandboxed Chromium source-browser run reads the real Runtime HTTP
and persisted three-iteration Gateway/Conversation/EventStream records, with
a fake MockModelAdapter. It confirms `main.py` was read, `.nous/private.txt`
was refused, no file changed, and reloaded Run inspection calls no model.
Mobile 390px has no horizontal overflow and there are no page errors. This
uses the explicit test-only Gateway compatibility mode, not product Kernel
inference or authenticated real-model/IdP/native Desktop qualification.
Screenshots and raw scoped records remain local evidence, not source fixtures
or preset success JSON.

The incremental cost measurement alternates 40 baseline and 40 manifest runs
against a deterministic fake adapter, using eight 2,048-character context items
and real EventStream persistence. Local p50/p95/p99 milliseconds are
**11.539 / 15.449 / 43.653** at main `339b086` and
**12.575 / 13.830 / 23.976** with the manifest; median event bytes are
**1,730 → 4,429**. The p50 overhead is 1.036 ms. These small local samples
are instrumentation cost, not a performance improvement, WAN/Relay result,
real model benchmark or a completed engineering-loop research experiment.
No durability, fsync, isolation, resource default or authorization was relaxed.

A separate Chat admission correction extends only the existing Composer and
ChatView. Four initial reproduction tests failed on unchanged main: file
selection remained enabled, dropped/pasted files appeared accepted, and a crafted
attachment reached model dispatch. The corrected UI preserves the typed draft
when refusing unsupported files, creates no image preview and sends no model
request or event subscription for unsupported input. Additional negative cases
cover a handler losing support before Send and crafted Node/privacy/budget
values, including a zero budget. Model and execution-mode controls remain usable;
the Workspace assistant still enforces read-only at dispatch.

No file upload, secret access or new execution authority is added. Existing
API `attachment_ids` refer to Conversation attachment metadata and retain their
compatibility contract; they are not proof of model delivery. A future attachment
implementation must bind protected Artifact content, authorization and the actual
Gateway input. Local selection, installation or a file reference must never be
shown as evidence that a model received file contents.

Chat correction validation: **15 focused tests** and **120 Desktop tests in
30 files**, lint/typecheck/build passed. **264 repository tests** passed;
Ruff/compile, 235 Markdown link targets, hygiene/identity/metadata/version checks
passed. Security scan remains **0 HIGH / 3 existing MEDIUM**. A sandboxed source
Chromium run against the real Runtime HTTP confirms file drop/paste rejection,
draft retention, zero image previews, disabled unsupported request controls and
zero Chat/model requests, with no page errors or 390px overflow. These source
checks use the explicitly labelled fake-adapter evidence fixture; they do not
qualify installed Windows Desktop or real model/identity/hardware paths.

File-read evidence review reproduced a separate consistency defect in
`chat/agent_tools.py`: a controlled edit between text reading and the second
byte read returned the old content with the new file's digest. Two regression
cases fail on the original implementation, including growth after the size
precheck. The existing tool now obtains one bounded byte buffer, checks its
actual size, decodes the selected lines and hashes that same buffer. UTF-8 and
LF/CRLF/CR behavior and the 256 KiB limit are retained. Permission/path checks,
Governance, model admission and EffectVerification do not change. This binds
the tool's content and digest; it does not lock out subsequent user edits or
provide an atomic filesystem snapshot or independent physical Observation.

Snapshot correction validation: **194 focused passed / 2 skipped**, **956
affected passed / 2 skipped**, **264 repository tests passed**. Full bare-host
regression: **4134 passed / 60 skipped / 2 unchanged orphan-process failures /
4 warnings**, 283.03 seconds. Both failures are the same unsupported bare-PID-1
cleanup assertions recorded above, not relaxed or skipped. Ruff, two changed
Python format checks, compile, 235 Markdown links, standard hygiene/version
checks and **0 HIGH / 3 existing MEDIUM** security findings are recorded. No UI,
Kernel, component lock, sandbox defaults or execution/retry policy change is
required for this correction; source/main platform CI is reported in its PR.

The same evidence review found Workbench's Chat Trace callback still queried
Run events. Reuse the existing DetailDrawer/ExecutionTracer path instead of
opening a misleading empty Run. Two controlled frontend cases fail before the
correction and verify both the original Trace endpoint and refusal after a
Controller change. **122 Desktop tests in 30 files**, lint/typecheck/build pass.
The Snapshot Python changes have not changed since the full run above; no second
local full Python run is needed for this bounded UI wiring correction.

Two configuration distinctions also remain relevant: the main Tasks view covers
local Work/Runtime tasks, while signed distributed Works are exposed through
Operations; legacy Connectivity nodes and signed Relay nodes likewise have
different owners. A panel title cannot merge their identities or trust. Some
legacy API defaults use HOME-based storage while newer workspace services use
the configured workspace. Configure `NOUS_WORKSPACE_ROOT` and the existing
`NOUS_DATA_DIR` explicitly for reproducible development; this correction does
not silently migrate those stores or create a second registry. Legacy Task
report/event/graph helpers do not provide full distributed evidence coverage;
use the canonical Operations views and recorded effect endpoint.

Performance scope is bounded: Artifact search reads metadata, while list results
verify content only for the selected bounded window. Existing CAS index loading
and legacy filesystem scans still need measurement for large workspaces;
this correction claims no unmeasured latency/Token improvement and changes no
fsync, grant fence, sandbox profile or retry semantics. Production installation,
physical/network qualification and research experiments remain separate Gates.

Final local correction evidence: **66 focused passed**, **1030 affected passed /
4 skipped**, **262 repository passed**, and **98 Desktop tests in 28 files**;
Desktop lint/typecheck/build also pass. Full bare-host regression is **4119 passed /
60 skipped / 2 failures / 4 existing warnings** (284.69 s). The two unchanged
process-session orphan cleanup assertions see zombies retained by bare PID 1;
their assertions and failure logs are preserved, not skipped. No new regression
remains in that final run. Ruff, changed-file formatting, compile, 235 Markdown
link targets, hygiene/identity/metadata/version and security checks pass; security
has zero HIGH and three existing MEDIUM findings. Component-lock contract tests
have **3 passed**, while actual native hash verification again fails on the
missing locked Windows daemon. PR/main platform CI is reported separately in
the integration PR; these local results do not substitute for it.

## Repository and architecture audit

Requeried GitHub branches, PRs, issues and baseline workflow runs. Local HEAD and
origin/main matched with a clean worktree. Only main remained remotely, no PR
was open, and 26 checkpoint tags were retained. Baseline Core, Multi-Arch,
Desktop and Security runs were respectively 37912578545, 37912578603,
37912578593 and 37912578643; all completed successfully on the exact baseline.
Kernel and component-lock diffs against the accepted consolidation baseline
`d95589908f7686210126b75f8033e6bf494f9fb7` were empty.

The audit covered repository instructions, canonical architecture, public SDK
and packaging declarations, Actions matrices, authoritative execution and
recovery paths, Governance persistence, remote human boundary and acceptance
records. Classification refers to existing owners, not proposed replacements:

| Concern | Classification | Existing owner / remaining qualification |
| --- | --- | --- |
| Work, Workflow and Agent coordination | REUSE | Existing Work stores, Workflow Runtime and AgentSessionCoordinator; no second orchestration system |
| Operation admission and approval | REUSE | Governance Gate/Broker/Store; models and scheduling cannot grant authority |
| Remote spool admission | EXTEND | Existing remote provider plus canonical `locking.file_lock`; findings below |
| Credential resolution/redaction | REUSE | CredentialBroker, execution-time context and protected SecretBackend; production backend lifecycle qualification remains separate |
| Human identity | EXTEND | Existing OIDC/session boundary; deployed IdP and browser/mobile human qualification still missing |
| Device, evidence and verification | REUSE | DeviceRegistry, CAS, independent read Work and EffectVerifier; physical qualification missing |
| External execution | EXTEND | Native/OCI and bounded Ray diagnostic; production resource profiles and complete real adapters remain unqualified |
| Performance observability | EXTEND | Existing events, audit and timing evidence; correlated queue/lock/fsync latency measurements are needed |
| Native release integrity | MISSING | Locked binary bytes unavailable; contract tests cannot establish their hashes |
| HA/federation and public benchmark acceptance | MISSING | M6/M7 remain future Gates; preparation is not acceptance |

## Reproduced defects and bounded correction

1. **Non-finite remote timeout.** The old adapter converted `timeout_ms` with
   `float()` and used it in a monotonic deadline. NaN makes the comparison false;
   infinity removes a finite polling deadline. Twelve rejection cases fail on
   the original implementation, including ambiguous booleans, negative values,
   malformed text and overflowing numbers. Correction rejects these values
   before any spool persistence. Existing finite numeric inputs, the 30-second
   default and the legacy zero/sub-millisecond floor of one millisecond remain
   compatible. This is a result-polling budget, not a hard OS deadline for fsync
   or file-lock acquisition.
2. **Concurrent operation binding replacement.** The original check/write pair
   was unprotected and used one `.json.tmp` filename per Operation. A controlled
   two-thread reproduction admitted two different inputs for the same Operation
   ID and replaced its durable request. Correction reuses the existing
   cross-platform per-file lock around comparison and initial publication.
   Same-binding callers share the original request; changed bindings fail closed.
   The lock is released before result polling, so different Operations and the
   Relay can progress. Atomic rename and fsync remain intact.

3. **Connector retry-budget overrun and lost zero setting.** The existing Connector Runtime used an
   off-by-one exhaustion condition. Even `retries=0` allowed a second invocation,
   including a non-idempotent write whose first effect happened before a temporary
   response error. Five new negative cases fail before correction. Honor the
   declared additional-attempt budget. Manifest decoding also replaced explicit
   zero with the default two retries; preserve zero across store reload. A
   non-idempotent call executes once, while
   explicitly idempotent calls retain their bounded retries. This is an existing
   legacy Connector path correction, not a new Work executor or a claim that its
   metadata provides complete effect/idempotency proof.

Contract coverage includes competing and duplicate admission, invalid/compatible
timeouts, immutable collision evidence, cached Receipt mismatch and fresh-process
recovery after response loss. Adapter fixture receipts only test binding; real
signed Node Protocol coverage remains in its existing integration suite. Recovery
reads the persisted original result and never republishes a possible side effect.
No Kernel, authorization, credential or sandbox limit changes are required.

## Configuration gaps and unresolved failures

- Real OIDC human approval and authenticated Codex Provider qualification require
  actual service/deployment access. Fake identities, CLI discovery or prepared
  contracts do not close those Gates. Do not build a password database or invent
  an external task API to replace missing access.
- GitHub administration previously returned 403. Current branch protection is
  not evidence that all recommended PR/CI/conversation and immutable-tag settings
  were applied. The exact maintainer settings remain in ROADMAP; no new settings
  are claimed by this change.
- Issues [#1](https://github.com/untrod/apeir/issues/1) and
  [#2](https://github.com/untrod/apeir/issues/2) track physical acceptance and native
  binary hashes. Issues [#4](https://github.com/untrod/apeir/issues/4) and
  [#8](https://github.com/untrod/apeir/issues/8) retain recovery/shutdown timing
  evidence. PR19's first Windows run had two failures (3923 passed, 53 skipped);
  its retry and subsequent main runs passed. That does not prove a race absent
  or establish these new admission defects as their cause.
- **SQLite runtime qualification:** the audit host reports SQLite 3.53.1, while
  the pinned initialized full-regression container reports 3.46.1. Upstream
  documents a rare WAL-reset corruption race, fixed in 3.51.3 and named backports
  3.44.6/3.50.7. Version strings alone cannot establish a vendor backport.
  Governance opens WAL connections; qualify each supported interpreter's linked
  SQLite and patch provenance before production/release acceptance. This review
  did not reproduce corruption or qualify all CI platform libraries. Do not
  disable WAL, remove durable writes or replace the database opportunistically.
  See [SQLite's upstream analysis](https://sqlite.org/wal.html#walreset).

## Performance assessment and safe priorities

These are inspected cost paths and proposed measurements, not claimed throughput
improvements. Preserve fail-closed and persistence semantics in every comparison.

| Priority | Concrete path | Measurement / decision before optimization |
| --- | --- | --- |
| P1 | Relay `_run_provider_spool` sorts and ingests all pending JSON requests every 50 ms | Measure pending count, per-pass reads, event-loop lag and p50/p95/p99 queue-to-admission latency under reconnect/backpressure. Terminal requests are already removed by `_publish_provider_result`; this is not an ever-growing scan of all completed history. Consider bounded scheduling/indexing only with restart and duplicate-delivery contracts preserved. |
| P1 | GovernanceStore opens a connection per operation; `operation_transaction` uses BEGIN IMMEDIATE | Measure connection/checkpoint and writer-lock wait, including concurrent revocation. WAL still has one writer. Do not release the effect's authorization fence or cache grants across revocation to improve benchmark numbers. |
| P1 | Node/Controller sequence publication and client session/probes now use guarded thread offload; other Relay state publication remains synchronous | Controlled ordering/cancellation cases exercise the correction below. Continue correlating Node journal, signed delivery, Controller projection and Workflow wake timestamps for #4/#8. A timeout is an unknown outcome, not permission to repeat the effect; Windows timing and fleet behavior remain unqualified. |
| P2 | Bounded Ray startup and process topology | Prior qualification observed peak 213 PID-accounted tasks at diagnostic bound 216, with owned cleanup. This narrow margin is not a production minimum. Measure cold/warm execution and useful-work cost before choosing Ray over Native/OCI for small tasks. Default PID64 remains unchanged; an explicit governed provider profile is required. |
| P2 | CI repeats broad platform matrices on source and main | Preserve required checks and broad main/release coverage; assess branch/PR overlap and setup caches using actual durations. Do not hide failures, weaken security checks or skip native hash qualification. |
| P2 | OPA policy evaluation | Benchmark the actual policy/input and separate evaluation, HTTP, audit and persistence costs. A policy-only microbenchmark cannot establish end-to-end admission latency. |

## External projects and commercial systems

Sources were checked on the review date. Upstream current documentation is not
qualification of APEIR's pinned versions or proof of a real integration.

| Primary source | Relevant lesson | APEIR action / boundary |
| --- | --- | --- |
| [Temporal Activity execution](https://docs.temporal.io/activity-execution) | Durable orchestration separates scheduled execution and reported completion | Compare retry/recovery semantics; uncertain physical effects still require APEIR evidence and Observation rather than automatic Activity-style replay |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Checkpoints support interruption and continuity; in-memory storage does not survive restart | Use agent harnesses as replaceable Providers, not a second Work/Workflow authority; existing durable stores remain canonical |
| [Ray security](https://docs.ray.io/en/latest/ray-security/index.html) | Ray runs trusted code; isolation is enforced outside the cluster | Keep network/OS/credential boundaries; token authentication added after APEIR's pinned 2.49.2 cannot be claimed for that diagnostic |
| [OPA performance](https://www.openpolicyagent.org/docs/policy-performance) | Profile real policies and distinguish prepared query evaluation from full setup | Reuse PolicyProvider evaluation under existing Governance, never delegate grant issuance to OPA |
| [SQLite WAL](https://sqlite.org/wal.html) | Reader concurrency does not mean concurrent writers; checkpointing affects latency and durability | Measure before pooling or tuning; qualify actual linked library and upstream fixes |
| [OpenAI prompt-injection design](https://openai.com/index/designing-agents-to-resist-prompt-injection/) | Layered controls bound impact even when a model encounters hostile instructions | Treat agent output as untrusted proposals and bind approvals/evidence at Runtime boundaries; model defenses cannot supply authority |
| [Claude Managed Agents permission policies](https://platform.claude.com/docs/en/managed-agents/permission-policies) | Hosted tool calls expose allow/ask/deny evaluation and confirmation binding | Translate Provider requests into existing Governance; a hosted confirmation is not automatically APEIR human identity or authorization |

Commercial product documentation describes public behavior, not inspected closed
source or an independently audited security guarantee. No account-backed
OpenAI/Anthropic integration was exercised by reading those pages.

## Recent research and limits

The selected 2026 papers are primary-source preprints, not an exhaustive review
or proof that their results transfer to APEIR. Abstracts/metadata were reviewed;
experiments were not independently reproduced.

- [CoSec](https://arxiv.org/abs/2609.34790), September 28 (revised September 29),
  evaluates 208 community authorization/privacy scenarios with persistent agents,
  traces and artifacts. Useful future benchmark extensions include cross-session
  protected data, membership revocation and composed workflows. Task completion
  must not substitute for authorization compliance.
- [ToolGuardian](https://arxiv.org/abs/2607.21835), July 23, separates tool
  characterization from deterministic policy evaluation; its study uses 16 tools
  and 20 runtime scenarios. Conformance facts from sandboxed tracing/mock effects
  could feed existing Governance. Do not add a competing ASP authority or trust
  metadata alone; small reported results are not universal safety guarantees.
- [From Tool Connection to Execution Control](https://arxiv.org/abs/2606.29073),
  June 27, benchmarks explicit runtime invariants including principal binding,
  scoped invocation and denial audit. Its narrow cases and in-memory timing do
  not establish durable APEIR latency or physical effect correctness. Adopt
  evidence-backed negative scenarios, not another protocol/authority ledger.

## Follow-through

Close this bounded admission repair through focused tests, affected/full
regressions, standard repository checks and a normal PR merge. Then prioritize
SQLite environment qualification and instrumented #4/#8 investigation as
separate coherent Gates. Continue real identity/Codex/provider qualification
where access exists. Physical M3.3-C/M5 and a second real device family remain
PENDING; native hashes remain BLOCKED. M6 depends on stable M3–M5 contracts and
M7 has no completed public benchmark Gate. This review cannot upgrade them.

## Local validation of the initial remote admission repair

- Focused contracts: **24 passed**, 1.03 s. Original implementation rejection
  comparison: **12 failed**, 12 deselected; no raw values enter durable state
  after the correction.
- Affected Node, Task/Work, Agent, Workflow, Reality, Governance, Control Plane,
  SDK and interoperability regressions: **873 passed, 25 skipped**, 69.75 s.
- Full initialized, unprivileged, network-isolated supported container:
  **3942 passed, 60 skipped, 4 existing deprecation warnings**, 256.43 s.
- Repository/hygiene/version tests: **273 passed**, including component-lock
  coverage; explicit lock contracts also **3 passed**. Counts overlap and must
  not be summed as distinct tests.
- Ruff, changed-file formatting, compile, document/link checks (233 Markdown
  files), comment/identity/Git hygiene, version consistency and diff checks pass.
- Security scan: **0 HIGH, 3 existing MEDIUM** Ray image-layout path findings;
  no scanner suppression or rule changes. Actual native verifier remains
  **BLOCKED** at the missing locked Windows x64 daemon binary.
- Kernel and component lock unchanged; normal OCI PID limit remains **64**.
  Ray diagnostic code/profile is unchanged; no new live Ray/physical claim.

Source/PR and resulting main CI, exact commit IDs and checkpoint evidence belong
in the integration PR and immutable tag annotation after those checks complete.
The local pass does not resolve timing issues or the SQLite qualification gap.

The follow-up Connector budget repair retains the initial commit and failure
evidence, adds effect-then-response-error tests, and revalidates the combined
HEAD. Final counts and CI attempts are recorded in the PR/checkpoint. Windows
initial CI also exceeded the unchanged Connector timeout test wall-time bound;
fixing the retry budget does not establish that separate timing failure's cause.

Final combined local validation after both Connector corrections: **42 focused
passed**, **891 affected passed / 25 skipped**, **3953 full passed / 60 skipped /
4 existing warnings** (262.35 s), and **274 repository passed**. The focused
suite includes 24 remote-admission and 9 new Connector-budget cases plus 9
existing Connector regressions. Repository-ref-dependent collection means
counts are reported from each exercised checkout, not inferred by addition.
Ruff/changed-file formatting/compile and standard documentation, security,
identity, Git and version checks pass; the same 3 MEDIUM findings and native
binary blocker remain. Required formatting changes in the legacy Connector
files were reviewed by AST: only `from_dict` and `_invoke` change semantics.

## Preserved Windows evidence and traceability synchronization

Initial remote-only source Core37918138923 attempt1 had **2 failed,3948 passed,
53 skipped,4 warnings** (833.79 s): restored firmware session still WAITING and
Connector timeout wall time0.7756698s exceeded its existing0.5s assertion. Its
attempt2 was cancelled by normal concurrency after the next semantic HEAD push.
Combined runtime HEAD8fd2b29 source Core37921150934 attempt1 had **1 failed,
3958 passed,53 skipped,4 warnings** (737.58 s): legacy decision/outcome linkage
read no outcome. The previous two failures passed in this later run; their
origins are still unproven and issues remain open.

The traceability test submitted after a fixed0.8s sleep rather than a current
WELCOME session, and skipped Node shutdown if an assertion failed. Reuse the
existing ten-second protocol-budget WELCOME helper before submission; poll the
actual outcome within the **unchanged1.5s outcome budget**. Retain all exact
Task/Decision/Node/Outcome linkage assertions, and stop the Node in `finally`.
A missing-outcome negative case must still fail and leave no live Node thread.
This repairs a test's synchronization/cleanup contract, not a proof of the
Windows timing root cause, and changes no production Runtime/Kernel deadlines.

After the traceability test repair: **33 focused connectivity passed**, **79
complete connectivity passed** (30.42 s), and **3954 full passed / 60 skipped /
4 existing warnings** (261.40 s) in the initialized supported container. The
runtime repair's42/891/274 checks above retain their scope; counts overlap.
Final source/PR/main CI must exercise the new test HEAD before acceptance.

## Ordered Relay persistence correction — 2026-10-13

Resulting main `a428dcec08a0987bca26903fb5c5fbd7e1f4ce4f` passed all four Core
jobs, but Windows Multi-Arch job `115146568093` retained **1 failed, 4103 passed,
51 skipped, 272 deselected, 4 warnings** (1376.47 s, Python 3.11.9). The unchanged
`test_recorded_result_reconciles_after_hostname_probe_failure[idempotent]`
timed out on its original five-second result wait, before its healthy-report
wait. The log records failed hostname probes and repeated receive-phase
`ConnectionClosedError`; it does not identify the blocking call. This main Gate
is not green and Issues #4/#8 stay open.

Audit classification: **REUSE** existing sequence/session files, atomic
publication, Node journal, signatures, replay guard, trust and pending Work;
**FIX** sequence and client session/probe I/O blocking the network loop;
**DEFER** unrelated Controller writes, deployed Windows/WAN/fleet and physical
qualification. Two causal pre-change writer tests fail for the Node and durable
Controller: the loop cannot execute a queued callback before the held writer
finishes. A 0.15-second delayed-write variant of the unchanged recovery contract
instead passed **2 cases** locally. These are distinct evidence sets; the Windows
failure's exact ordering is not claimed as reproduced.

The correction retains one owner guard through allocation, durable write and
wire publication, using the existing default executor. Cancellation drains the
original executor Future before releasing that guard, including a second cancel
and shutdown's Task sweep. Writer failure publishes no frame. Payload snapshots,
contextvars, key loading, signatures and restart sequence monotonicity remain
intact. Current Node trust and connection are rechecked after persistence;
pairing/error ACK exemptions remain. Client session writes share the owner guard;
session/probe calls remain serial, and overlapping live-loop use is rejected.
No Work/effect replay, authority system, Node journal, Kernel or lock change is
introduced. Controlled safety contracts have **24 passed**. The broad affected
Node/recovery/Governance/Reality/Control Plane/Agent/Workflow/SDK run has **921
passed** before the final session-publication guard and its three extra contracts;
the final targeted checks qualify that guard separately. Required
source/PR/resulting-main CI remains a separate prerequisite.

Root integration on the final guarded tree passed **844** Node, Governance,
Reality, Control Plane, Agent, Workflow and Developer Platform regressions
(110.35 s). This independently checks the final session guard; its selected
suite differs from and overlaps the preceding 921-case audit.

Final local targeted I/O/recovery/protocol/shutdown/reliability checks have
**84 passed**; SDK checks **23 passed** and repository/architecture checks
**281 passed**. Counts overlap. Ruff, changed-file formatting, compile and
standard documentation/link/comment/identity/Git/version checks pass. Security
retains **0 HIGH / 3 unchanged MEDIUM** findings. Three component-lock contracts
pass; actual native hash verification remains BLOCKED by the missing pinned
Windows binary. Full CI and native/physical qualification are not inferred.

The global Controller send guard can delay other Nodes behind socket backpressure;
stuck storage or a saturated default executor can extend cancellation drain.
These tests claim local software contracts, not performance improvement,
Windows timing closure, native binary integrity or physical qualification.

PR #58 source `e6e1b0530ef8b537b8b557302015d2d08b506f98` passed Core,
Desktop, Security and the additional Multi-Arch run `38371097444`. Windows
reported **4128 passed, 51 skipped, 272 deselected**, including both original
hostname-probe recovery cases. Resulting main `eaae0e9c35c48303cd70a98c851763b73b10d5b0`
passed Multi-Arch, Windows/macOS/Python 3.12 Core, Desktop and Security, but Core
Python 3.10 job `115220330294` retained **4 failed, 4410 passed, 58 skipped**.
Those four new repeated-cancellation contracts expected exception arguments
after the Python Task boundary. Python 3.10 locally reproduced **4 failed,
20 passed**; a minimal independent coroutine likewise retained the original
arguments inside the coroutine and discarded them on retrieving its Task outcome.

The test now observes the original Relay exception before that boundary and
asserts its exact first-cancellation arguments, while separately asserting the
Task is cancelled. Writer drain, repeated cancellation, wire order, failure,
cleanup and timeout assertions remain unchanged. No production code or timeout
changes. I/O, original reconciliation and shutdown selections pass **47 tests**
on Python 3.10 (5.75 s) and **47 tests** on Python 3.12 (5.98 s). These overlapping
local runs do not substitute for the corrected source and resulting-main CI.

The additional four-platform source run `38385375101` passed Python 3.10
**4415/58**, Linux Python 3.12 **4426/47** and macOS **4415/58** (passed/skipped),
but Windows job `115255734904` retained **1 failed, 4421 passed, 51 skipped**
(929.12 s). The existing process-session test failed at its first startup result,
before Runtime recreation. Its log does not identify whether host startup or
identity observation failed; this is not evidence that Relay reconciliation
failed, nor grounds to close the historical Windows issues.

Review of the existing ProcessSession owner found that the first live-identity
query miss immediately ended startup observation. Two controlled target/helper
query misses reproduce that result locally. Startup now reobserves only its
original, already bound host within the unchanged ten-second deadline. Invalid
binding or failed host state still stops immediately; permanently unprovable
identity remains RECOVERY_REQUIRED with stdin/control denied. Timeout reloads
the original persisted identities and retains their diagnostic instead of
overwriting them with stale pre-spawn metadata. Neither spawn nor side effects
are retried. The existing failed assertion now includes its original result for
future diagnosis. This does not identify the original Windows failure's cause.

The four new contracts pass locally. The complete ProcessSession plus Relay
I/O/reconciliation/shutdown selection retains **2 failed, 60 passed** under bare
PID 1 (`tail`): the two previously documented orphan-identity assertions see
exited zombies. In the supported initialized environment the unchanged
assertions pass: **62 passed** on Python 3.12 (25.43 s), and **62 passed** on
Python 3.10 (21.39 s). Both runs reuse the pinned Python image, `--init`, PID64,
no external network, read-only source/rootfs, dropped capabilities and no new
privileges; no Docker socket or credentials are supplied to the workload.
Those bounds describe the test harness, not a new production Provider profile.
Containers were removed after exit. Final Node/Governance/Reality/Control Plane/
Agent/Workflow/workspace regression has **858 passed** (134.73 s). Counts overlap.
Required new-source and resulting-main CI remain pending; native hashes and
physical/remote-network acceptance retain their separate blockers.

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

CAS writer review reuses the existing index, pin file and cross-process lock:
reload persisted state under that lock before graph extension, pin/unpin or GC.
Duplicate content retains its original metadata and corrupt pin records fail
closed. A further credential review reproduced two typed-metadata publication
failures: protected material could enter MIME or deployment target fields.
These fields now reject protected values before publication instead of masking
them into different semantic identities. Free-form pin descriptions retain
central redaction. Current recovery-main Artifact/Node/Reality/workspace/
credential regression has **438 passed** (106.34 s); this does not qualify native
bytes, real hardware, production scale or unmeasured performance. Source and
resulting-main CI remain separate checks.

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


## CAS reader freshness correction — 2026-10-13

Classification: **REUSE** the existing ContentAddressedArtifactStore, immutable
objects, atomic index publication and error contract; **FIX** stale metadata on
long-lived readers; **DEFER** cache optimization pending measurement. Independent
store instances previously could publish an object that get/list/resolve/verify
on an existing reader did not see. An already cached valid index also concealed
corrupt persisted metadata and could still report verification success. Five
pre-change cases fail under those controlled conditions.

Readers now load the current authoritative index under the existing in-process
guard. They observe atomic old-or-new publication without adding a file-lock
nest or another index owner. Four publication and four corruption cases preserve
the original object bytes, leave corrupt records unchanged, and require an
Artifact error rather than guessed success. This adds filesystem reads; no
latency or throughput improvement is claimed. Source/PR and resulting-main CI,
native bytes and physical effects remain separate acceptance requirements.

## Work result and coding evidence admission — 2026-10-13

Read-only product audit starts at main `566b801`. **REUSE** the original Work,
Agent invocation, ToolCatalog, ProcessSession, checkpoints and recorded-work
verifier; **FIX** result admission and current coding evidence. No executor,
verification authority, grant, Kernel or component lock is added or changed.
An original Work receiving an error-only read-tool envelope completed with a
successful observation and baseline verification. An error-only verifier also
completed Work. Empty, truthy and contradictory result mappings had the same
problem; scalar Catalog/Work responses invented a success flag. The original
completion gate skipped verification for unplanned Work without explicit criteria.
Recovery separately trusted a `found` flag rather than the original result.

Admission now requires explicit agreeing boolean success fields, refusing
errors, uncertainty and contradictory flags. Built-in Workspace, Git, Artifact,
Skill, Web and ProcessSession producers already emit boolean `ok`. Custom or
extension scalar/arbitrary mappings no longer prove success and must normalize
through their existing adapter; boolean verifier responses remain supported.
Unknown effect responses and post-dispatch exceptions retain their original
pending action and fail closed across restart, without another effect. Recovery
uses the same admission rule. Unplanned tool Work reuses the existing recorded-work
verification; a pure explanation does not acquire mandatory coding criteria.

The existing coding gate accepted tests and diff review from before a later
patch or another Plan revision. Missing/null/coerced exit codes also qualified as
successful tests. Current revision and recorded action ordering now fence these
facts; a real ProcessSession's original Work/start sequence must follow the
latest change, so polling an old test cannot manufacture freshness. Only exact
integer-zero EXITED test evidence qualifies. Positive fixture evidence now carries
its actual action ordering; original success and no-replay assertions remain.
The reattachment fixture's goal now describes its actual process-state inspection;
a separate negative proves RUNNING tests cannot complete original coding Work.

Controlled contracts exercise complete original Work progression, real Artifact
reader envelopes, boolean verifier compatibility, scalar Catalog results,
ambiguous effects/restart, recovery discovery, test/diff freshness and exact exit
codes. Registered fake sensitive material remains absent from durable state after
an effect-then-exception result. Evidence uses fake seams, not live models, real
PTY/build execution, native Windows, IdP or physical hardware. Their independent
qualification blockers remain unchanged. Final local checks and source/main CI
must be reported separately; this repair does not certify overall product PASS.

Initial controlled suite on original `566b801`: **73 failed, 14 passed**; the same
contracts on the corrected tree: **87 passed** on Python 3.12 and **87 passed**
on Python 3.10. Affected Work/Agent/Governance/Catalog/built-in tools/Chat:
**498 passed, 1 skipped** (13.74 s). Repository contracts: **282 passed**.
Counts overlap. Changed-file Ruff/format/compile and diff checks pass; current
Markdown links (**235 files**), document/comment hygiene pass. Security retains
**0 HIGH / 3 unchanged MEDIUM** findings. No full regression, live process sandbox,
Provider account, physical or native test was performed by this bounded repair.
Source/PR and resulting-main CI remain prerequisites for integration acceptance.

Root review on Usage main `508504a` exposed another concrete replay defect:
a non-idempotent fake effect increments its state, then returns explicit boolean
failure. Both original `566b801` and the initial corrected candidate invoke it
again during automatic Work reanalysis: two effects for write, execute and unknown
handlers. Real Workspace/runtime-capability and ProcessSession adapters also
collapse pre-dispatch and post-effect failures into failed response envelopes;
a boolean failure does not establish that no effect occurred.

Completed failures for these effect classes now preserve the original pending
operation and require recovery. The repaired probe records one effect and restart
invokes neither handler nor model. This deliberately blocks genuine pre-dispatch
failures conservatively; Provider-returned `no_effect` hints cannot authorize
retry. The existing original proposal pause requires the selected host Workspace
runtime and current canonical Work/Plan/manifest/authorization/approval binding,
with the original journal still PROPOSED and approval PENDING. Forged proposal
fields cannot substitute for that owner. Read failures and known Web GET behavior
retain their existing contracts. The original no-replay proposal recovery,
human approval and MATCH-only application remain exercised.

Four new initial-candidate contracts retained **4 failures**. An old generic
check fixture now declares its actual read-only semantics while preserving its
replan and completion assertions. The old failed-patch fixture's assumption of
safe automatic retry is replaced by recovery, unchanged source revision and no
second mutation or model call after restart. Independent same-Plan verification
probing found no stale success reuse: the verifier runs again after the later
mutation and its failure blocks completion. Incoming Usage diagnostic tests
continue to distinguish missing/null counters from explicitly reported zero.

Final combined affected Work/Agent/Governance/Catalog/built-in tools/Chat plus
proposal/API selection on `508504a`: **551 passed, 1 skipped** (16.91 s).
Work/Catalog selection: **180 passed**. Python 3.10 result admission and original
proposal recovery: **101 passed**. These counts overlap earlier evidence.
No new full regression or external qualification was run; source/PR and
resulting-main CI remain separate prerequisites.

Review on 2026-10-14 retained a further concrete failed-effect recovery probe:
after the original fake shell effect returned failure, a generic
`found=true/state=RUNNING` response reopened Work and produced a second effect.
The original log remains preserved. Recovery now selects the canonical bound
ProcessSession owner, validates the persisted original Work/action/invocation
and prepared command/cwd/environment digests, revalidates the host specification
and uses the existing original process identity observation. A matching Work and
action alone cannot substitute a different command or profile. Work checkpoint
changes during observation, including cancellation, stop continuation.
Generic recovery responses and missing legacy descriptors fail closed; this
intentional compatibility correction cannot reconstruct an unrecorded binding.

The controlled repaired Work exercises one original fake effect, retains the
original pending action through restart, and calls neither the forged recovery
executor nor the model. Canonical positive and negative fixtures use persisted
original session/spec/host records with an explicit identity seam; they reject
different Work/action/session/invocation/arguments/command/profile/cwd and lost
helper/target identity. Fixtures explicitly fail if recovery launches or controls
a host. These are software contracts, not a live process, PTY, build/test,
Provider-account or physical qualification; `shell_start` remains unsupported
by the public ProcessSession runtime. No Kernel or component-lock changes occur.

Final candidate on base `508504a` has **561 passed, 1 skipped** across the affected
Work/Agent/Governance/Catalog/built-in tools/Chat/workspace proposal/API selection.
Work/Catalog has **195 passed**; Python 3.10 original Work/result/proposal recovery
has **139 passed**; repository contracts have **286 passed**. Counts overlap.
All repository Ruff, changed-file formatting, compile, documentation/link,
comment/identity/git hygiene and version checks pass. Security retains **0 HIGH /
3 unchanged MEDIUM** findings; component-lock contracts pass **3 tests**, while
actual native hash verification remains BLOCKED by the missing locked Windows
`nousd` binary. Required source and resulting-main CI remain pending integration.

Directly affected original ProcessSession and startup contracts were additionally
executed in the supported initialized Linux harness: **15 passed** on Python 3.12
(19.31 s), and **15 passed** on Python 3.10 (15.29 s). These execute real disposable
host processes and preserve the existing identity, crash-recovery and orphan
cleanup assertions. The harness uses the previously pinned Python image,
`--init`, PID64, CPU2/RAM2GiB, network disabled, read-only source/rootfs, dropped
capabilities and no new privileges; both containers were removed after exit.
An initial candidate regression dropped `state` from an unprovable-spec recovery
response. Its unchanged original test failed with `KeyError`; the failure was
retained, and the corrected response preserves original diagnostic identifiers
while explicitly denying recovery/control/replay. Invalid selectors do not
change another Work's journal. This bounded Linux contract run does not qualify
public PTY, Windows installed Desktop, remote Nodes or weaker execution isolation.


## Execution input and output boundary review — 2026-10-13

**REUSE** existing Environment validation, OCI Provider, terminal conversation
owner and centralized sensitive-data redaction. **FIX** OCI image operands and
protected terminal material at the existing execution/recording boundary.
No Provider, terminal database, permission owner or host-execution fallback is
introduced. Kernel, component lock and default PID64 remain unchanged.

OCI images are rejected if they can be interpreted as command-line options,
including through direct Provider inputs or a persisted record with a matching
digest. The existing engine command also terminates option parsing before its
image operand. Two prerepair operand probes reached the runner; the repaired
probes fail before any runner call. **23 contracts** cover negative inputs,
restart validation and unchanged Docker/Podman normal-image arguments and
resource/isolation controls. These are validation/argv contracts, not actual
container isolation, engine availability or physical qualification.

Terminal results and exceptions are redacted before entering the result queue,
conversation, history, summaries or CLI output. Protected input is rejected
before writing a message or calling the executor. The existing cancellation and
failure statuses remain intact, and ordinary diagnostics remain readable.
Prerepair **3 failed, 2 passed**; terminal/conversation/Governance/credential
regressions have **312 passed, 1 skipped** on Python 3.12 (9.22 s) and Python 3.10
(9.68 s). The tests reopen the actual SQLite conversation and scan persisted
files using deterministic fake material. This does not implement or qualify an
interactive PTY and cannot retroactively remove historical leaked records.

Default strong-process/OCI execution, installed Windows Desktop, real model
accounts and physical devices retain their separately documented blockers.
In particular, an installed OCI engine does not establish that its default
control runner can pass strict admission; source contracts do not promote the
overall product beyond PARTIAL. Source and resulting-main CI remain required.

Combined Environment/Node/Governance/terminal/conversation/credential regression:
**629 passed, 3 skipped**, 23.26 s. Whole Ruff, five changed-file format checks,
compile, existing documentation/235 links/comment/identity/Git/version checks
and diff checks pass; the security scanner retains **0 HIGH / 3 MEDIUM**.
Counts overlap the focused qualification and do not imply hardware or release
integrity.

### Parallel Workflow overlap contract

Usage merge main `508504a` passed Core, Desktop and Security, but Multi-Arch
Linux amd64 job `115411003370` retained **1 failed, 4303 passed, 59 skipped,
272 deselected** (473.00 s). The existing planner/Workflow test completed its
original DAG but observed only one simultaneously active handler. Its 20 ms
sleep assumed host scheduling and durable step admission were faster than that.
A controlled, serialized 30 ms admission delay reproduces the same assertion
failure without changing the original DAG, outputs or execution handlers.

The test now synchronizes the original execution wave with a bounded barrier.
It retains COMPLETED, dependency/output and `maximum >= 2` assertions, and
requires at least two planned execution steps. Forced serial execution still
fails. Activity counters unwind if the barrier fails. Runtime, persistence,
authority, production timeouts and default resources are unchanged; this does
not identify the original CI host's timing cause or claim a performance gain.
Final Workflow/Agent contracts pass **64 tests**; the same controlled admission
delay also passes after correction. Python 3.10 focused contracts pass **3**.
New source and resulting-main CI remain separate acceptance requirements.

## Bounded Automation product consumer — 2026-10-14

**REUSE / EXTEND** existing WorkflowStore, PlanWorkflowBridge, Reality handler,
Governance, signed Node journal, EventStream, CAS and Operations Console. Legacy
enabled text remains UNQUALIFIED. A structured simulated definition now drives
manual or one-shot due execution, preserving the original run/Work through human
approval, denial, cancellation, restart, duplicate delivery and reconciliation.
The scheduler issues no authority; missing original journal/receipt/CAS evidence
is UNKNOWN and cannot reopen an uncertain effect.

Current combined backend regression has **813 passed** (251.49 s); Desktop has
**185 passed in 37 files**, with lint/typecheck/build passing. A newly installed
wheel outside the checkout completes **18 independent CLI subprocess commands**:
Approve Once yields the original COMMITTED/MATCH Work with effect count1;
duplicate trigger retains the same run/count; Deny and Cancel retain count0 and
late approval cannot revive cancellation. Wheel SHA-256 is
`b1834ba22fce5be049e3f44ff1a46d652679897d9548a8b7792689df265ecec2`;
that source qualification is not a native binary release.

Actual Runtime HTTP plus built-source App/Operations Console also exercises
create/trigger/Approve Once, Deny, Cancel and logout refusal through the same
stores. A 390px source-browser view has no document overflow. Browser screenshots
and raw histories are source UI evidence with a cryptographic fake IdP and
simulated device effects, not installed APEIR.exe, a real IdP or physical hardware.
No model calls are used for these deterministic operations. Background Cron,
semantic Recorder, executable professional Skills and production execution remain
unqualified. Source and resulting-main CI are separate required gates; overall
product status stays PARTIAL.


### Private history database admission and truthful read errors

Classification: **REUSE** the selected workspace resolver, three existing
SQLite owners, private-file security layer and API error contracts; **FIX**
file-level state admission and false empty/zero history on storage failures.
With the selected `.nous` directory real, links for `context.db`, `evaluation.db`
and `experience.db` previously exposed another disposable workspace's records.
A Context audit write followed the same link. The controlled Linux probes use
only owned fake workspaces; they do not establish a remotely authenticated
exploit or access to real private files. The connection boundaries now reject
static symbolic/reparse links, broken links, multiply linked database files,
nonregular database/sidecar files and a replaced
state directory before opening state. Independent review then reproduced a
second binding defect without a link: an unescaped read-only SQLite URI for a
literal `#` workspace name opened a sibling fake database instead of the validated
file. Percent escapes and question marks also changed path interpretation.
Read-only connections now use the encoded absolute file URI; writes keep plain
paths. Actual sibling-database probes retain the original bytes and exercise
empty/read/write/reload/API behavior with hash, percent, spaces and Unicode names.
Question-mark names are tested only on systems where they are valid filenames.
Normal explicit paths and first-use
creation remain supported; OS ancestor aliases are not new authority.

A corrupt Evaluation database previously returned successful empty API history;
after initialization, missing Experience tables also produced empty lists and
zero statistics. Existing domain exceptions now distinguish these failures from
healthy empty stores. Context corrupt-store errors already fail closed. Optional
history/learning diagnostics remain separate from authorization and effect
verification: losing a trend is not proof of an effect, and the Task Center's
recorded MATCH/COMMITTED projection is not derived from Evaluation scores.

Prerepair focused contracts: **33 failed**; three additional hardlink probes also
failed before admission was extended. Repaired workspace-binding contracts are
included in Context/Evaluation/Experience/Governance/Agent/API regressions:
**872 passed** (14.06 s); Python 3.10 Context/Evaluation/Experience/intelligence
regressions: **570 passed** (8.75 s). The URI contracts had **9 failed, 3 passed**
before correction; final workspace-binding contracts have **135 passed** (1.42 s).
Counts overlap. Static path checks do not
claim malicious same-OS-owner TOCTOU protection or native Windows ACL acceptance.
Kernel and component lock remain unchanged; source and resulting-main CI are
separate acceptance requirements.

The bounded URI audit also found six raw read-only URI entries in five existing
modules: GovernanceStore, SQLiteRuntime (connection and integrity metrics),
CapabilityRegistry, legacy NetworkRegistry and SQLiteConnector. Owned Governance
getters read foreign EXECUTE decisions, PENDING approvals and ACTIVE leases;
the selected store's write transaction still rejected foreign lease consumption.
This is a reproduced authority-record binding defect, not evidence that an
unauthorized effect executed. Those entries now use the same encoded file URI,
without changing each owner's path, permission, transaction or trust contract and
without applying the private-history path guard to different stores.

Additional contracts before correction: **18 failed, 6 passed**; final combined
URI/workspace contracts: **159 passed** (1.49 s). Extended Context/Evaluation/
Experience/Governance/Agent/Control Plane/Network/SQLite/Connector/API regression:
**1093 passed** (23.10 s); Python 3.10 affected subset: **1021 passed** (23.78 s).
Counts overlap. Four newly touched modules had existing formatter failures;
only those files were mechanically formatted and the patched AST was unchanged.
No network-filesystem or UNC qualification is claimed; unsupported nonlocal URI
authority fails closed rather than reverting to an unescaped path.

### Original-result recovery versus readiness snapshot — 2026-10-14

**REUSE** the Node journal, signed Relay result delivery and Controller-local
connectivity/resource projection. **FIX** the existing transport-loss acceptance
test's temporal assumption; no production transport, execution, lease, timeout
or retry policy is changed. The original result and resource placement readiness
remain separate facts, neither of which grants authority.

Main `8f917db05484950e6ce1e5157c3cf9f56733e459` Core, Desktop and Security CI
passed, but Multi-Arch run `38501837733`, Windows job `115650359887`, retained
**1 failed, 4339 passed, 51 skipped, 272 deselected, 4 warnings** (1132.86 s).
`test_completed_work_is_delivered_after_transport_loss_without_reexecution`
had already received the original result and asserted one execution. It then
waited for one ONLINE projection and separately read another projection whose
lease was expired. The same inherited assertion failed in Work candidate run
`38502195601`: **1 failed, 4445 passed, 51 skipped, 272 deselected, 4 warnings**
(1236.23 s); its new Work/ProcessSession tests passed. These failures remain
recorded. Logs do not identify the Windows scheduling/event-loop cause; Issues
#4/#8 remain open, and passing reruns cannot close them.

ONLINE is the connection phase, not proof of a fresh lease or resource report.
The existing test heartbeat is 50 ms and its lease window is 150 ms. A controlled
projection using the canonical projector supplies two ONLINE-but-expired samples
after the actual original result is delivered. The original test fails the same
lease assertion; the corrected test waits for, and asserts, one identical
snapshot for the exact Node with current connection, lease and fresh resources.
It retains the five-second readiness bound, original output, removed pending
assignment, disconnect and exactly-one-execution assertions. A permanently
expired projection still fails within that unchanged bound; it is not reported
as successful readiness. Normal and controlled cases are retained in the suite.

Shutdown always removes the transport and stops the owned server, even after an
assertion failure. It requires DEGRADED when the lease is still valid; if the
150 ms lease expires during bounded shutdown, it instead requires STALE/OFFLINE
and forbids scheduling. Existing direct projection tests preserve both fresh
DEGRADED and expired/disconnected contracts, with an additional explicit expired
ONLINE negative. This corrects observation timing, not lease renewal or authority.

Focused contracts: **25 passed** on Python 3.12 (4.06 s), **25 passed** on Python
3.10 (4.31 s). Node/Reality/Governance/Artifact regression: **570 passed**
(104.02 s). Repository contracts: **288 passed** (0.85 s). Counts overlap.
Whole Ruff, changed-file format, compile, existing documentation/235 local-link,
comment/identity/Git/version/diff checks pass; security retains **0 HIGH / 3
unchanged MEDIUM** and component-lock contracts **3 passed**. One initial
regression invocation named a nonexistent test directory and collected no tests;
the corrected selection above ran successfully, not a hidden product failure.
Kernel and component lock are unchanged. Source and resulting-main cross-platform
CI are required before qualification; native Windows hashes and physical/network
acceptance retain their independent blockers.

### Original ProcessSession cleanup admission — 2026-10-14

**REUSE** ProcessSessionStore, its original process/helper identity checks and
bounded control acknowledgement. **FIX** the startup test's cleanup observation
assumption; no production identity, control, retry, isolation or timeout changes.
Main `cf55c6d8e160eef330abd26f4150ef3250998615` passed Desktop, Security and
Multi-Arch CI, but Windows Core run `38588916681`, job `115938259917`, retained
**1 failed, 4790 passed, 60 skipped, 4 warnings** (1865.80 s). All startup/no-new-
spawn assertions had passed. During cleanup, a RUNNING status was followed by
`kill` performing its own identity check and rejecting RECOVERY_REQUIRED before
writing a control. The actual Windows OS-query cause is not established; neither
this correction nor passing reruns closes Issues #4/#8.

A controlled identity-query miss between the first observation and control
admission reproduces the same rejection: **2 failed, 2 passed, 2 deselected**.
The corrected cleanup observes the same original session and may re-attempt only
that explicit pre-dispatch refusal. Every attempt still requires the production
identity check. After a control is accepted it only observes terminal evidence;
acknowledgement loss and other uncertain failures propagate without another
control. It never kills a bare PID, invents identity, respawns a process or treats
UNKNOWN as terminal success. The existing five-second control bound is unchanged.

The normal/transient cases retain one launch, original identities and recovered
attachment. Actual atomic control-file writes must be exactly one, bound to that
session and action. Permanent identity uncertainty writes zero controls and
fails closed; cleanup succeeds only after the fixture restores real observation.
Two response-loss cases perform the original accepted control once, then lose the
result and prove the helper does not repeat it. The actual signed/session/lifecycle
contracts remain in their existing owners.

Final focused startup contracts: **9 passed** on Python 3.12 (18.70 s) and Python
3.10 (18.82 s); startup/catalog/Node-readiness/reconciliation selection: **61 passed**
(23.17 s). Earlier broader selection **251 passed** remains scoped to the earlier
seven-case candidate. One mistyped test-path invocation collected no tests and is
retained separately; the corrected selection above ran successfully.
Actual initialized Linux ProcessSession/startup contracts: **20 passed** (33.66 s),
using the pinned public image, non-root UID, read-only source/rootfs, network-none,
dropped capabilities, no-new-privileges, PID64, CPU2 and RAM2GiB. The owned container
was removed and checked absent. This is a test harness, not product strong-sandbox,
PTY or native Windows qualification. Existing Ruff/format/compile/documentation/
235 links/hygiene/version/security checks pass; scanner retains **0 HIGH / 3 known
MEDIUM**, lock contracts **3 passed**. Kernel and component lock are unchanged.
Required source and resulting-main CI remain separate acceptance gates.

### Automation complete evidence and original continuation — 2026-10-15

**REUSE / FIX** existing Workflow definition/checkpoint validation, original
Distributed Work and signed evidence, and the Console's current-human action path.
A completed historical run previously remained completed when its original
mutation output was missing. It now requires every original step, matching
checkpoint/output binding and committed original Work before presenting completion;
incomplete evidence is rejected without reconstructing output or executing again.
Honest unstarted, approval-waiting and cancelled records remain readable.

A separate actual response-loss probe showed an interface dead end: reconciliation
committed the original Work/MATCH, but the failed Workflow still needed its original
resume. The Console now exposes that continuation only for uncancelled, fully
committed, output-bound original Work with mutation MATCH and no uncertainty. It
keeps replacement triggers disabled and never manufactures Workflow completion.
The actual backend sequence preserves the original run/Work IDs and effect count1;
a trap forbids another mutation during either recovery phase.

Original output-integrity contracts: **8 failed, 2 passed**; final complete consumer
selection: **92 passed** (165.74 s), with the subsequently added full recovery
sequence separately **1 passed** (7.40 s). Python 3.10 relevant overlap:
**17 passed** (19.82 s). Original UI continuation contract: **1 failed, 18 passed**;
final Desktop: **192 passed in 37 files** (45.21 s), lint/typecheck/build pass.
Existing build warnings and original failure logs remain retained. These are
runtime-service simulations, not a vendor account, deployed IdP, physical device,
background Cron, Recorder, production strong sandbox or native installation.
Kernel and component lock are unchanged; exact source/main CI remain required.

### Generic Operations current-intent admission — 2026-10-15

**REUSE / FIX** the existing humanMutation exact-body nonce helper and Runtime
connection epoch for generic pairing, approval and Skill actions. Six controlled
pending-nonce cases previously dispatched after URL/token/ABA/session expiry,
while local logout was disabled. The repaired path binds current live human
intent, synchronously invalidates on logout/reconnect/configuration/expiry/unmount,
and rejects late response publication. A further same-Controller reconnect probe
retained **1 failed** because one UI path bypassed the live-human invalidation;
it now uses the same callback. No server authority is supplied by these guards.

Original controlled cases: **6 failed, 21 passed**; final full Desktop selection:
**204 passed in 37 files** (45.03 s). Post-dispatch context changes and lost responses
retain one submission, no automatic retry, and unconfirmed-outcome guidance.
Lawful bound logout/pairing/Skill behavior remains covered. Local logout failure
reports server revocation unconfirmed; it is not presented as authenticated IdP
qualification. One initial test command used the wrong directory and selected no
matching test; the corrected causal invocation above is retained separately.
Kernel, component lock, default limits and all backend authority owners remain
unchanged. Source/main CI and actual source-browser acceptance are separate gates.

Actual source-browser follow-through on clean `0bb053f830a7b8838791e57efd0ce46e7d973b77`
uses the built App against real Runtime HTTP, a cryptographic fake IdP and simulated
Reality. Approve Once, Deny, Cancel and response-loss→reconcile→original resume
reach completed/failed/cancelled/completed with effect counts **1/0/0/1**; recovery
preserves the exact original run/Work. Browser has zero page errors, no inference
requests, no 390px horizontal overflow, and logout disables further management.
The optional favicon request returns 404; the existing psutil/Tauri warnings remain.
Client monotonic wall times including UI/screenshot work are **2.45/1.89/1.78/9.11 s**,
one sample per different scenario, not a benchmark distribution or improvement claim.
These are source-browser records, not installed APEIR.exe or remote identity.

The independent installed wheel from clean `516ad9cefac587ed34ba4fd1feff9fb09ce904ff`
again completes **18 separate CLI processes** outside the checkout with no
PYTHONPATH: original approval COMMITTED/MATCH/effect1, same-trigger duplicate1,
Deny/Cancel0 and late approval rejected. Wheel SHA-256:
`4592f5e6b731d5b4a708385f71968875d3aa9805cc14c4530d79624810424c06`.
This wheel qualifies the local simulated CLI contract, not native component hashes,
signed distribution, arbitrary workloads, live model accounts or physical hardware.

### Reality restart observation delivery — 2026-10-15

**REUSE** the original Node journal, signed terminal delivery, Distributed Work
reconciler, AgentSession/Workflow and independent Reality observation. **FIX**
the acceptance assumption that fresh connection/resource readiness also proves
the subsequent read Work has delivered its result. No production execution,
authorization, retry, isolation or timeout contract changes.

Main `4a5d1858fa71c971c087f73eb19da52ea8d3c165` Windows Core run `38655187548`,
job `116163146461`, retained **1 failed, 4911 passed, 60 skipped, 4 warnings**
(1908.58 s). The slow authenticated restart test expected COMPLETED but received
WAITING; the truncated error identified a separate `observe_` Work. The complete
Windows error/journal is unavailable, so its actual OS/network cause remains
unproved and Issues #4/#8 stay open.

A controlled hold of an independently acquired read's terminal upload reproduces
the same premature completion assertion (**1 failed**, 17.25 s). The unchanged
runtime correctly leaves the original mutation VERIFIED with one effect and no
MATCH while the original Workflow waits for that read. Acceptance now permits
exactly one continuation after the paused read's original ID, Capability, target,
Node, Workflow, acquisition and input Artifact bindings are checked and its signed
terminal result is canonically reconciled. The next independent read is fresh;
the revoked mutation is never executed again. No result means WAITING, no MATCH
and no continuation. The original final COMPLETED/COMMITTED/MATCH/one-effect
assertions and all runtime deadlines remain unchanged.

Final restart/observation/original response-loss selection: **6 passed** on Python
3.12 (35.02 s) and Python 3.10 (35.52 s). Reality, Node, Workflow safety/runtime,
AgentSession coordination and Artifact CAS regression: **410 passed** (117.55 s).
An initial new-test observer saw the
intermediate OBSERVING state between saving the error and saving WAITING; its
**1 failed, 4 passed** record is retained separately. The corrected observer checks
state and error from one current AgentSession. Ruff, changed-file formatting,
compile, documentation/235 links/comments, security (**0 HIGH / 3 known MEDIUM**)
and component-lock contracts (**3 passed**) pass. These are software simulation
contracts, not physical or native Windows installation qualification. Kernel and
component lock remain unchanged; source and resulting-main CI are separate gates.

### Automation configuration publication admission — 2026-10-15

**REUSE / FIX** the existing Workflow writer, immutable Automation definition and
current human management check. Structured enable/disable now revalidates the
original definition and current session/permission after writer admission and
immediately before configuration publication. Four controlled HTTP cases on
`ac26e44` retained a configuration update after authority was withdrawn during
writer contention; no Workflow run, grant or execution authority was produced.
The correction retains trusted-local configuration compatibility and the
independent authorization checks on actual Work consumption.

Final focused contracts: **9 passed** (4.05 s), including lawful publication,
revoked session/permission, consumed nonce replay, unchanged state after restart
and missing/changed definitions. Automation/HumanSession/routes: **168 passed**
(164.12 s); Workflow/API enforcement: **52 passed** (1.77 s). Counts overlap.
Original probes and initial fixture failures remain retained. The existing
Workflow writer excludes concurrent definition replacement; separate Governance
revocation and Workflow commit are not claimed to be one atomic transaction.
No Kernel, component lock, execution permission or default resource limit changes.
Source and resulting-main CI remain required; overall product stays PARTIAL.

The same bounded publication review covers new structured configuration: the
existing add_simulation consumer now passes its existing current-human callback
to WorkflowStore.put_automation after writer admission. Original HTTP probes
have **2 failed, 1 passed**: withdrawing the session or management permission
during writer contention still published an enabled configuration. Repaired
creation/toggle contracts have **12 passed** (5.69 s), and **12 passed** on Python
3.10 (6.02 s). Combined Automation/HumanSession/routes/Workflow/API enforcement:
**223 passed** (171.87 s). Failed publication leaves no Automation, Workflow run
or grant; a previously prepared immutable definition can remain and is explicitly
not execution authority. Trusted-local use and idempotent stored bindings remain
supported. Separate Governance and Workflow commits are not claimed atomic.
No new authority, store, automatic trigger or execution fallback is introduced.

### Truthful legacy Device projection — 2026-10-15

**REUSE / FIX** the configured Operations DeviceRegistry and existing Desktop
compatibility routes. The legacy list and scan called absent Connectivity
helpers and fabricated a local online Device on fallback. Actual service-bearer
HTTP reached this result; anonymous requests were rejected. Current Operations
already read separate canonical Nodes and Devices; the exported legacy Desktop
fetch helpers have no current UI callers. This was a fact-projection defect, not
evidence of unauthorized execution or actual discovery.

The list now preserves the registered stable identity, lifecycle (including
REVOKED), Node association and simulation metadata without manufacturing a host
or Node as a Device. Missing current liveness remains UNKNOWN; persisted
AVAILABLE is not an online observation. Scan reports UNAVAILABLE, no candidates
and scan_performed=false, without network activity or trust changes. Empty JSON
bodies now receive the same unavailable result as bodyless requests; nonempty
targets are refused. Corrupt registry content produces an UNKNOWN error rather
than a fabricated local host or successful empty list. Original envelope/list
keys remain; tests requiring a synthetic local Device were corrected to canonical
facts and explicit liveness uncertainty.

Prerepair contracts: **15 failed**. Final Device/API/Operations/enforcement and
compatibility selection: **164 passed** (4.97 s); Python 3.10 focused contracts:
**15 passed** (2.70 s). Full Desktop: **165 passed in 35 files**, lint/typecheck/build
pass. An initial canonical-snapshot fixture compared JSON arrays with Python
tuples (**7 failed, 157 passed**); expected transport normalization was corrected
without changing the production identity/lifecycle assertions. A removed import
was caught by Ruff and corrected. No registry, discovery protocol, trust source,
Kernel, component lock, permissions or production liveness qualification added.
Exact source/main CI remain required; overall product remains PARTIAL.

The Device adapter also uses the same centralized redaction as Operations before
returning canonical metadata. An additional malformed fake-metadata probe failed
before this defense; final combined selection has **165 passed** (5.41 s), with
**16 passed** (2.43 s) on Python 3.10. Earlier 164/15 counts above precede that
additional negative case. Transport comparisons normalize Python tuples to JSON
arrays; identity, lifecycle and revocation assertions remain intact. A scanner
match on an inline deterministic fake bearer fixture was retained and its source
made explicit through the named fake-token constant; no scanning rule changed.
This response defense does not claim to erase historical registry content.


### Signed Node facts reach the existing Desktop — 2026-10-15

**REUSE / FIX** OperationsPlane's existing signed Relay Controller and the
existing EntityStore. The legacy node list/detail and setup query read early
Connectivity SQL/session state, while Operations used the signed Node path.
Six causal backend probes failed before the adapter correction. List/detail/query
now use the configured Controller, preserve original public-key identity and
revocation, report unavailable facts as UNKNOWN, and perform no network discovery
or trust mutation. Existing compatibility Connectivity classes remain untouched;
they are not the signed Node trust source. The retained ConnectScreen/SetupWizard wording now accurately
says registered Nodes, with optional offline continuation and Operations Add Node.
The current App bootstrap uses OnboardingWizard; no replacement wizard was added.

Four original frontend probes failed: missing entity IDs collapsed multiple Nodes
under `undefined`, raw online flags were accepted without canonical readiness,
cached event time hid current revocation, and old responses survived credential
changes. The existing API adapter now binds exact Node IDs, conservative readiness
and current configuration generation; unknown capabilities/counters/roles stay
unknown. Two further activity probes failed because generic Node events promoted
unseen or revoked Nodes to online. Activity now preserves uncertainty/revocation.
Two real-store probes also failed: React's useSyncExternalStore did not see a new
snapshot reference, and reset reused already-mutated default maps. Notification
now publishes a fresh top-level reference; initial/reset maps are independent.
Historical Node cache restores no current readiness. No second frontend store,
Node registry, event system, trust source or execution authority was introduced.

Actual authenticated HTTP list/detail/empty-body query and a real loopback signed
Node connection cover readiness, absent current resource evidence, and persisted
revocation after reopening the Controller. One new fixture initially dialed the
configured ephemeral port 0 instead of start()'s returned URL (**1 failed,
7 passed**); that is preserved and corrected without changing runtime deadlines.
The next probe exposed the adapter's insufficient ONLINE-only alias; it now also
requires current fresh resource facts and a valid connected lease. Final focused
backend **8 passed** (1.38 s); Node/Device/Control Plane/API/security compatibility
selection **224 passed** (17.56 s); Python 3.10 Node/Device **24 passed** (3.91 s).
The first two mistyped frontend/test launch commands collected no tests; corrected
commands above and the retained causal failures are separate evidence.

Final Desktop lint/typecheck/test/build: **175 passed in 36 files** (47.26 s),
including an actual React useNodes subscription, reset, activity, cached-revocation
and pending-response checks. This is source-level frontend/HTTP/loopback software
qualification. Native APEIR.exe, real remote IdP, WAN/NAT, Windows/Jetson and physical
Device acceptance remain unqualified; source/main CI and native binary hash checks
are separate gates. Frozen Kernel, component lock and product PARTIAL are unchanged.


Node-page failure delivery is exercised separately from DTO unit tests. Two
original rendered-page probes failed because an unavailable/pending Controller
looked like a successful empty directory. The existing NodesPage now shows its
actual pending read, backend failure and a manual read retry; Controller changes
hide previous rows before publishing the new response. A full empty REST snapshot
also originally retained former Nodes (**1 failed, 10 passed**); the existing
snapshot consumer now replaces membership instead of accumulating old Controllers.
No command or network discovery is triggered by these read controls. Final source
Desktop lint/typecheck/test/build has **179 passed in 37 files** (51.70 s), including
actual rendered loading/error/retry and Controller-switch flows. The earlier
175/177 counts describe preceding candidates. Native Windows UI and all legacy
cross-Controller event/cache paths remain separate qualification limits.

### Observation fault-hold producer lifecycle — 2026-10-15

**REUSE / FIX** the existing Reality restart test and its original read producer.
Main `bd89756` Core run `38683486516`, Windows job `116253006935`, retains
**1 failed, 4918 passed, 60 skipped, 4 warnings** (1483.70 s): the added delayed
observation case timed out waiting five seconds for its fault-injection point.
Multi-Arch, Desktop and Security passed. This is not the previous final-session
assertion failure; no complete Windows worker trace establishes its OS cause.
Issues #4/#8 remain open.

A controlled delay of only the first independent read's worker-result return
reproduces the same original five-second TimeoutError. The test now awaits
either its owned producer or the actual fault-hold event. Producer errors and
cancellation propagate immediately; finishing without entering the fault is a
failure. This removes a competing preparation deadline, not a Runtime timeout
or retry check: original Work/reconciliation bounds and CI's 60-second test
bound remain unchanged. All original WAITING/no-MATCH/one-effect, fresh-read and
final COMPLETED/COMMITTED/MATCH assertions remain. The same controlled single
delay passes after correction. An initial broader probe delayed every fresh
read and correctly failed the final completion assertion; that record is kept
and the correction does not admit repeated slow reads as success.

Final Reality/Node/Workflow/Agent/Artifact selection: **368 passed** (108.15 s).
Python 3.10 focused restart/producer-error/cancellation contracts: **8 passed**
(32.32 s). The initial focused run had **8 passed, 1 warning**; the new negative
fixture's empty-regex warning was corrected without changing production code.
No Kernel, component lock, production execution or authorization changes.
Exact source and resulting-main cross-platform CI remain required.


### Node control publication and response-loss recovery — 2026-10-15

**REUSE / FIX** the existing signed Node protocol, Node journal, state lock,
Artifact CAS and Relay ordered blocking-I/O lane. Controlled Artifact, lease
acquire/release and stop writes originally blocked a queued transport callback
(**4 failed**); the same hold now permits the callback without changing the
write, durability, signature, readiness or timeout contract. Cancellation drains
the original operation before releasing its owner, emits no invented success,
and preserves the original signed-control idempotency binding on reconciliation.

Four controlled pre-commit failures also reproduced memory publication before
lease acquire/release/expiry or pre-start cancellation was durably recorded.
Updates now stage the existing mapping, persist it, then publish it. A failed
lease publication never reuses a consumed fencing token. A separate boundary
selection retained **4 failed, 1 passed**: after a commit whose response was lost,
the same process could issue a replacement lease or execute an already cancelled
Work; malformed journal records were silently discarded. Current requests now
reconcile the original persisted journal first. Unknown EXECUTING evidence cannot
restart an effect; malformed records or lost previously observed Work IDs fail
closed. This remains single-owner Node storage, not multi-process writer or
complete journal-erasure protection.

The first expanded Node run retained **1 failed, 236 passed**: an uncertainty
fixture seeded only a private memory mapping without its purported persisted
record. It now writes that original journal before reconciliation and retains
all RECOVERY_REQUIRED/UNKNOWN and no-replay assertions. Production at-most-once
admission already stages its EXECUTING record before publishing it; new boundary
checks preserve that contract rather than claiming a new admission mechanism.

Six actual CLI processes in fresh owned directories exercised MATCH, Deny,
MISMATCH, UNKNOWN, lost response and restart. The actual results were respectively
COMMITTED/MATCH/1 effect, CREATED/no verdict/0, VERIFIED/MISMATCH/1,
VERIFIED/UNKNOWN/1, COMMITTED/MATCH/1 and COMMITTED/MATCH/1. Lost response first
had no Controller receipt and already one effect. These are simulated devices,
local CLI human attestation and runtime-service scope, not real model, remote IdP,
Kernel, native Windows or physical hardware qualification. Single-run durations
(1.269–2.826 s) are observations, not a comparative performance benchmark.

The earlier source `92f2c0c` passed all four Core platforms, including Windows
**4923 passed, 60 skipped**. Its Multi-Arch run `38766532736` was cancelled by the
operator while Windows was still progressing at 99%; it is **CANCELLED**, not a
pass or proof of a hang. Its earlier Artifact/control test failure and a failure
marker during cancellation are preserved without an unavailable final stack.
An isolated Windows/Linux two-test diagnostic passed but did not reproduce the
failure. A separate full-prefix Windows Python 3.11 diagnostic `38775081314`
passed **4616 tests, 60 skipped, 272 deselected** (2181.62 s), including both marked
cases. That diagnostic adds stricter failure/trace bounds and is explicitly not
a replacement for production Multi-Arch acceptance. No observed failure is
closed merely because a subsequent run passed; Issues #4/#8 remain open.

Final local Node/Reality/Governance/Artifact/Work/AgentSession/Workflow/Gateway
and usage regression: **980 passed** (144.77 s). Python 3.10 Node service and
Relay I/O contracts: **69 passed** (5.41 s). No default PID, isolation, identity,
authorization, frozen Kernel or component-lock change. Standard repository checks
and exact new-source/resulting-main CI remain distinct evidence from the earlier
source and diagnostics above; none upgrades physical or native release status.


The shared-store correction also exposed an existing Chat auto-scroll dependency
on a newly allocated message array: an unrelated Node snapshot caused one extra
scroll without new content (**1 failed** controlled subscriber probe). Chat now
tracks the latest message identity/content/card count and loading state instead;
real new/updated messages still scroll, while a Node refresh makes zero additional
scroll calls and zero model/network requests in that fixture. An initial fixture
removed its scroll stub before unmounting (**1 failed / 1 cleanup error**); that
record is retained separately and the corrected cleanup reproduces the same
single assertion failure. Final source Desktop lint/typecheck/test/build:
**180 passed in 38 files** (44.80 s). These are observed UI callback/correctness
contracts, not measured task latency, Token savings or native UI qualification.


### Automation integration with canonical Node facts — 2026-10-15

The existing consumer candidate was normally merged with accepted main `c43f942`;
only independent API-contract and acceptance text required conflict resolution,
and both records were retained. Current source `13190ae` has **173 passed**
Automation/Workflow/Node-and-Device projection contracts (173.11 s), and Desktop
lint/typecheck/test/build has **219 passed in 40 files**. An initial local command
named a nonexistent `tests/workflow` directory and collected no tests; the
corrected command uses the existing Workflow test files. It is not counted as a
product failure or a successful regression. All 12 repository-standard checks
pass, with **0 HIGH / 3 known MEDIUM**, and **3 component-lock contracts**.

A fresh built source-browser run against actual Runtime HTTP on that source
again exercised approval, denial, cancellation and response loss: final effect
counts **1 / 0 / 0 / 1**, with the exact original run and Work preserved during
reconciliation and resume. Logout blocks creation; the 390-pixel viewport has no
horizontal overflow and no page errors or model calls occur. Source-browser
screenshots and original persisted histories are retained privately. The local
single-case client monotonic times were 2.118 / 2.412 / 1.660 / 9.549 seconds;
these differing scenarios are not a performance comparison. The identity
provider is a deterministic signed test fixture and the device is simulated.

Separately, main `1570e3b` passed all Core, Multi-Arch, Desktop and Security
workflows: Core Windows **4946 passed / 60 skipped**, Linux 3.12 **4959 / 47**,
Linux 3.10 and macOS each **4948 / 58**; Multi-Arch Windows **4636 / 60 / 272
deselected**, Linux amd64 and ARM64 each **4637 / 59 / 272 deselected**. This is
that exact merged Node durability baseline, not qualification of this unmerged
Automation candidate or resolution of Issues #4/#8. Source/main CI remains
required for this candidate. No Kernel or component-lock changes.

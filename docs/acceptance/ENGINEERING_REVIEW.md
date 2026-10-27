# Engineering review and research comparison

Review date: 2026-10-09. Read-only baseline: Distribution
`5c9cdd987af3823d4be9e6909311af65b9be2299`; frozen Kernel
`87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
[ROADMAP](../../ROADMAP.md) remains the sole current milestone-status source.
This record distinguishes reproduced defects, inspected risks and unqualified
external dependencies. It is not an exhaustive proof that the repository is
bug-free, a physical acceptance, or production certification.

## R5 completion code audit and public entry review — 2026-10-25

Audit base:Distribution62cbe6ff53a769172067740370f26fb18eb3c094;
frozen Kernel87fd1b2ff28ef14ab1a515a58162592b452fda2e. Both remote heads
were checked, all five latest-main workflows passed, no PR was open and only
main existed before starting this work. This audit does not promote a feature
from an enum, interface or screenshot to an execution qualification.

| Capability / owner | Classification | Actual entry / consumer / evidence |
| --- | --- | --- |
| Docking/layout: `desktop/src/components/studio/StudioShell.tsx`, `lib/studioLayout.ts`, `lib/studioLibrary.ts` | REUSE | Existing Studio panel table, version1 presentation and protected drafts; `desktop/e2e/studio-runtime.spec.ts` exercises real API/browser layout and Controller isolation |
| Dashboard: `StudioDashboard.tsx`, `StudioData.tsx` | REUSE | Shared Operations/health/Usage/EventClient reads; no widget execution authority; same E2E and bounded-layout tests |
| Workflow models/compiler/runtime/store/CLI: `nous_runtime/workflow/` | EXTEND | Public `apeir workflow`; durable definitions, checkpoints and original runs; `tests/test_workflow_runtime.py`, `tests/test_workflow_safety.py`; graphical editing and definition management HTTP consumers missing |
| Generic Workflow handlers | EXTEND | Transform, immediate wait/barrier, input condition and approval builtins exist. Agent/capability/connector/command require trusted host handlers; enum membership is not generic execution availability |
| Automation: `automation/consumer.py` and existing WorkflowStore | REUSE | Durable bounded simulated-reality consumer, existing Console/API; recurring/general triggers retain their documented limits |
| AgentSession/Work/TaskPlan | REUSE | Existing supervisor, PlanWorkflowBridge and original Work/Run identities; existing Work/Automation integration tests; no new Agent authority |
| Governance/ApprovalBroker/human sessions | REUSE | Existing API admission, exact operation bindings, human mutation nonces and revocation; `tests/governance`, `tests/control_plane` |
| Extension/Skill/CAS: `extensions/registry.py`, `skills/`, `artifacts/` | EXTEND | Verified packages, source/digest/provenance, lifecycle and original CAS already exist. Studio declarative contributions and host data bridge are missing; no second package registry is needed |
| Provider SDK/model configuration | REUSE | `sdk/provider/python`, existing Gateway/NKI and Model Center; examples use public contracts; real account qualification remains independent |
| Workspace/Proposal/Diff | REUSE | Existing developer API, current file SHA and human-reviewed write consumer; `tests/test_workspace_proposals.py` and Desktop tests |
| ProcessSession/Environment | REUSE / BLOCKED | Existing bounded execution and cancellation; untrusted execution requires the original strong sandbox. UI existence is not PTY or OCI qualification |
| Events/evidence/effect verification | REUSE | Configured-owner RuntimeEventBus, per-Run EventStream, CAS and current verifiers; original journals remain authoritative for their respective scopes |
| Nodes/Devices/Environment | REUSE | Existing Controller/Node signed reports, Reality registry and EnvironmentRuntime; software tests do not replace Jetson/ESP32 physical qualification |
| Native Desktop/Kernel/install | BLOCKED | Current Tauri/sidecar/official packaging pipeline exists. Original locked Windows bytes remain unavailable; deterministic R4 candidates await explicit lock approval. Windows10 lifecycle is PENDING |

The tracked Markdown inventory covers235 Distribution and66 frozen-Kernel files,
with hashes, titles, local-link checks and legacy-brand occurrences retained in
private audit evidence. Both inventories have0 broken local links and0 identical
content groups. Legacy Nous identifiers are compatibility/history, not a blanket
rename target. Kernel Markdown is read-only in this change; its historical CI
badge uses the prior owner URL and its scoped native claims do not qualify the
current Distribution installer. External redirects and live service availability
are not established by the local-link checker.

REUSE the existing README pair, canonical Quick Start and Studio guide. The
public entry now separates source downloads, developer checkout and blocked
native installation. Its screenshot is an unedited actual source-browser capture
of the accepted Studio implementation, with no Provider or hardware success
invented. The latest qualified source manifests remain pinned to62cbe6f; a docs
commit is not substituted for that software qualification. Archive and per-file
checksums, clean wheel install, actual HTTP/GUI file read, layout restore and
model-free shutdown were independently exercised. Documentation regression:
320 PASS,5 Windows-only cases not executed on this Linux host. CLI/source steps
reuse the exact qualified artifacts; Windows activation syntax is an existing
instruction, not a claim of current native installation acceptance.

## Studio composition review — 2026-10-24

Starting main `9048af81` includes normally merged R4 PR #90; its component lock
and frozen Kernel remain unchanged. REUSE the existing Desktop Runtime views,
API/EntityStore/EventClient, theme and editor. EXTEND presentation with a pinned
FlexLayout dock and bounded version1 layout; the new frontend panel contribution
table owns rendering only. The Desktop architecture records the view/owner map.
No Workflow executor, Runtime store, credential backend or installer is added.

Two original deterministic failures establish that the existing EntityStore
retained prior nodes after credential replacement and hydrated unscoped cached
records. The repair clears the same Store on connection replacement, scopes its
existing cache record to endpoint/session without saving bearer material, and
rejects obsolete hydration/batch results. Same-scope historical Node tests retain
their original UNKNOWN/revoked assertions. This fix is required for Studio's
cross-Controller acceptance, not a new task database or authority.

Actual sandboxed Linux Chromium with two owned, model-disabled Runtime CLI/HTTP
processes exercises layout save/reload, draft-preserving drag, no repeated file
read on reparenting, blocked destructive layout replacement, Controller switch,
hidden old private content and explicit draft export. Malicious layout fields
are rejected; unknown components load no code. Source mobile390px and dark mode
are exercised. The public Playwright test is now part of existing Desktop CI;
screenshots are labelled source browser, never installed APEIR.exe evidence.

Source `62025bccac70973ad77af1d459c75810114d952d`, Linux x64/Node24.19.0,
Vite7.3.7 and sandboxed Chromium156.0.8078.4 recorded8 exploratory warm
Studio-open samples: p50=137.96ms,p95=150.01ms (median / nearest-rank). It measures click to two browser animation frames after
the Studio region appears, in the same local Chromium/source environment. It
does not measure Windows cold start, sustained FPS, memory release, paired
improvement or model latency. Those performance qualifications remain pending.

Dependency audit independently reproduced7 pre-existing development findings
on main (5 HIGH,2 MODERATE); production dependencies had0. Compatible Vite7.3.7,
Vitest4.1.12 and affected transitive dependency updates remove those findings;
the full audited lock now has0 findings. No scan or assertion is weakened.
FlexLayout0.11.1 is MIT and Playwright1.64.1 is Apache-2.0; both are version-pinned.
The required frontend job now audits all npm dependencies, including dev tools.

The schema has document-kind discriminators but currently saves one global
presentation preference. Workspace-specific libraries, visual Workflow conversion, isolated external UI contributions and real media adapters
remain PENDING. Existing text/Runtime views in a preset do not qualify these.

### Dashboard integration follow-up

EXTEND the existing Studio schema and panel table with a bounded read-only
Dashboard; REUSE Operations, detailed health, CostController/EntityStore and the
same EventClient transport. No new Runtime authority, DB or executable widget
loader is added. A missing Controller resource projection is extended with
bounded CPU-capacity/RAM fields from its current signed report; stale/offline/
revoked reports are unavailable. No CPU/GPU utilization is invented.

Actual source Chromium/HTTP acceptance checks add/settings/drag, exact persisted
coordinates after reload, import/export, rejected bounds, explicit unsupported
GPU metrics and pause. Original failed geometry tests are retained privately:
allowing collisions made the visible drag differ from its rejected persisted
state. The library’s no-overlap strategy fixes the mismatch; acceptance checks
persisted coordinates as well as DOM position. Shared subscriptions are tested
with multiple visible/hidden readers and stale Controller responses. These are
software/source-browser observations, not Windows or hardware qualification.
Local follow-up qualification:383 Desktop tests and3 actual CLI/HTTP/Chromium
cases passed;306 Node/Operations tests passed. Repository contracts passed299
with5 Windows-only cases skipped on Linux. Type/lint/build, full npm audit
(0 findings) and documentation checks passed. Exact candidate CI remains a
separate gate; these local results do not certify a future merge commit.

### Named layout library follow-up

REUSE the existing Studio schema, current Runtime health read, protected-layout
replacement guard and UI-reset owner. EXTEND presentation only with bounded
named snapshots and four document kinds; no Runtime DB, task, credential store
or permission authority is added. Workspace namespacing uses an opaque digest
of the authenticated endpoint/directory and rechecks that source on load/edit.
A new Controller never displays the other namespace’s saved workspace entries.
Global/templates are intentionally portable, without any Runtime content.

Actual sandboxed Chromium with two owned CLI/HTTP Runtimes exercises workspace
save, template copy/rename/export/load, full page reload and Controller A→B
namespace separation. A second real browser window saves concurrently; the stale
first editor must reload and both valid entries remain. These presentation
actions issue zero Runtime mutations. Software validation rejects invalid fields,
namespace mismatch, duplicate IDs, oversize collections, stale revisions and
unavailable writer locks, preserving prior stored bytes on quota failure.
Native Windows/media/Provider/hardware qualification remains separate.

### Studio visual and interaction refinement — 2026-10-24

REUSE the same FlexLayout model, GridLayout, ThemeProvider/design palette,
version1 layout/library documents, protected drafts and Runtime read consumers.
EXTEND presentation with a compact toolbar/menu, ephemeral normal/edit mode,
shared status treatments, monochrome icons, bilingual labels and keyboard focus.
No execution, permission, Runtime database or layout schema is introduced.
The Usage panel now reads the existing shared accounting consumer directly,
instead of opening the Model Lab configuration view a second time.

Existing explicit and implicit legacy Dashboard geometry remains compatible;
only newly created Dashboards get smaller default cards. Responsive stacking is
a view transform and never overwrites saved positions. Resource meters admit
only fresh/current/trusted reports with valid memory bounds. Topology connects
only exact reported Node/Device bindings. Missing metrics/bindings remain
UNKNOWN; CPU utilization, GPU and throughput are not invented.

Real model-disabled CLI/HTTP and sandboxed Chromium checks retain the original
layout/drag/draft/Controller/library assertions, add old six-row Dashboard import,
normal-mode movement refusal, keyboard edit/settings, live service and unknown
usage states, both themes and Chinese small-screen reload. Frontend contract
fixtures exercise nonempty memory/topology rendering and stale/revoked/invalid
report refusal; they are not physical telemetry or hardware acceptance.
Local validation:405 Desktop tests and7 composed sandboxed Chromium/real HTTP
cases pass, including browser2x DPI/touch hit targets and measured service-status
text contrast of at least4.5:1 in both existing themes. Type/lint/build and
repository contracts (299 PASS,5 Windows-only skips on Linux) pass. The retained
security scan remains0 HIGH/5 pre-existing MEDIUM. These results belong to the
composed source candidate; exact-head CI and resulting-main qualification remain
separate gates.

The original visual test exposed an implicit-default compatibility regression;
it is retained privately and fixed by preserving legacy defaults. Source browser
screenshots are not installed APEIR.exe screenshots. Windows10 native visual,
DPI, lifecycle and real Provider qualification remain PENDING/BLOCKED under the
existing native gates. No FPS, latency, Token or cost saving is asserted.

### Shared Usage transport measurement — 2026-10-24

The public `desktop/scripts/benchmark-studio-usage.mjs` builds isolated fixtures
from two clean checkouts, rendering two unchanged existing collapsed StatusBar
components with the same Vite/React compiler and an owned model-disabled Runtime.
This measures the shared Usage hook, not whole Desktop or Model Lab performance.
Baseline/UI and fixed backend: `8502b4c87b5118d11c6c7b64acbda7706a60f423`;
candidate/UI: `c5501c00f690d8f5b643103c012cdd613c6d69a9`. Linux x64,
Node24.19.0, Vite7.3.7, sandboxed Chromium156.0.8078.4; alternating AB/BA/AB,
3 paired11-second windows per build. No model, native or physical task runs.

| Measured quantity | Baseline | Candidate |
| --- | --- | --- |
| Usage HTTP GETs, each window including initial reads | 6,6,6 | 3,3,3 |
| First exploratory renderer TaskDuration p50 / p95 / p99, ms | 16.928 /17.765 /17.765 | 21.693 /30.921 /30.921 |
| Browser-process CPU, second instrumented series, seconds | 0.06,0.05,0.05 | 0.06,0.07,0.09 |
| Browser-process CPU p50 / p95 / p99, seconds | 0.05 /0.06 /0.06 | 0.07 /0.09 /0.09 |
| Renderer TaskDuration p50 / p95 / p99 in that second series, ms | 28.591 /29.645 /29.645 | 27.679 /28.403 /28.403 |
| Largest observed renderer heap-after in second series, bytes | 2879964 | 2796396 |
| API failures / Runtime mutations in qualified fixtures | 0 /0 | 0 /0 |

Only the reduction in duplicate Usage reads is established. **Overall performance
qualification remains PARTIAL**: observed browser CPU increased, and no stable
causal attribution follows from n=3 or10ms-granularity CPU counters. The p95/p99
figures are sample maxima, not robust tail estimates. TaskDuration is not CPU;
CDP SystemInfo CPU covers this owned browser group, not Runtime or whole-host CPU.
Heap-after is not peak memory. There is no overall speed, Token, Provider-cost,
network-byte, native/Windows or cross-machine performance improvement claim.

An initial full Model Lab scenario was excluded: it correctly received403 for
an absent human session, and it uses its own Model Lab snapshot instead of the
hook being measured. Its failure evidence was retained; no failed sample was
relaxed into a successful hook measurement. A fixture-layout click failure was
also retained. The qualified fixture keeps bars collapsed, matching the recorded
scenario. No test deadline or authorization assertion was weakened.

## Governance schema admission — 2026-10-23

R2 rechecked main `e3cd2a20`, composed candidate `c8ec9f3` and frozen Kernel.
Core39960170078 Windows job120436212486 timed out during `human_env` construction,
inside the original GovernanceStore schema `executescript`; its full log remains
on GitHub and the failure is not replaced by the passing Multi-Arch39960173640.
**REUSE** PR #89 connection ownership and phase diagnostics; **FIX** schema
transaction/failure semantics; **EXTEND** its existing Windows diagnostic;
**BLOCKED** remains protected-main integration and native locked components.

Three deterministic original failures independently establish that schema DDL
ran outside a transaction, a late injected syntax error left published partial
tables, and initialization swallowed the error while logging private exception
text. The existing connection now owns one `BEGIN IMMEDIATE` schema transaction:
all DDL commits together, late failure rolls it back and propagates, and warnings
contain no exception text. WAL, FULL synchronous behavior, busy timeout, grants,
identity, approvals and normal transaction ownership are unchanged. There is no
connection pool, successful-schema cache or second GovernanceStore.

Focused lifecycle/human-session/context checks pass **102 tests**; related
Governance/ControlPlane/Context/repository checks pass **1231 tests** (63.28 s).
The original three failures and prior Windows initialization/commit stalls remain
separate evidence: the atomicity repair alone does not prove every Windows stall
has the same cause. The existing diagnostic can run `windows-governance` to
exercise the original cases before the broader Governance/ControlPlane suite,
with the original60-second bound. It cannot produce the required `Core gate`
context; full combined-source Windows Core must qualify independently. No timing
Issue is closed on a single passing rerun.

The composed `18f032e` Windows Python3.12 diagnostic
[39986761379](https://github.com/untrod/apeir/actions/runs/39986761379), matching
the original failing Core interpreter, passes the original focused **102 tests
(34.38s)** and broader Governance/ControlPlane **474 passed,18 skipped
(118.44s)**. The earlier Python3.11 subset is retained separately. Neither
diagnostic substitutes for full Windows Core or closes the timing Issues.
After normal synchronization with accepted MCP main `ad773890`, the focused
Linux schema/human/context combination still passes **102 tests**.

Full composed `18f032e` Core subsequently retained a new test-probe failure on
Linux/Python3.10: **1 failed,5739 passed,77 skipped (888.71s)**; Linux/Python3.12
passed **5751 tests,66 skipped (898.35s)**. The new probe counted overridden
`commit()` method calls and assumed one call. Actual Python3.10 reproduction
shows `executescript()` first calls `commit()` without an active transaction,
then the owner commits the real transaction: `[false,true]`, but exactly one
SQLite BEGIN/COMMIT. The probe now traces actual SQLite boundaries and requires
exactly `BEGIN IMMEDIATE`→`COMMIT`, with every DDL inside that transaction.
Late-error rollback, existing-data retention, privacy, WAL/FULL and integrity
assertions remain. No production code or timeout is changed for this correction.
The original failing3.10 probe/log is retained; corrected focused checks pass
**102 tests on Python3.10 (2.32s)** and **17 lifecycle tests on Python3.12**.
Fresh exact-source full platform CI remains required.

Paired Linux constructor measurement used the same interpreter/filesystem,
alternating order,5 warmups and20 measured fresh databases per variant. Before
PR #89 baseline `d9c0505`: p50/p95/p99 **13.52/16.80/18.57 ms**, mean CPU3.89 ms;
atomic schema candidate: **5.26/6.04/6.28 ms**, mean CPU1.89 ms. Both retain
identical schema, WAL/FULL and integrity checks, with0 failures. These small
sample tail estimates are exploratory, not Windows, model, UI or end-to-end
performance qualification.


## Source Preview delivery closure — 2026-10-24

R3 rechecked main `ad773890`, the five open reviews and frozen Kernel.
**REUSE** the existing Provider/Workspace/Proposal, CLI and source-wheel owners;
**EXTEND** only the existing Source Preview qualification and artifact contents.
**BLOCKED** remain protected-main integration, real account qualification, strict
test execution and native installation. Protection reads still return403; an
empty effective ruleset list does not establish classic/admin enforcement. No
additional main merge is attempted before maintainer verification.

The old artifact omitted usage instructions and exercised API import/bind/close
instead of the public startup path. The existing Desktop workflow now includes
the canonical Quick Start with links pinned to the exact source revision, and
hashes the guide, wheel, manifest and validation report. It invokes a bounded
stdlib verifier using the fresh base consumer's isolated interpreter. This
verifier reads only its temporary fixture/session: normal model-enabled startup
without Kernel refuses; explicit model-free startup serves the chosen workspace;
unauthenticated access denies; unused model tokens/cost stay UNKNOWN; saved
Providers stay unchanged; interrupt exits0, revokes the session and closes the
listener. Logs and generated session material remain private and are not uploaded.
The verifier rejects source-checkout imports rather than qualifying them as an
independent install. This adds no Runtime, permission or packaging authority.

A newly built wheel installed with base dependencies only in a fresh Python3.10
environment passes that public startup qualification outside the checkout.
Related CLI/startup/repository checks pass **289 tests (2.92s)** before the new
checkout-import refusal test; the focused final selection passes **13 tests
(2.23s)**. Counts overlap. Current-source artifact/CI qualification is separate;
this Linux source evidence cannot establish native Windows or real inference.

## Model-free public startup and product recovery — 2026-10-23

**REUSE** the existing `--no-intelligence` process mode, Runtime API, WorkHarness,
Proposal service, human sessions and CAS; **FIX** public API startup in that
explicit mode; **BLOCKED/PENDING** real inference, qualified test execution and
native installation. No execution, approval or model authority is added.

The actual `apeir --no-intelligence runtime-api start` command originally exited
in production with `NOUS_KERNEL_ENDPOINT is required`, preventing independent
Runtime-service inspection even after all models were explicitly disabled.
Startup now activates the existing model-off guard before initialization and
retains the ordinary Kernel preflight in model-enabled mode. Saved Providers
remain untouched and unloaded, protected reads still require authentication,
and unsuccessful model tests report unknown usage rather than zero.
The subprocess/HTTP regression fails before the change and passes afterward.
Startup, CLI, model-off, credential and Gateway checks pass **65 tests** (2.86 s).
That combination also exposed an older CLI fixture leaving its workspace in the
process environment: the original order retained **3 failed /20 passed**.
Those CLI tests now use the existing temporary-workspace fixture and isolated
capability storage; their assertions and production startup behavior are intact.

A fresh wheel installed with only declared base dependencies in an independent
Python3.12 environment was exercised outside the checkout with `python -I`.
The public model-free API starts with a generated owner-only session, serves the
actual selected workspace, rejects unauthenticated Provider reads and refuses
model execution with unknown usage. Normal production startup without Kernel
still refuses. Interrupt exits0, revokes the session and closes the listener.
This qualifies source API operation, not an installed native executable.

The composed software review used sandboxed Chromium, the actual source UI and
authenticated Runtime HTTP with a deterministic fake deliberator/signed fake
human identity. Original Work `work_e7e7fabef2c4454893450d006c3f3503` generated
two-file Proposal `wfr_19f468faa14e46bcab121bac25321279` through WorkHarness.
Browser review/Approve Once/apply yielded independently reread file MATCH.
An initial missing service-read permission returned403 and left files unchanged;
the fixture operator granted only the exact workspace read scope and resumed
the same original approved proposal. No service approval authority was added.

The existing pytest profile then admitted the separately approved original run
`workbench-exec-f0eb3668891d4d51`, but returned exit-1 with
`STRICT_SANDBOX_UNAVAILABLE`: tests did **not** execute. A new Runtime process
restored the original proposal, authorization and CAS manifest; reconciliation
reported `replayed=false`. Both file hashes and write timestamps stayed unchanged.
Work remained `WAITING_USER`, requiring a qualified test backend. Browser review
and restart had zero page errors; private screenshots/HTTP evidence are source
browser captures, not APEIR.exe. Proposal generation occurred in the fixture's
real WorkHarness before browser review; it was not a live model call initiated
inside Chat. These limits keep the complete developer/product Gate PARTIAL.

That qualification also identified a public source entry gap: Operations Console
accepted an address but had no service-session input. Scripts that preselected
the session had masked this missing user interaction. The original three UI
cases fail before the correction (**3 failed,37 passed**). The existing form now
accepts an explicitly entered service session over its existing HTTPS/loopback
admission. It clears the draft on address edits, connection changes and submit,
never forwards the old session to a new Controller, and stores no credential in
layout/localStorage. The existing session-only API connection owner and separate
human approval authority are unchanged. Existing unsafe-address tests also check
that entered sessions are neither sent nor included in refusal messages.

Using the independently installed public CLI's production/model-free API,
sandboxed Chromium opened the actual source UI with no injected session or
native IPC: a wrong session returned401, explicit form entry recovered actual
Operations data, and reload retained the selected endpoint/session. All model
Providers remained disabled, Kernel readiness was false, and the UI kept observe
mode rather than inventing a human identity. There were zero model calls and
zero browser page errors. Full Desktop checks pass **326 tests/46 files
(57.33s)**; lint, typecheck and source build pass. These are source software
results, not Windows native installation or live-provider qualification.

Minimum-version validation found another real packaging gap: an independent
Python3.10 base/dev install failed API imports with missing `async_timeout`
(**7 failed,58 passed**). The API imports the existing extension facade even
without the optional MCP SDK. Its already-used Python3.10 timeout backport is
now a conditional base dependency instead of being declared only in the MCP
extra; no replacement timeout, direct SDK path or unguarded execution is added.
The same affected selection passes **65 tests (3.11s)** afterward. A second fresh
Python3.10 environment installed only the actual wheel/base dependencies and
passed the public strict/model-free API, authentication, unknown-usage and
interrupt/session-cleanup checks. Its installed lost-response simulated Demo
also retains effect count1 and reaches COMMITTED/MATCH without Kernel traversal.

The existing manual Source Preview workflow still builds on Python3.12, then
installs only the wheel/base dependencies with Python3.10, the minimum supported
version. It now checks isolated API import/bind/close before the existing Demo,
records consumer and builder versions, and preserves the same artifact name,
seven-day retention and explicit non-native qualification. This adds no PR/main
matrix or release bypass. Workflow actionlint1.7.12 and repository contracts
pass; exact-source remote qualification remains separate.

After normal composition of the existing PR83/PR86/PR89 histories, affected
Governance, ControlPlane, Context, Work, public startup, credential, workspace
proposal, checkpoint and repository checks pass **1549 tests,16 skipped
(90.69s)**. Counts overlap the earlier narrower checks; skips are not PASS.
Resulting MCP main `ad773890` separately passes Core39986188751,
Desktop39986188830, Multi-Arch39986188775 and Security39986189013. Its Windows
Core has **5369 passed,149 skipped (2351.96s)**; Windows Multi-Arch has
**5073 passed,131 skipped,292 deselected (2111.40s)**. Those main results do
not qualify the still-unmerged R2 combination or establish that repository
administrator protection was enforced. No further main merge is attempted.


## Saved Provider lifecycle integration — 2026-10-23

Starting parent PR #83 was `e8a0913`, while main remained `e3cd2a20`.
**REUSE** Provider setup/configuration, Registry, Gateway, existing file locks and
Governance routes; **FIX/EXTEND** saved update/removal and setup model selection;
**BLOCKED/PENDING** remains protected integration, native release and live-model
qualification. There is no second Registry, credential store or execution path.

Original regressions retained **4 failed / 3 passed**: deletion left saved
configuration behind, update failed after removing the original adapter, the
current Gateway retained stale discovery, and corrupt JSON was replaced by an
empty mapping. Original setup selection retained **1 failed / 7 skipped**:
Gateway identities and unrelated Providers were offered as vendor model IDs.

Create/update/remove now share the existing JSON owner with advisory file and
in-process locking, unique temporary files and atomic replacement. Invalid edits
and failed writes preserve the original adapter; corrupt records deny mutation.
Successful edits preserve unedited settings and refresh the original Registry
and current strict Gateway. A refresh failure after persistence clears the
Gateway and reports failure, without claiming rollback or retrying inference.
Deletion survives reload, leaves credentials in their separate store and does
not cancel already admitted requests. Other running processes are not broadcast
synchronized; this is not a distributed transaction or an authority revocation.
Unsupported `enabled` edits are rejected rather than falsely reported applied.

The existing catalog exposes a recorded vendor `provider_model`, or null when
unknown. The wizard reuses its bounded reader, exact selected Provider and
connection/lifetime fences. It never substitutes a Gateway ID/display label or
strips namespace prefixes from vendor IDs. Suggestions remain unqualified until
an explicit actual inference through the existing Gateway/NKI.

Initial focused lifecycle checks: **12 passed** (2.35 s), including new-interpreter reload,
four-process writers, failed writes/refresh and authenticated Runtime HTTP.
Unauthenticated PATCH returns401; an admitted PATCH changes persisted config and
the actual model catalog; DELETE still returns403/NOUS_APPROVAL_REQUIRED without
changing state. Full Desktop: **323 passed**, 46 files (75.50 s); lint, typecheck
and web build pass with the retained mixed Tauri import warning. These use fake
references/IPC and no real model or installed Windows executable.

The first related regression retained **1391 passed,5 skipped,1 error** (78.30 s).
The error is the unchanged local TLS fixture reading an empty `port` file while
its child was still publishing via `write_text`. Its producer now closes a
`port.pending` file before atomic replacement. The original five-second bound,
TLS/security checks and parent assertions remain unchanged; no Runtime timeout
or retry policy changes. The affected TLS/Skill HTTP suites then pass **37 tests**
(25.48 s). The original error remains distinct from the Windows timing Issues;
passing these tests does not close those Issues or qualify remote publishers.
Final related Provider/Model/Governance/ControlPlane/Context/no-intelligence
regression: **1393 passed,5 skipped** (65.71 s); repository contracts: **278 passed**.
Counts overlap the narrower checks and are not a product maturity percentage.

The same first-use review reproduced **3 failures** for the desktop `anthropic`
identity: it selected the custom/OpenAI adapter rather than the existing
Anthropic implementation. The saved identity now maps to the existing `claude`
preset, and root, `/v1` and full messages addresses retain one correct endpoint.
Existing saved configurations are not automatically migrated. The native Gemini
template, for which no adapter exists, is disabled with a compatible-endpoint
explanation. Provider/factory/no-intelligence checks then pass **96 tests**
(4.76 s), and the wizard's **8 tests** pass; no real account call is claimed.
The final affected combination including this protocol correction is
**1396 passed,5 skipped** (72.15 s).

The exact composed `018b175` Core and Multi-Arch runs subsequently failed, and
their original logs are retained: all full platforms exposed the older credential
test's mock of `_register_provider_runtime`, which the new prepare-before-save
path no longer calls. That test now checks the actual published adapter, Gateway
model and unchanged reference-only persistence assertions, restoring global state
afterward. Windows Core additionally failed the existing 16-owner cold checkpoint
test at `msvcrt.LK_LOCK` with `Resource deadlock avoided`. Initialization now queues
local owners through the existing bounded Runtime lock before the unchanged OS
file lock; separate processes still take that original lock. Neither Windows CRT
retry bounds, SQLite timeouts nor the original concurrency assertions are raised.
A four-interpreter cold-start/reload/integrity check also exercises cross-process
ownership. This is a software correction candidate until fresh platform CI passes;
it does not close the unrelated Windows Relay/HTTP/Automation timing Issues.

The subsequent `774e079` Windows Core job120431985987 passed all7 checkpoint
cases, including the original16-owner and new cross-process checks. The full job
then timed out at60 seconds in `test_private_remote_read_reuses_current_human_session`:
the stack is inside Governance `_db_connect` → `conn.commit()` during human login.
This is retained as a failed full job, not a full Windows PASS or proof of a
connection-leak root cause. The independent PR #89 lifecycle/phase diagnostics
remain under their original review; this observation does not justify increasing
the timeout, reducing durability or weakening authentication.

An installed-wheel lost-response Demo also exposed repeated full Workflow event
projections in AgentSession history after resume. The original restart and
approval scenarios reproduced **2 failures** (9 entries for6 unique events and
10 for7 respectively). Coordination now retains the newest exact distinct
projections; changed evidence remains distinct, and the existing256-entry bound,
original EventStream, Work, receipt and observation records are unchanged. There
is no bulk history migration. A300-event approval-wait/replay case separately
reproduced1 failure in the first deduplication candidate: filtering against the
previous window before truncating could displace recent events with older ones.
The final projection scans from the newest records and stops at256 distinct
entries; repeated replay retains the canonical stream's recent window, with the
original approval still pending. Comparison storage is bounded by that existing
limit. No measured model-Token or end-to-end speedup is claimed.

## Native session destination audit — 2026-10-23

The starting PR #83 source was `48a6cc1`; current main was still `e3cd2a20`.
**REUSE** the native process manager, Windows Credential Manager, Runtime API
client and connection version; **FIX** local-session destination and late native
response binding; **EXTEND** the existing startup/settings/diagnostic UI tests.
No credential store, API, execution authority or startup daemon was added.
Original component regressions retained **3 failures**: local startup used the
connection form's address, late session loading replaced a changed connection,
and local credential mutation proceeded for a selected remote Controller.

The corrected UI binds native session results only to the manager's validated
loopback endpoint and verified ready session, with original connection/version
and view checks. Credential rotation/removal, diagnostic recovery and workspace
restart require the selected local endpoint. Startup preserves a selected remote
Controller. Session-reset failure does not silently restart another process.
An action may already have completed when its response becomes unusable; no
automatic action retry or process cancellation is inferred.

New checks include the actual App bootstrap, remote/ABA/unmount negatives,
invalid destination/readiness/session rejection, transient input clearing and
the existing API client over two actual loopback HTTP servers. The authenticated
request reaches only the endpoint returned by the simulated native IPC host;
the other server receives no request. **22 focused tests** and the full Desktop
suite (**314 passed**) exercise this software boundary. Node HTTP fixture types
are development-only; the existing browser polling handles remain DOM numbers.
Related Runtime startup, provider, launcher, component-lock and two-file proposal
regressions have **39 passed**. This uses fake IPC/credentials, not an installed
Windows executable, actual Credential Manager qualification or a real model.

The preceding composed `7d0d88e` Core run `39880466334` completed on four
platforms: Linux Python 3.12 **5684 passed / 66 skipped**, Linux Python 3.10
and macOS Python 3.12 each **5673 passed / 77 skipped**, and Windows Python
3.12 **5662 passed / 88 skipped**; each retained four warnings. Those exact-source
results precede this frontend correction; new candidate CI and protected main
integration remain separate requirements. Main protection inspection still
returns administration HTTP 403. Native binary hashes, real model/IdP and
installed product acceptance remain **BLOCKED/PENDING** at their own Gates.

## First-use and Provider test integration — 2026-10-23

**REUSE** health/workspace APIs, native initializer/process manager, Provider
configuration, Gateway/NKI, model-test application service, usage and redaction;
**EXTEND/FIX** the original wizard and CLI adapters. No Registry, execution
database, credential store or approval authority was added. Original targeted
checks retained **7 backend failures** and **2 wizard failures**: direct setup
inference/diagnostic POST, guessed readiness, ineffective workspace selection,
UNKNOWN model completion, missing usage converted to zero and lost error binding.

Configuration validation now performs no credential resolution/network/inference.
Doctor/ping use GET metadata only. A saved explicit Provider test uses the
existing model-test service only for the original matching strict NKI Gateway;
changed mappings, compatibility Gateway or Gateway replacement cannot dispatch.
The existing model-test route records original request IDs on failure, returns
unknown usage/cost and accepts explicit completed outcomes. The legacy counter's
redaction correction preserves only null/nonnegative integers and rejects secret
strings/structures. Embedded-credential and unsupported base URLs are rejected
without copying their contents into diagnostics.

The wizard reads selected Runtime health instead of guessing architecture or
WebView availability. It initializes/restarts the exact selected local workspace
and confirms it through the original API, or keeps the remote Controller's scope.
Keyless setup preserves existing Providers. Saving completes once before the
completion screen; no conversation, inference or verified execution is invented.
Connection-version changes invalidate setup; response loss does not retry native
actions. Local HTTP/native IPC tests, fake Gateway replies and the real
authenticated Runtime HTTP configuration route establish software boundaries.
They do not qualify actual Windows Credential Manager, a real model invoice,
installed EXE, strong sandbox or hardware.

Affected backend regression: **504 passed**. Full Desktop: **321 passed** in
46 files. The preceding first native-session correction retains its separate
314-test full run. Changed-file format checking also required mechanical
formatting of the previously unformatted Provider experience module/test; their
pre-existing format failures were checked against the original Git contents.
No scanner rule, execution timeout or safety assertion was relaxed. Current-source
PR CI and protected main integration remain required; main and external product
Gates are not upgraded by these local results.

The source-browser qualification subsequently completed keyless first-use setup,
entered the existing Workbench and reopened its persisted configuration after
reload. Sandboxed Chromium used actual authenticated Runtime HTTP and its real
workspace registry, with a fake native IPC host; no POST/model request occurred
and there were zero page errors. Default proposal inspection remained denied,
as displayed by the original Governance boundary. This is a read-only source UI
qualification, not unrestricted developer mutation or Windows installation.
The fixture's initial generic network-idle wait and exact tab-name selector
failures remain retained; explicit readiness/tab locators resolved those harness
errors without changing application timeouts. A separate controlled delayed
native workspace reply exposed premature Next admission (**1 failed / 6 passed**).
The wizard now awaits the original health/workspace facts, without sleeps or
extra retries. Final full Desktop regression: **322 passed**, 46 files.

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
| Skill/Provider: `skills/`, public SDK, `tests/control_plane/test_skill_center.py` | REUSE / EXTEND | Reviewed local catalog install/load/enable/disable/uninstall with integrity and Governance. Controlled remote catalog/API/UI software now has owned HTTP/TLS permission, nonce, revocation and rollback cases; instruction loading is not executable Skill permission. Real publisher trust, deployed human identity and account-backed Providers remain unqualified |
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

## OCI readiness truth correction — 2026-10-14

**REUSE** the existing OCI Provider and strict ProcessSandbox report; **FIX**
passive readiness claims; **DEFER** engine and workload qualification. The
existing probe treated an engine path as available execution and containment.
Seven controlled cases fail before correction; one existing default-runner
denial case passes. Resolving an executable now only establishes discovery.
An exact strong report is required for default control readiness, failed probes
stay UNKNOWN, and a host-injected runner does not self-certify qualification.
The probe executes no command and claims no container isolation or engine health.
The actual default runner, injected reference execution and PID64 controls remain
unchanged. Final affected Environment, external reference, admission, Governance,
Control Plane and SDK contracts have **503 passed, 3 skipped** (17.50 s);
Python 3.10 focused readiness contracts have **12 passed**. These controlled
contracts do not qualify default Linux OCI, Python/scientific execution, PTY,
native installation or physical hardware. Source and resulting-main CI remain
required before acceptance.

## Controlled Skill identity and removal review — 2026-10-14

REUSE the Skill, Extension, Governance, human-session and CAS owners. FIX derived
Skill identity metadata and bind uninstall to its original reviewed content under
the existing Extension writer fence. Revoked Extension records retain their
existing trust state across owner reload and rejected reinstall. Tests cover
current human scope, content changes before removal, interrupted authority,
compatible updates/restarts and another installed Skill remaining unchanged.
The controlled pre-fix run retained **11 failed cases** (including missing bound
API contracts), plus **3 failed format/alias cases**; the same cases pass after
correction. Final added regression cases: **15 passed**. Affected Skill, Extension
and Control Plane regressions: **441 passed, 17 skipped**, also reproduced on
Python 3.10. Desktop lint/typecheck/build and **168 tests in 35 files** pass;
repository contracts: **288 passed**. These counts overlap. Owned HTTP/TLS and a
cryptographic fake identity qualify software boundaries only; production Catalog,
real IdP, installed Desktop, executable Skill and physical acceptance remain
unqualified. No Kernel or component-lock change is made.

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




### Environment command target binding — 2026-10-14

**REUSE** the existing Environment API, mutation Governance and canonical Runtime
capability dispatcher. **FIX** command target consistency: the execution arguments
must retain the same Environment selected by the route and reviewed by Governance.
A conflicting body target is rejected before policy/approval construction and
before the handler invokes the dispatcher; an omitted or identical target stays
compatible. Authentication still precedes this validation. No permission, Provider,
execution database or host fallback is added.

The original controlled handler/route/actual-loopback-HTTP regression retained
**15 failed, 3 passed**. Its dispatcher was instrumented with a fake bounded
result; this proves argument misbinding, not an unauthorized real workload effect.
The corrected contracts have **18 passed** on Python 3.12 (1.00 s) and Python 3.10
(1.70 s). Environment/Governance/Control Plane/Runtime-dispatch/terminal regression:
**509 passed, 2 skipped** (14.08 s). Original strict sandbox, high-risk approval,
credential and resource boundaries remain unchanged; default OCI control remains
BLOCKED without qualified strong isolation. This does not qualify actual OCI,
interactive PTY, native installation, physical devices or a remote human.

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

### Current-human Skill lifecycle revalidation — 2026-10-15

**REUSE / FIX** the existing Skill Registry, Extension writer fence, Governance
human session boundary and Operations API. Six owned-fixture probes showed that
revocation after initial admission could still change enabled state or return
instructions. Enable/disable now revalidate the exact reviewed identity, version,
digest and current human permission inside the existing publication fences.
Instruction acquisition rechecks current content, enabled/revoked state and human
permission before disclosure. Installation and instruction loading grant no
execution authority; no script is executed by these lifecycle operations.

Original causal contracts: **6 failed**; repaired: **6 passed**. Repository
lifecycle selection: **22 passed**; related Python 3.12 contracts: **391 passed,
17 skipped** (60.82 s); Python 3.10: **110 passed** (22.19 s). Counts overlap.
An initial additional package fixture used a nonmatching directory name; that
failure is retained separately and corrected without weakening assertions.
Ruff, changed formatting, compile, diff and existing 235-file links pass. No
OS-owner race immunity, deployed IdP, native Desktop, executable Skill, hardware
or production qualification is claimed. Kernel and component lock are unchanged;
source and resulting-main CI remain separate integration gates.

### Selected input secondary transfer and file alias admission — 2026-10-14

**REUSE** the original ContextBuilder/ContextGuard, WorkspaceGuard, Runtime Run,
Model Gateway recipient admission and usage ledger. **FIX** two candidate input
boundaries before publication; no additional authority, model registry or store.
The primary model's answer can contain selected-source text. Its collaboration
review previously lacked the selected-input hook, so current transfer revocation,
reviewer recipient changes, source changes or cancellation did not block that
secondary request. A private host factory now binds the actual review messages to
the same original Run, source snapshot and current reviewer permission. Review
failure stays visible and unapproved; model review grants no execution authority.
The new input digest describes source-derived candidate text, not proof that the
entire raw file was sent again or that a remote Provider received it.

Descriptor traversal denied symlinks but did not reject hard-linked input. The
opened regular file must now have one link both before and after its bounded
read. Protected/external aliases fail before reading; a link created during the
read prevents Context publication. Ordinary single-link files retain their path,
version, secret filtering and permission checks. Unsupported no-follow hosts,
including the current native Windows path, remain BLOCKED without a fallback.

Original deterministic fake-Provider reviewer regressions: **5 failed**. Owned
hard-link regressions before correction: **4 failed, 60 deselected** (0.80 s).
Corrected selected-input and collaboration focus: **102 passed** on Python 3.12
(13.85 s) and Python 3.10 (15.08 s).
Context, collaboration, Gateway/facade/accounting, fake NKI, persistent checkpoint
and Runtime admission regression: **596 passed** (17.38 s). The reviewer negatives
require no secondary dispatch or budget reservation; lawful review retains its
ordinary reported usage and original source lineage. One mistyped regression
path collected no tests and is retained; the corrected named selection ran.
These are controlled software/HTTP-fixture checks, not live model, native Kernel,
remote-human, physical or installed Desktop qualification. Existing isolation,
PID64, Kernel and component lock remain unchanged; source/main CI is still required.

The Gateway also removes the private admission hook from direct/stream adapter
requests after checking it and fencing dispatch. The original host request retains
its checks and evidence, while serialized IDs, messages, tools and metadata remain
unchanged. The original fake-adapter boundary checks had **2 failed, 2 passed**;
four allowed/denied direct/stream cases now pass within the regression above.
This minimizes exposure of a host callback; it is not evidence of leaked real
credentials or an authority exploit by a trusted host adapter. NKI payload and
original accounting/reconciliation semantics are unchanged.

The same review extended the existing `normalize_workspace_path` owner for
protected ordinary-file scopes. A benign owned probe established that hard-link
aliases of protected/external files entered Workbench and Chat read/search,
preview diffs and pre-approval proposal snapshots/CAS. Original files remained
unchanged and proposals still required approval; no real secrets or unauthorized
mutation were exercised. Placing an alias requires filesystem access to its
source; this is a scope/data-provenance correction, not a demonstrated remote
link-creation exploit. Static single-link admission now covers those existing
consumers, without changing explicit unprotected internal callers or adding a
file authority. Selected input preserves its stronger descriptor checks.
The new ordinary-surface contracts retained **3 failed, 1 passed** before repair;
after repair the alias/selected-input selection has **68 passed** (2.39 s).
Context/Model/Runtime/Chat/Workbench/proposal/API/checkpoint regression has
**863 passed** (25.99 s); Python 3.10 alias/selected-input regression has
**103 passed** (15.48 s). One initial private probe compared the enum against an
incorrect uppercase literal; the corrected probe uses the authoritative enum.
These checks do not qualify host-owner race resistance or native installation.

### Explicit host permission configuration and truthful status — 2026-10-14

**REUSE** PermissionEngine, PermissionRule, the canonical Gate and its authority's
private state. **EXTEND** explicit trusted-host policy input, selected solely by
`NOUS_PERMISSION_POLICY`; discovered files and model/request data cannot configure
authority. No policy/grant store or approval implementation is added. POSIX
owner-only regular-file, directory, no-follow, single-link, byte/rule bounds,
unique-key JSON, secret filtering and optional expiration fail closed. Every
permission check reloads policy; file removal/revocation/corruption blocks later
use. Runtime `add` is refused on file-backed policy. Native grants, Approval,
authorization/credential expiry, sandbox and billing remain separate requirements.
Windows owner-file loading is unqualified/blocked; trusted host injection remains
compatible, and selected file descriptor limits are unchanged.

The legacy permission query fabricated static granted flags from a new empty
engine. It now reads the canonical configuration, returns nullable UNKNOWN grants
without a subject-bound evaluation, and reports read errors instead of fake
success. Its four corrected contracts failed on the original handler. Rule
conditions also require present, exact-typed facts: original absent-null and
boolean/integer coercion contracts had **3 failed**; their corrected cases pass.

An actual Runtime HTTP service-bearer request now loads an explicitly selected
owner policy through ordinary Gate construction, without injecting a PermissionEngine,
and delivers admitted bytes to the owned HTTP Provider fixture exactly once.
Removing permissions after Provider setup causes zero sends. These **2 passed**
(2.55 s) preserve the original source/recipient/budget/Run checks. Initial fixture
errors omitted the known read-only chat Capability declaration and assumed a
load method; those failed attempts remain, corrected without changing admission.
Governance/Context/Model/Runtime/Chat/Workbench/proposal/API/checkpoint regression:
**1107 passed** (31.52 s). Final Python 3.10 policy/input/alias selection has
**127 passed** (18.31 s), including the exact-type cases. Live vendor,
remote-human, strong execution, physical and native qualification stay incomplete.

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

### Artifact validation vocabulary measurement — 2026-10-15

**REUSE / FIX** the canonical ArtifactType Enum and existing CAS validation. An
owned Linux warm-filesystem baseline found metadata reads scaling from 0.027 ms
p50 at one record to 12.52 ms at 1000 records. The candidate derives one immutable
type-value set from the same Enum instead of allocating that same set for every
validated record. Every read still reloads the actual index, validates every
record and performs the same content checks. No index/stat/permission cache,
fsync, locking, GC, redaction or integrity rule changes.

Three alternating child processes per variant each measure 100 reads against
the exact same unchanged 1000-record index (593893 bytes).
All 300 samples per operation/variant are retained:

| Operation | Before p50 / p95 / p99 (ms) | Candidate p50 / p95 / p99 (ms) | CPU seconds before / candidate |
| --- | --- | --- | --- |
| metadata get | 13.08 / 17.87 / 20.52 | 8.87 / 11.35 / 15.57 | 4.083 / 2.768 |
| resolve + content verification | 25.49 / 34.25 / 38.93 | 17.68 / 23.54 / 101.49 | 7.971 / 6.047 |

This exploratory single-host microbenchmark supports reduced median/CPU overhead,
not guaranteed tail latency: the slower candidate resolve p99 remains recorded.
It is not a Windows failure explanation, end-to-end or Token-cost improvement.
Artifact/Node/Governance/Reality contracts: **580 passed** (130.19 s); focused
Artifact contracts: **31 passed** on Python 3.12 (1.80 s), **31 passed** on Python
3.10 (1.47 s), overlapping the combined selection. Kernel and component lock
are unchanged; exact source/main CI remain required.

Current-main controlled comparison (2026-10-16) starts from `629b13f` and fixes
three rounds in order AB/BA/AB, 100 samples per operation in each child process:
**300 samples per operation/variant**, the same unchanged 1000-record,
593893-byte index, one-CPU affinity and a warm local Linux filesystem. The host
is shared, not exclusive. The actual candidate source bytes match the measured
module SHA-256 `c336f43a64b344527a69d2e69798316c237c3adedaa6d07b056737ac62354977`.
Only the declaration order of independent constants was aligned to that exact
measured module; no admission or validation behavior changed.

| Operation | Before p50 / p95 / p99 (ms) | Candidate p50 / p95 / p99 (ms) | CPU seconds before / candidate |
| --- | --- | --- | --- |
| metadata get | 12.485 / 16.132 / 27.362 | 9.336 / 12.551 / 15.095 | 3.947 / 2.929 |
| resolve + content verification | 25.821 / 32.586 / 35.727 | 17.745 / 21.589 / 26.408 | 7.957 / 5.457 |

Peak child RSS was 18820 KiB before and 18788 KiB after. Raw samples, manifest,
index hashes and source trees remain outside source control. The earlier slower
101.49 ms p99 is retained above; the new fixed comparison is separate evidence,
not a replacement favorable rerun. The 300-sample shared-host tail has statistical
limits and does not establish end-to-end, Windows, network or Token savings.
After normal dependency integration, Artifact/Node/Governance/Extension writer
and Skill installation contracts have **565 passed** (28.11 s); focused Artifact
contracts have **31 passed** on Python 3.12 (0.97 s) and 3.10 (0.99 s). Current
index reloads, cross-instance graph/pin/GC ownership, corruption rejection,
redaction, signed results and no-replay behavior remain unchanged. Required
source and resulting-main CI remain separate gates.

### OCI readiness current-main integration — 2026-10-16

**REUSE / FIX** the original closed-unmerged PR 68 continuation, existing OCI
Provider, ProcessSandbox admission and Environment status API. Normal dependency
merges preserve the target-binding implementation from PR 78 rather than adding
a second fix; after preceding gates the remaining scope is four existing files
(Provider, readiness tests and canonical documentation). The passive probe
separates engine discovery from strong control admission, unknown engine health
and not-run workload qualification. It starts no engine command or workload.
No default PID64, mount, network, credential, authorization or sandbox change.

Integrated Environment/terminal regression: **149 passed, 3 skipped** (1.56 s).
Python 3.10 target/readiness contracts: **30 passed** (1.21 s). All 12 existing
repository-standard checks pass; security retains **0 HIGH / 5 MEDIUM** with
the reviewed private-IP SSRF fixtures from the Catalog dependency.

An actual service-authenticated loopback HTTP status request on this Linux host
reports Docker found, `available=false`, `control_admission=blocked`,
`control_security_grade=resource_only`, `engine_health=unknown`, and
`workload_qualification=not_run`. No workload or host fallback ran, and the owned
HTTP thread/server were closed. Initial private driver errors omitted creation
of the selected workspace and assumed a different Provider ID; those attempts
remain separate from the corrected check using the canonical Provider ID.
This is truthful preflight/status qualification, not actual container isolation,
Python/scientific execution, PTY, native installation or physical acceptance.
Source and resulting-main CI remain required before integration.

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

### Node registration peer binding — 2026-10-15

**REUSE / FIX** the existing configured Controller signing key, Node identity,
NodeProtocolEnvelope and ReplayWindow. Ordinary session messages already enforce
the expected Controller source and exact Node target. The registration helper
verified the signature but omitted those peer checks before saving the session
and collecting host reports. Two controlled loopback probes with a correctly
signed but differently addressed ACK reached the forbidden host probe (**2 failed**).

The same source/target checks now apply before registration replay acceptance,
session publication and host reporting. No identity/key/trust-root, authority,
Work, timeout, replay-window or automatic retry changes. Negative cases exercise
both absent and retained original session records; neither can be replaced by
foreign session data. Existing valid registration, signed execution, Artifact,
lease, cancellation and reconnect contracts remain exercised.

Node/Reality/Artifact/AgentSession/Governance operation regression before adding
the two retained-session variants: **422 passed** (131.17 s). Final protocol
selection including those variants: **18 passed** on Python 3.12 (0.90 s) and
Python 3.10 (0.92 s). These are controlled software protocol tests, not remote IdP,
physical or native installation qualification. Exact-source CI and resulting-main
acceptance remain required; this does not establish the cause of Issues #4/#8 or
claim exhaustive handshake/replay qualification. Kernel and component lock stay
unchanged.


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




Selected-input candidate Core run `38819836324`, Windows job `116713447362`,
retains **4983 passed, 149 skipped, 4 warnings, 2 errors** (1401.08 s).
Both errors occur in pytest setup/teardown: its generated node ID embeds the
65 KiB oversized bytes fixture and exceeds Windows' 32767-character environment
variable limit before the test body can run. Explicit short parameter IDs retain
all five original payloads, byte limits and refusal assertions. The 64 collected
node IDs now have maximum length 138. No new skip, timeout increase or production
read fallback is introduced. Current source still blocks selected-source delivery
on hosts without the required safe descriptor operations.

After integrating main `c43f942`, the combined Context/owner-policy/Gateway/Node/
Reality/Artifact/file-alias/Node-and-Device projection regression has **1184 passed**
(174.68 s); Desktop lint/typecheck/test/build has **181 passed in 38 files**.
After the parameter-ID correction, selected-input/integration/owner-policy has
**119 passed** (15.58 s), and selected-input alone has **64 passed** on Python 3.10
(2.20 s). The failed Windows run remains evidence; corrected Windows and exact
source/resulting-main CI are separate outstanding acceptance, not inferred from
these local passes. No real Provider task, Token saving or Windows-native release
qualification is claimed.

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


The same source-browser screenshot review found that page-level overflow checks
alone missed four long identifier/control boxes outside the Automation pane at
390 pixels. A stricter actual-browser bounds check retained **1 assertion
failure**, with four off-pane boxes. Scoped rules in the existing Operations CSS
now wrap the form, stack its record contents and wrap full evidence identifiers;
no backend or mutation logic changes. The unchanged four-scenario browser flow
then has zero off-pane boxes, no pane/form overflow, and the same **1/0/0/1**
effect counts with original recovery bindings. Final Desktop lint/typecheck/
test/build: **219 passed in 40 files**. These are source-browser layout and
execution checks, not installed Windows screenshots.

The existing public simulation measurement script was also run on exact main
`c43f942`: **12/12** fresh isolated Controller workspaces reached COMMITTED/MATCH,
each with one effect. Local observer monotonic nearest-rank p50/p95/p99 were
**1.625 / 1.737 / 1.737 seconds**. The preview uses the same fixed Work ID in
separate workspace namespaces; these are not 12 globally unique operation IDs.
Linux child CPU was 15.008 user + 1.700 system seconds, with `getrusage` child
maximum RSS 86480 KiB, not aggregate steady-state service memory. An unavailable
`/usr/bin/time` was a measurement preflight error; the successful wrapper uses
Python's existing process/resource facilities. No comparison, Token reduction,
WAN/physical performance or research-experiment PASS is inferred.


A fresh wheel from clean Automation candidate `ab92d13` was installed into a new
virtual environment and exercised outside the checkout with no `PYTHONPATH`.
**18 CLI processes** again preserve the original approved COMMITTED/MATCH Work
and duplicate trigger/effect count one, deny/cancel with zero effects, and reject
late approval after cancellation. Explicit simulation is required. Wheel SHA-256:
`8d975c0f0acd9b13698b21503d83e5a684e8bf8a69df8ca91131895fee37d6ee`.
This is an installed source-package CLI and local OS-human boundary, not an
NSIS/native installation, remote identity, background scheduler or physical Gate.


### Automation start acknowledgement and uncertain effect evidence — 2026-10-15

After normal integration with main `893cbe4`, the combined run retained
**1 failed, 203 passed** (170.13 s). The failure precedes cancellation: the Node
already persisted COMPLETED and the device effect count is one, but the
Controller still has ASSIGNED rather than RUNNING because its start ACK was not
recorded. An isolated repeat passed (**1 passed**, 6.32 s), which is not a fix.
Controlled omission of the start ACK reproduces the exact original assertion
failure (**1 failed**, 5.79 s). Existing signed-result reconciliation already
admits original ASSIGNED Work; ASSIGNED cannot prove an effect did not occur.

The test now separates start-ACK delivery from terminal-response loss. The
recorded-ACK cases use an explicit publication barrier and retain the exact
RUNNING assertion. The ACK-loss cases require exact ASSIGNED, a completed original
Node journal, no Controller receipt or MATCH, and reconciliation of the original
operation. Both are tested with and without cancellation and later grant
revocation. All original final MATCH/COMMITTED, same-run, one-effect and exactly
one grant-consumption assertions remain. No production state, timeout, retry,
protocol, authority or safety assertion is relaxed. This is a controlled causal
fault matrix, not sleeping or treating a passing rerun as resolution.

The four-case matrix has **4 passed** (23.16 s) on Python 3.12 and **4 passed**
(23.30 s) on Python 3.10. This identifies the candidate test's notification
assumption; it does not establish the OS cause of historical Issues #4/#8 or
upgrade Windows, WAN, native or physical acceptance.


### Automation Windows negative-history investigation — 2026-10-16

Candidate `5c28901` Core run `38825658046`, Windows job `116732406366`, retains
**1 failed, 5081 passed, 60 skipped, 4 warnings** (2020.16 s): the receipt variant
of the committed-history tamper test did not raise WorkflowBindingError. Other
selected platforms passed. The original failure did not record the Workflow/Work
state immediately before tampering, so its cause is **not established**. It must
not be dismissed because other runs or platforms passed. The candidate remains
a draft; no Windows or integration Gate is promoted.

The negative test now explicitly requires COMPLETED Workflow and COMMITTED Work
before modifying evidence, preserving the original tamper/rejection assertion.
On failure it reports only state, step status, reconciliation/effect count and a
timeout-present boolean. This distinguishes an incomplete setup from acceptance
of a tampered committed receipt; it does not itself fix or prove the cause of the
Windows failure. All fourteen strengthened semantic-tamper cases pass locally
(8.07 s). No production Runtime, approval, signature or verifier change is made
for this investigation. Exact updated-source Windows evidence is still required.

### External-provider spool publication and Windows baseline evidence — 2026-10-16

Main `c43f942` Core run `38822457356`, Windows job `116723873694`, retains
**1 failed, 4970 passed, 60 skipped, 4 warnings** (1539.12 s). The external-provider
signed Node protocol case returned `ok=false`; its old assertion did not print
the provider error code. The initial-reports ConnectionClosed warning alone does
not establish the cause. The unchanged condition now includes redacted error-code
and content-free phase/memory/result-presence diagnostics for a future failure.
No assertion, timeout or keepalive setting is relaxed.

**REUSE / FIX** the existing Node journal, signed result admission, Controller
spool and remote-provider binding checks. A controlled post-publication cleanup
PermissionError reproduced replacement of a real original signed result with
`REMOTE_PROVIDER_REQUEST_REJECTED` in two cases (**2 failed**). An earlier fixture
passed no socket for the existing acknowledgement and had two setup failures;
its correction reuses the signed RecordingSocket fixture and retains the same
original-result assertions. Separate before/after-publication I/O probes retained
**2 failed, 2 passed** after the cleanup correction: publication failure was also
incorrectly materialized as rejection and could erase its request binding.

Cleanup is now best-effort only after the result is durable. An OSError retains
the original request and does not invent rejection or no-effect evidence.
Restart reads the admitted original signed result and retires the original
request without another pending dispatch. Before-publication failure has no
published result; after-publication failure preserves its exact bytes. Node
journal bytes and receipt bindings remain unchanged. Permanent malformed input
still rejects before dispatch. These are component/storage faults using real
Node journals and signatures; the broader Reality regression retains independent
observation/MATCH requirements. The spool response alone is not an effect commit.

Relevant Node/Reality/Artifact/Usage/Gateway/Workflow regressions: **712 passed**
(137.37 s), before two additional malformed-input cases. Final remote-provider
and protocol selection: **48 passed** on Python 3.12 (1.87 s), **48 passed** on
Python 3.10 (1.93 s). Exact-source Windows/ARM64 CI and resulting-main validation
are still required. The controlled defect matches a possible false-result path,
not an established cause of the earlier Windows failure or Issues #4/#8.

Main `c43f942` Multi-Arch run `38822457553`, Windows job `116724755654`, separately
retains **1 failed, 4659 passed, 60 skipped, 272 deselected, 4 warnings** (1740.94 s).
Its Connector timeout result was correctly `CONNECTOR_TIMEOUT`, but total local
elapsed time **0.96258 s** exceeded the unchanged **0.5 s** assertion. No production
or accepted-test change is made for that unexplained timing failure here.

Temporary diagnostic source `195d366` and run `38827287779` use the existing
Windows diagnostic workflow, retaining the same timeout/elapsed assertions while
measuring adapter wait, registration, health and result-storage phases. Twenty
isolated Windows samples pass (elapsed **0.03874–0.08554 s**, maximum health write
0.06347 s); the adapter had not finished before release in all 20. This does not
reproduce the full-suite failure, prove absence of a race, or qualify production
Multi-Arch. The diagnostic branch must not be merged. Its prior recovery traces
and all failed runs remain available. Kernel and component lock are unchanged.


An independently explored local execution-worker drain prototype is **REJECTED**,
not part of this spool fix. It incorrectly treated the transport task as execution
owner. Its narrow 71-test selection passed, but the existing wider cancellation/
reconnect contract retained **1 failed, 950 passed** (135.43 s): transport must
return cancellation while the admitted handler remains journal-owned EXECUTING,
then deliver its original completed result on reconnect with one invocation.
The prototype made that valid contract wait for the held handler and reach its
watchdog failure. The original test is unchanged, and no worker-drain change is
included here. The local candidate, initial fixture failures and failed broader
run are retained privately to prevent its accidental integration. Passing narrow
probes did not justify overriding the existing authoritative recovery path.


The retained-request recovery matrix also injects Node revocation before
Controller restart. With the publication/cleanup fix alone, its corrected probe
retained **4 failed, 4 passed**: re-entering execution admission to read a known
result could replace it with a revoked-node rejection. The earlier probe also
had two test-wrapper argument errors; those fixture errors are not evidence of
a production defect. Recovery now validates the persisted Node signature and
original request/receipt binding before reading already admitted evidence. It
does not transfer artifacts or queue another execution. Changed retry inputs
cannot erase or borrow the original result. The same revoked Node still rejects
a separately submitted new workload, and its persisted REVOKED state survives.

The four I/O boundaries, trusted/revoked Node and original/changed retry matrix
retain byte-identical original journals and previously published results. Final
protocol/provider selection: **60 passed** on Python 3.12 (2.62 s), **60 passed**
on Python 3.10 (2.64 s). Expanded Node, Reality, Artifact, Governance, model,
AgentSession, Workflow, Usage and Connector regression: **961 passed** (130.14 s).
Exact-source platform CI must qualify this additional runtime change separately
from the earlier publication-only source. No Kernel or component lock changed.

Full-suite Connector diagnostic run `38828059028`, source `2393bd7`, retained
**9 failed, 4680 passed, 60 skipped, 272 deselected, 4 warnings** (1887.40 s).
Twenty instrumented Connector samples satisfy the unchanged 0.5-second bound
(elapsed 0.06481–0.21026 s); health storage reaches 0.18288 s. This still does not
reproduce or resolve the earlier 0.96258-second failure. Eight diagnostic failures
are cp1252 Unicode output errors with uncaptured stdout. The remaining delayed
Observation restart case ended WAITING instead of COMPLETED; its original
assertion and failure remain, with cause unestablished. This diagnostic branch
is not acceptance and must not merge. No production timeout, Connector assertion
or effect verification is relaxed.


Automation source `14be54f` retains all three PR checks and separately completed
Core `38830702842` and Multi-Arch `38830705527`. Windows Core: **5083 passed,
60 skipped, 4 warnings** (2209.01 s); Ubuntu 3.12: **5096 passed, 47 skipped,
4 warnings** (724.27 s). Multi-Arch Linux amd64/ARM64 each have **4772 passed,
59 skipped, 272 deselected, 4 warnings** (571.72 / 588.46 s), with platform
detectors **13 passed** each. Windows 3.11 has **4771 passed, 60 skipped,
272 deselected, 4 warnings** (1932.24 s). These strengthened precondition tests
passed; they do not establish the cause of the earlier Windows tamper-probe
failure or justify closing it from reruns alone. The normal integration of
Relay source `32f3c7d` requires fresh combined regression and exact-head CI;
earlier browser/wheel evidence remains explicitly scoped to source `5c28901`.


A further HTTP writer-contention probe of the unmerged Automation consumer
retained **2 failed, 1 passed**: after initial nonce admission, session or
management-permission revocation prevented execution but still left a new
PENDING Run when the delayed writer acquired its lock. **REUSE / FIX** the
existing management callback and Workflow transaction; the callback now runs
inside first-trigger publication before creating the Run/relation. This changes
no execution authority and adds no store. Duplicate original-run reads remain
compatible. Controlled session revocation, persisted expiry, permission denial
and valid admission retain explicit nonce/replay, restart and zero-effect checks.
The final writer/creation/toggle/concurrent-trigger/checkpoint selection has
**15 passed** on Python 3.12 (9.07 s), **15 passed** on Python 3.10 (9.29 s).
Exact-head CI must qualify the additional runtime change.

Normal integration parent `9d9fff9` was also exercised using actual Runtime HTTP
and the built source Operations Console: Approve Once, Deny, Cancel and response
loss/recovery retain the same original Run/Work and effect counts **1/0/0/1**.
Both successful flows have original receipt, fresh Observation and MATCH. Logout
disables mutation, no model request occurs, and the 390-pixel form/pane have no
horizontal overflow or off-pane evidence/control bounds. This uses signed fake
identity and the explicit simulated template; it is not a deployed human IdP,
installed APEIR.exe, physical effect or cross-network qualification.

Spool source `32f3c7d` passed four-platform Core `38856754480`, including Windows
**4994 passed, 60 skipped, 4 warnings** (1515.80 s), but Multi-Arch `38856756820`
retains Windows **1 failed, 4681 passed, 60 skipped, 272 deselected, 4 warnings**
(1505.06 s). The delayed Observation restart case returned WAITING on a new
independent read after its first held read had completed. It did not commit
without observation. The production spool/Node implementation remains unchanged
from that source; the failed Windows run is not treated as acceptance.

A controlled second signed-read hold reproduces the same WAITING-versus-COMPLETED
assertion with the old test driver (**1 failed**). That driver followed only one
paused acquisition and assumed the next resume must finish synchronously. It
now follows each distinct exact read's terminal signed evidence before another
continuation, checking original Workflow, device, Node, capability, Artifact and
mutation bindings at every pause. Missing read evidence still blocks; repeated
already-consumed read IDs fail rather than spin. The existing final COMMITTED,
MATCH, original Workflow and effect-count-one assertions remain, and both held
observations are excluded from the final fresh verification. The original
`delayed` and `missing` case IDs are preserved; `delayed-again` adds the second
controlled pause. Production waits (including three seconds), receipt waits and
retry settings do not change. The test driver also has the existing CI's
60-second bound; it does not increase that CI limit. Python 3.10 recovery-driver
selection: **9 passed** (41.68 s), including missing result and producer-failure
cases. Fresh exact-head CI remains required. This corrects a demonstrated test
consumer assumption, not an established root cause of Windows storage latency
or proof that no runtime race exists. Issues #4/#8 remain open.

### Connector explicit admission contract — 2026-10-16

**REUSE / FIX** the exported Connector library and existing Governance decision;
no new API, policy or execution authority. An adapter write now requires both
EXECUTE and explicit boolean `allowed=True`. Controlled decision probes before
the fix retained **9 failed, 1 passed**: five missing/false/nonboolean admission
flags reached the mock adapter, while absent/invalid modes could raise instead
of returning the existing denial result. The valid canonical decision still
executes once. A first invocation used the wrong checkout and selected no tests;
that orchestration error is not counted as a reproduction.

The original nine Connector tests, including the unchanged timeout bound, and
the ten decision probes have **19 passed** on Python 3.12 (0.22 s), **19 passed**
on Python 3.10 (0.25 s). Governance/Connector/Workflow safety regression has
**275 passed** (6.58 s). The previous Connector wall-time failure remains
unexplained; no health-I/O, timeout, retry or persistence setting changes here.
The library export has no current Desktop consumer; these tests do not qualify
a live enterprise service, credentials, physical effects or complete product
integration. Exact-source checks and normal PR integration remain required.


Connector source `9d80c48` Core run `38857997503` retains **1 failed, 5000 passed,
47 skipped, 4 warnings** (478.00 s). The wider response-loss regression imported
a shared Gate fixture that supplied EXECUTE without the contract's `allowed`
field, so it was denied before reaching the intended effect-once fault. The
initial targeted selection omitted this separate retry module. The shared
fixture now returns the existing canonical AuthorizationDecision with explicit
boolean admission. All nine original test-function ASTs remain unchanged; no
response-loss, effect-count, retry-budget or timeout assertion was weakened.
The complete three-module Connector selection and Governance/Workflow regression
are rerun before publishing the correction. The failed full CI is not relabelled
as a baseline environment failure or erased.


### Process startup observation consistency — 2026-10-16

Main `b71a766` Multi-Arch `38860036017`, Windows job `116839996688`, retains
**1 failed, 4673 passed, 60 skipped, 272 deselected, 4 warnings** (1379.91 s).
The unproven-host binding case remained RECOVERY_REQUIRED/stdin unavailable,
but returned host-state-missing instead of the required helper-identity-changed
reason. The exact error assertion is preserved, not broadened to accept either.

**REUSE / FIX** Distribution ProcessSessionStore and its existing host projection,
OS creation identity checks, journals, controls and deadlines. Startup had read a
ready record, then called status to read another record before classifying it.
A controlled missing second sample using the real process reproduces both the
original identity assertion and loss of a valid startup sample (**2 failed**).
One poll now projects its exact observed record with the same current OS identity
checks. Subsequent status/control calls still read again. A separate negative
proves later missing state returns RECOVERY_REQUIRED, denies stdin and publishes
no control despite the earlier valid RUNNING snapshot. Original single-launch,
wrong-identity and no-control/replay assertions remain unchanged. All original
startup test-function ASTs are unchanged. No change under `nous_runtime/kernel`,
no 10-second deadline increase, new store, process retry or isolation fallback.

Startup selection has **11 passed** on Python 3.12 (19.40 s), **11 passed** on
Python 3.10 (19.49 s). Full related regressions and exact-head CI are required.
This reproduces the double-sample failure class; the cause of the Windows file
read intermittency itself remains unestablished. It does not qualify a persistent
PTY, strong product sandbox, installed Desktop or production release.

Automation source `2bc4166` Core `38857348310` retains Windows **1 failed,
5104 passed, 60 skipped, 4 warnings** (1999.26 s): the device-disconnect test
asserted Controller FAILED while its original terminal result had not yet
projected and Work remained RUNNING. Source 443fc72's earlier qualification is
superseded by this additional test-consumer correction; a cancelled superseded
run is not a passing result. No production Runtime code changes in this step.

A controlled signed-status hold reuses the original failure/disconnect test
function and its assertions. Both faults reproduce the same pre-terminal
assertion (**2 failed**). At that barrier the actual Node journal is FAILED,
Controller Work is RUNNING, no Controller result exists and effect count is zero.
After release the original test now waits for that exact result and calls the
existing Controller reconciliation. FAILED, OFFLINE, zero-effect and no
re-execution-after-reconnect/resume assertions remain. Four immediate/held
cases pass on Python 3.12 (1.16 s) and 3.10 (1.17 s). The full Reality suite has
**118 passed** on Python 3.12 (122.11 s) and **118 passed** on Python 3.10
(123.76 s), including the repeated independent-read pause correction. Neither
10-second production waits nor the existing 60-second CI limit changes.
This demonstrates an asynchronous projection assumption, not the cause of
Windows delay or a completed performance/physical/network qualification.


Source `5b7d6a2` Multi-Arch `38863786127` retains Windows **1 failed,
4696 passed, 60 skipped, 272 deselected, 4 warnings** (1520.21 s). The
response-loss/restart case returned VERIFIED after a single Workflow Resume,
before independent observation completion. The original terminal assertions
remain; a controlled hold of each of two actual read results reproduces the
one-resume assumption (**1 failed**, 17.02 s). Success-path continuation now
reuses the existing exact-read receipt/reconciliation helper. The no-effect
lost-response case still takes its original failure path, and ACK interleaving,
same original Work, MATCH, one observation, state change and effect-count checks
are retained. Five immediate/held recovery cases pass on Python 3.12 (23.41 s) and Python
3.10 (23.60 s). The final
full Reality regression has **119 passed** (122.73 s); the controlled case also
requires two distinct held read acquisitions.
This corrects another test consumer of the asynchronous contract; no production
wait, retry, process startup deadline or execution authority changes. Fresh
cross-platform CI is required; the failed run is not relabelled as successful.


### Automation VERIFIED recovery admission — 2026-10-16

**REUSE / FIX** the existing Automation projection, Workflow/Work owners,
original Node journal, signed receipt, Reality recovery and EffectVerifier.
The projection omitted VERIFIED mutation Work when its Observation was missing
or MATCH had persisted before COMMIT publication failed. That could hide the
original recovery actions even though the effect had already occurred. The
projection now keeps both cases reconciliation-required; it does not execute
anything or convert a missing verdict into success. Explicit MISMATCH remains
uncommittable. No new grant, mutation Work, retry or authority is introduced.

Dropping the actual read result after Node observation and failing the original
COMMIT publication reproduce **2 failed** projection assertions before the fix.
Both cases now recover the same Run/Work using existing public Reconcile and
Resume, persist MATCH and COMMITTED, and retain effect count **1**. Lost read
observation IDs are excluded from the fresh verification. The targeted history
and recovery selection has **18 passed** on Python 3.12 (21.00 s) and Python
3.10 (22.14 s), including 14 unchanged semantic tamper categories.

Source `7d2ce48` full Core `38861767549` retains Windows **1 failed,
5118 passed, 60 skipped, 4 warnings** (2399.18 s). The committed-history
fixture failed before tampering: Workflow was failed and original Work VERIFIED.
Its shortened CI representation did not retain the verdict or precise cause;
this is not proof of the cause of an earlier changed-receipt rejection failure.
The test now reports concise content-free preconditions. Only an exact original
independent-read timeout, VERIFIED mutation without verification, bound read
Work and effect count 1 permits one explicit public Reconcile/Resume before
tampering. COMMITTED and tamper rejection remain mandatory. A controlled lost
read reuses the original changed-receipt test to exercise that continuation.
MISMATCH, UNKNOWN and other failures are not retried into an accepted fixture.

Current main `380e657` has successful Core `38864193438`, Multi-Arch
`38864193549`, Desktop `38864193441` and Security `38864193443`. Windows
Core has **5009 passed, 60 skipped, 4 warnings** (1513.97 s); Windows
Multi-Arch has **4695 passed, 60 skipped, 272 deselected, 4 warnings**
(1328.62 s). These main results do not certify this unmerged Automation code.
Exact-head affected regressions and CI remain required. Product/native, physical,
real IdP, actual model engineering and strong-environment qualifications remain
separate; no full product PASS or Windows timing root cause is inferred.

The final Automation/Node/Governance selection has **593 passed** (218.89 s);
Workflow/safety/human-session regressions have **81 passed** (1.97 s).
Explicit negative-observation checks have **2 passed** (2.74 s), retaining
MISMATCH as uncommitted and UNKNOWN as reconciliation-required. The native
verifier on main `380e657` still fails with the exact missing locked Windows
`nousd-x86_64-pc-windows-msvc.exe`; component-lock bytes are unchanged.


### Unified-main target-binding qualification — 2026-10-16

The renewed audit begins at accepted main
`629b13f38a2b663b00596782c0e85be6731d2c5a`; its Core, Desktop,
Multi-Arch and Security workflows all completed successfully. Six remote
branches, 31 unchanged historical checkpoint tags, open PR 67, open Issues
1/2/4/8 and no published Releases remain. Re-query before subsequent mutations.

**REUSE** the existing Environment API, authorization route, Capability executor,
original unmerged target-binding fix and its tests. **FIX** the route/body target
inconsistency before proposal construction and again before dispatch. An exact
main reproduction retained **15 failed / 3 passed** (1.31 s), including real
loopback HTTP with an instrumented dispatcher; no actual external workload was
executed. This is an argument-binding defect, not physical-effect evidence.
Normal merge retained the original fix SHA and all main changes. The shared
fixture now returns the canonical explicit allowed AuthorizationDecision rather
than an incomplete EXECUTE-only object. All 18 original cases and their
assertions are retained. Final target checks: **18 passed** on Python 3.12
and **18 passed** on Python 3.10 (0.83 s each). Environment/Governance/Control
Plane/Capability/terminal regressions: **572 passed / 6 skipped** (16.02 s).
An earlier selection named nonexistent test files and collected no tests; that
invocation is retained separately and is not counted as successful regression.

**EXTEND** the existing external-agent Provider and official MCP SDK boundaries;
the present production MCP code is a client, while server objects occur only in
test fixtures. A public scoped APEIR MCP server and qualified Codex App Server
Harness path are **MISSING**. Official App Server documentation was fetched and
installed `codex-cli 0.159.0-alpha.3` generated its current JSON schemas; schema
inspection is not an authenticated engineering task or integration PASS.
**DEFER** physical Jetson/ESP32, installed native binaries and production release
until their independent prerequisites are available. Kernel/component lock,
sandbox requirements, authorization and uncertain-effect recovery are unchanged.

Before any queued branch abandonment, all five remote tips and the OCI local
continuation were saved in one owner-protected Git Bundle. Bundle verification,
independent bare-repository restore, exact-ref comparison and full connectivity
checks passed for all six refs. Raw Git objects and runtime evidence stay outside
the source tree; existing dirty worktrees were not discarded. Saved diagnostics
are not automatically accepted product code. Exact-source PR and resulting-main
CI remain separate gates.

### Saved workspace input current-main integration — 2026-10-16

**REUSE / EXTEND / FIX** the original PR 67, ContextBuilder/ContextGuard,
WorkspaceGuard, live PermissionEngine, Gateway admission and existing Inspector.
Normal merges preserve current main and the target-binding candidate; PR 67 is
dependent on PR 78 and cannot bypass its qualification. No second authority,
Context store, registry or model execution service is added. Saved selection
requests separate current read and exact Provider-recipient transfer permission;
Chat uses the existing authenticated service identity, not human approval power.

Combined Context, owner-policy, model/accounting, file-alias, permission-status,
Node-protocol and Environment-target regression: **813 passed** (22.52 s).
Python 3.10 policy/input/alias selection: **127 passed** (17.95 s). Desktop lint,
typecheck, **220 tests** and build pass against the integrated main UI. All 12
existing repository-standard checks pass; scanner findings remain 0 HIGH and
3 known MEDIUM. Windows no-follow source delivery and owner-file ACL admission
remain explicitly blocked; no host fallback is introduced.

At source `adbb6e3`, an actual sandboxed source Chromium browser selected a saved
file, called Runtime HTTP using an explicitly configured owner-file read/transfer
policy and delivered the exact version to an owned fake HTTP Provider once.
The source path was absent from Provider input; the Inspector showed read/sent
provenance and opening it made zero extra model calls. The file stayed unchanged,
page errors were absent and the 390-pixel viewport did not overflow. Servers,
threads and browser were closed. An initial private driver used a nonexistent
title selector for the Inspector button; that timeout remains recorded, and the
correct driver uses its actual accessible button name. No product assertion was
weakened. Evidence/screenshots remain outside source control. This is software
HTTP/UI integration with an explicit fake Provider, not native APEIR.exe, NKI,
real remote-human or paid vendor task acceptance. Exact-source CI and main
integration are still required.

The first target-binding candidate `c5e82aa` passed Core, Desktop, Security and
Linux Multi-Arch, but Multi-Arch `38920847961` retained Windows **1 failed,
4829 passed, 60 skipped, 272 deselected, 4 warnings** (2093.64 s). Its controlled
two-observation response-loss test timed out awaiting original signed read
delivery and recorded a Relay heartbeat disconnect. This is not an Environment
target-binding failure and is not relabelled PASS. The original raw job log is
retained outside source control.

The injection polled `AgentSessionStore.get` synchronously on the transport
event loop while coordination used its existing writer lock. A bounded writer
lock held until a scheduled loop callback reproduces starvation: **1 failed**
(2.71 s). Polling that same original Session through `asyncio.to_thread` makes
the callback and store access progress without weakening transport isolation or
authority. Only test-side durable reads change. Existing 15-second polling and
60-second outer deadlines, original read IDs, signed-result checks, VERIFIED,
MATCH/COMMITTED and one-effect assertions remain. The six focused recovery and
lock-contention cases pass on Python 3.12 (23.26 s) and 3.10 (23.54 s).
The full Reality regression has **120 passed** (121.69 s); all 12 existing
repository-standard checks also pass, with 0 HIGH and 3 known MEDIUM scanner
findings. Target-binding regression remains **18 passed**.
This proves a blocking source in the injection, not the cause of every Windows
timeout; Issues 4/8 remain open. Exact updated-source cross-platform CI is still
required before integration.

### Controlled Catalog current-main integration — 2026-10-16

**REUSE / EXTEND / FIX** the existing Skill/Extension registries, CAS, central
WebGateway, current human-session/nonce authority and Operations Console.
Normal dependency merges retain main, PR 78 target admission and PR 67 input
delivery; those gates must merge first. The UI conflict resolution retains
Automation navigation, exact reviewed Catalog/package binding and the current
Controller/session epoch guards. No second downloader, Skill registry, approval
system or execution authority is introduced.

Skill, Extension, Control Plane and Automation regression: **572 passed,
17 skipped** (308.54 s). Python 3.10 Skill/Extension and focused Skill Control
Plane regression: **303 passed, 17 skipped** (42.38 s). Desktop lint/typecheck,
**223 tests** and build pass. All 12 existing repository checks pass. Scanner
results are **0 HIGH / 5 MEDIUM**: three existing public Ray image-layout paths
and two explicit private-IP rejection vectors in `test_remote_catalog.py`.
The fake addresses test all-private and mixed-public/private DNS denial; no
credential or actual private deployment address is recorded. Assertions and
scanner rules are unchanged, and the two additional findings remain visible.

Source `b4ea288` also passed an owned browser/HTTP/TLS acceptance: add Catalog,
review exact source/version/digest, install, verify CAS, load instructions,
disable, reject disabled reads, enable and uninstall. Three actual child-server
TLS acquisitions occurred through the test's explicit DNS/route seam. The
source Chromium page had no script errors or mobile overflow, and no execution
Grant was issued. Browser and owned servers/threads were cleaned up. This
private driver has **1 passed, 2 marker-configuration warnings** (6.59 s), not
hidden product failures. Fake signed human identity and local TLS do not
qualify a real IdP, public publisher, installed APEIR.exe or executable Skill.
Instruction loading remains distinct from execution. Exact-source PR/platform
and resulting-main CI remain required; overall product status stays PARTIAL.

### Bounded Relay stop and receive backpressure — 2026-10-16

The updated target candidate `f0f43f1` passed Core/Desktop/Security and Linux,
but Multi-Arch `38927399914` retains Windows **1 failed, 4830 passed,
60 skipped, 272 deselected, 4 warnings** (1986.70 s). The prior held-observation
case passed. This failure is the original Artifact/lease/stop test's unchanged
two-second shutdown bound, waiting for WebSocket close completion.

**REUSE / FIX** the existing Node Relay, protocol flow control, durable sequence
guard and original Node journal. Two controlled real-loopback tests reproduce
idle receive waiting beyond stop and a full receive queue hiding the peer's
close frame: **2 failed** (62.72 s). An independent accepted-main idle probe has
**1 failed** (2.78 s). No test or production deadline was enlarged. Stop now
wakes idle receive; closure drains raw frames solely to finish the existing
handshake. Buffered commands are not decoded, acknowledged or executed, and
Controller pending Work remains available for original-journal reconciliation.

The first implementation cancelled an already admitted result send; combined
regression retained **1 failed, 398 passed** (131.55 s) in the existing revocation
test. That prototype is rejected. Requested stop now preserves an active
message's original completion/publication; explicit transport cancellation
retains existing journal ownership and drains durable writes. The unmodified
revocation/result-denial check passes. Final Node/Reality/target regression:
**399 passed** (126.25 s); Python 3.10 shutdown/I/O/reconciliation selection:
**57 passed** (5.96 s). Ten focused original-control, revocation and stop cases
pass (1.67 s), and eight shutdown cases additionally require clean close code,
no remaining Relay tasks, no new Node execution and retained pending Work
(1.42 s). Counts overlap and are not summed.

The ordinary PID64, memory/network/filesystem, identity, signing, replay and
effect-verification boundaries are unchanged. This proves the controlled stop
and queue mechanism, not every historical Windows failure or physical/WAN
qualification. Issues 4/8 remain open. Raw failed CI and prototype logs remain
outside source control. Updated-source cross-platform CI is required.

### Passive snapshot state creation and unresolved HTTP timing — 2026-10-16

Catalog source `2201afd` Multi-Arch `38928853921` retains Windows **1 failed,
5004 passed, 131 skipped, 290 deselected, 4 warnings** (2257.29 s). The exact
package-locator nonce case timed out during its prerequisite full Operations
HTTP snapshot, before its nonce rejection assertion. This is separate from
Relay close; neither the nonce assertion nor its five-second request bound is
removed. The owned HTTP fixture now dumps only thread code locations on timeout,
without frame locals, to distinguish backend work from transport delay.

**REUSE / FIX** the existing Operations projection and canonical owners. A
deterministic before-test has **1 failed**: an empty-state snapshot initializes
Session/Workflow databases and the Distributed Work lock. Passive reads now
skip absent stores and invoke the original owners when state exists. Empty or
nonregular persisted files yield component UNKNOWN and degraded health without
repair. An owner-created Session, Workflow and Work become visible on the same
projection's next read; no cache or second authority is introduced. The updated
Operations selection has **30 passed** (2.91 s), including six damaged-state
cases; Operations/remote-HTTP selection **62 passed** (26.76 s), and composed
Control Plane/Skill/Extension regression **465 passed, 17 skipped** (51.45 s).

The prespecified shared-Linux cold-empty-workspace comparison uses A15/B15/B15/A15,
30 samples per variant, warm imports and the same fake health-loader contract;
HTTP/auth/startup are excluded. Before p50/p95/p99 is
**9.160/11.373/14.743 ms**, candidate **11.565/16.733/19.643 ms**; aggregate CPU
is **0.286/0.332 seconds**. Candidate timings are worse in this measurement,
not an improvement claim. With 30 shared-host samples p99 is the sample maximum,
not a reliable population-tail estimate. The reproducible change is zero
execution-state files created by reads, versus three before. Raw samples and
both source modules remain retained privately. This corrects read-side mutation;
it does not prove or resolve the Windows HTTP timeout cause. Fresh same-bound
cross-platform CI remains required; no retry or increased deadline is added.

### Workspace input candidate ARM64 comparator qualification failure

Candidate `df36290` Multi-Arch run `38934932374` failed Linux ARM64 job
`117087935836`: **1 failed, 4942 passed, 59 skipped, 290 deselected**
(641.37s); Windows and Linux amd64 passed. The original failure log is retained
in the private qualification evidence. The existing within-tolerance comparator
unit test compared two separately timed near-empty tasks. The runner records
integer milliseconds; the observed 0ms baseline and 1ms candidate correctly
triggered BLOCK, contradicting the fixture's WARN expectation. Accepted main
`629b13f` contains this same timing-dependent test.

The comparator unit fixture now supplies explicit 100ms/105ms inputs, retaining
its WARN/no-regression assertions. A separate explicit 0ms/1ms regression keeps
the original observed case BLOCK. Production timing, comparator tolerances,
performance gates, Node assertions and timeouts are unchanged. This is test
input determinism, not a performance improvement or a Windows recovery fix.
Exact-source CI remains required before integration.

### Governance SQLite connection lifetime and timing — 2026-10-21

**REUSE** GovernanceStore, its original SQLite transactions, logger, HTTP/Skill
owners and security checks. **FIX** connection cleanup after failed setup;
**EXTEND** safe phase diagnostics. This creates no store, pool, authority,
scheduler or event system. Kernel, component lock, busy timeout, WAL,
synchronous durability, approval/revocation checks and effect retry rules stay
unchanged.

Main `e3cd2a2` performs three setup PRAGMAs before its cleanup `try/finally`.
Injecting an error in each PRAGMA while retaining the actual SQLite connection
reproduces **3 failed tests (0.18s)**: transaction bodies are denied, but the
connections remain open. The same connection owner now covers connect, setup,
commit/rollback and close with cleanup. Twelve lifecycle contracts pass
**12 tests (0.09s)**, including readonly failure, failed commit rollback,
post-commit close failure without body replay, and diagnostic privacy.

The existing logger warns only when a local monotonic connect/configure/commit/
rollback/close phase takes at least one second. Messages contain only fixed
phase names, elapsed time and readonly state, with normal logging thread fields;
they do not include paths, SQL, row values or exception text. This threshold is
observability, not a deadline change. A committed fact followed by close failure
remains readable as original evidence; no retry is added.

Affected Governance/ControlPlane/Skill/SQLite/path-binding regression initially
has **573 passed,1 setup error (51.59s)**: the owned TLS fixture saw its port file
after creation but before its port number was written. The child now writes a
temporary file and atomically publishes readiness; the original five-second
deadline and assertions remain. The final affected scope has **574 passed
(50.76s)**. This fixture correction is not a Runtime network timing fix.

Same-host A/B/B/A measurement of 1000 durable short transactions per variant
records p50/p95/p99 **0.1216/0.3105/0.5357ms** before and
**0.1459/0.3241/0.5431ms** after; CPU **0.1632s to0.1801s**. Every database has
500 expected rows per block, integrity_check=ok, WAL, foreign_keys=1 and
synchronous=2. This measures diagnostic overhead on a shared Linux host, not a
speedup, Windows result, whole-Runtime benchmark or Token saving.

[Issue88](https://github.com/untrod/apeir/issues/88) remains open. Windows
Python3.11 run39453407331 captured a Skill HTTP timeout during commit;
Python3.12 run39541361099 captured another during close after the completion
audit. The deterministic setup leak is not yet proven to cause either timeout.
Full regression and exact-source/current-main platform CI remain required;
the original five-second HTTP assertion and durable audit are preserved.


### Windows Skill HTTP phase investigation — 2026-10-21

The SQLite lifecycle repair is independent of the unresolved HTTP deadline.
Source `cffb64d` Multi-Arch run [39635213958](https://github.com/untrod/apeir/actions/runs/39635213958)
recorded Windows **1 failed,5026 passed,131 skipped,302 deselected,4 warnings
(2353.08s)**. Initial installation in the revoked-update case times out before
fault injection. Safe SQLite diagnostics show commit **1562ms**; the handler
has progressed to opening the CAS receipt append file at the client timeout.
This does not show that receipt open alone consumed five seconds, nor prove
SQLite setup/close is the sole cause. Linux amd64/ARM64 pass; the issue stays OPEN.

REUSE existing Core CI and owned HTTP/TLS tests; EXTEND only fixture diagnostics.
Bounded snapshots retain phase names, request ordinals, elapsed milliseconds and
completion flags, never arguments, paths, SQL, results or exception messages.
Completed entries are bounded at128; active phases remain distinguishable.
Nested timings overlap and must not be added as exclusive costs. Existing effects,
exceptions, human/nonce admission and five-second HTTP assertions are unchanged.
Related owned HTTP/TLS/privacy cases: **33 passed (23.48s)**; existing conservative
CI-scope cases: **17 passed**. The combined repository/SQLite/owned HTTP selection
has **321 passed (23.42s)**; these counts overlap. A same-host ABBA trivial-boundary
probe (2000 samples per variant) measures diagnostic p50/p95/p99 overhead from
0.120/0.160/0.180µs to1.111/1.172/1.383µs. This is instrumentation cost, not a
product speedup or Windows/HTTP latency estimate. A real local fixture trace has25 completed phase
records for12 HTTP requests; it is neither Windows qualification nor a speedup.

The optional `windows-skill-http` input on existing Core CI selects a separately
named diagnostic. Default dispatch, PR, main and release selection are unchanged.
Diagnostic-only skipped jobs also receive different names: GitHub treats skipped
checks as passing, so they must never replace `Core gate` or platform evidence.
Diagnostics use the failing Windows/Python3.11 Tier1 dependency scope and original
tests. Their result cannot qualify full Core, fix Issue #88 or certify release.
The workflow passes official actionlint1.7.12 validation. Frozen Kernel, component
lock, durability, timeouts and retry policy are unchanged.


The first actual [Windows diagnostic39689950082](https://github.com/untrod/apeir/actions/runs/39689950082)
on `154c110` passed **33 tests (62.42s)**. Its32 fixture snapshots contain200
completed HTTP requests (mixed endpoints): observed p50/p95/p99 **47/625/641ms**,
maximum **891ms**, with no incomplete phases. This fresh subset does not reproduce
the full-suite deadline failure and cannot close Issue #88. Python3.11 Windows
`monotonic()` quantizes some short phases to0ms; those values are below the timer
resolution, not zero I/O cost. The fixture now uses high-resolution local
`perf_counter()` for phase intervals. Original deadlines/SQLite runtime diagnostics
stay unchanged. Related Linux owned HTTP/TLS/privacy cases still have **33 passed
(23.43s)**; new Windows precision evidence and full-suite qualification are separate.


### Governance read-only connection admission — 2026-10-21

FIX the existing SQLite connection owner: a read-only connection no longer
initializes parent directories. An absent/removed database still raises the
original SQLite failure without recreating its workspace; normal existing reads
retain original rows and need no directory-creation permission. Write-path
initialization, transaction/rollback/close behavior, WAL and durability remain
unchanged. This does not claim SQLite has no internal WAL sidecar activity.

Both original filesystem contracts failed before the correction (**2 failed,
12 deselected,0.14s**). Related Governance/Control Plane/Skill/permission cases
now have **555 passed (45.91s)**; collection confirms555 distinct cases. These
counts overlap earlier evidence. No authority, retry, timeout or Kernel change.
The explicit Windows diagnostic now also includes these existing lifecycle cases.

A paired same-host, same-database Linux ABBA probe has5000 samples per variant:
p50/p95/p99 **120.291/257.848/411.920µs → 109.155/245.329/387.744µs**;
thread CPU **0.7362s → 0.6737s**. Every lookup returns the same original row;
integrity remains `ok`, row count1. This removes redundant directory operations
in the read helper, not evidence of a whole-Runtime or Windows/HTTP speedup.
It does not establish a correction for the unresolved full-suite Issue #88.


### Human admission timing within the existing Skill HTTP diagnostic — 2026-10-22

REUSE the existing owned HTTP/TLS fixture, `HumanSessionAuth`, nonce admission
and bounded phase recorder. EXTEND only its instrumentation to authentication,
nonce issuance and nonce consumption. Earlier Windows evidence has total HTTP
2784.6ms but business admission37.1ms; attributing the remainder to SQLite close
or CAS would be unsupported. The existing SQLite phase warnings and new nested
method spans can now distinguish those admission stages without changing them.
Fixed phase names, local request ordinals, elapsed milliseconds and completion
flags remain the only retained fields. Cookies, nonces, identities, arguments,
results and exception strings are excluded. Nested timings overlap; setup calls
outside HTTP have their own ordinal and are not HTTP request latency.

A concurrent positive/denied contract verifies separate request correlation,
original return/exception behavior, exactly one call per operation and exclusion
of fake private cookie/nonce material. Existing owned HTTP/TLS/lifecycle/privacy
regression: **53 passed (25.70s)**. A real local denied-request trace observes
both authentication and nonce-admission spans; no additional authority, SQL,
retry, timeout, durability setting, storage owner or production behavior changes.
This diagnostic does not itself fix or close Issue #88. Windows measurements and
resulting-main qualification remain separate; a passing isolated run cannot
replace the original full-suite failure evidence.

### Pre-installation audit and original-evidence repair, 2026-10-18

Requeried main `e3cd2a20d75a711108285533cd83014bf6f9b69d`, remote heads,
PRs, open Issues, workflows, releases, component lock and available toolchains.
Main's four workflows and PR #81's five exact-source workflow runs are successful;
GitHub still reports the PR blocked by three stale required check names. The
administration endpoint returns 403. No protection change, administrator bypass,
new tag or Release is performed. The 31 published tags and frozen Kernel remain
untouched. The root checkout remains on main; candidate work is isolated.

| Existing surface | Classification | Actual entry / remaining boundary |
| --- | --- | --- |
| Work, AgentSession, Workflow, Governance, CAS, EventStream | REUSE | Existing CLI/HTTP/SDK and durable owners; no competing state system. |
| MCP Runtime | EXTEND | PR #81 official SDK stdio → authenticated Runtime HTTP, five tools and original human approval. Not yet main; direct official Codex MCP evidence is not a model turn. |
| Prepared Work model input | FIX | A 96,000-character string slice could corrupt JSON and omit Goal constraints/schema. Complete compacted input now either dispatches whole or pauses the original Work before Provider invocation. |
| Signed Node result recovery | FIX | Re-signing the same terminal journal could overwrite the envelope digest already bound to VERIFIED Work. Preserve first evidence, ACK canonical duplicates, reject conflicts; terminal stop control metadata is distinct from execution evidence. |
| Reviewed Skill acquisition | REUSE | Main has original human-reviewed local/HTTPS catalog/Extension/CAS paths. Correct the stale example claim that all remote acquisition is rejected. Instruction loading is not executable Skill qualification. |
| Model Center | FIX / EXTEND | The live HTTP route is the Control Plane adapter over the active Gateway registry, not the earlier same-path ModelCenter handler. Do not infer measured health from declared availability or invent zero price/latency when benchmark evidence is absent. Existing REST membership and canonical enabled-only Desktop selection remain the owners. |
| Context / Workbench | EXTEND | Existing saved-file admission, editor/proposals and original Work paths. Full authenticated Harness, all native filesystem paths and actual cloud/local model tasks require independent qualification. |
| Parallel model invocation | FIX | Bind child dispatch to the remaining aggregate deadline and honor the requested minimum successful responses. Retain partial output/cost evidence without calling it aggregate success. |
| Terminal / Git / Environment | EXTEND | Existing process sessions, bounded profiles, read-only sandboxed Git and Environment service. Do not label fixed profiles as a qualified full PTY or bypass missing strict isolation. |
| Automation | EXTEND | Existing manual/one-shot simulated consumer; recurring real-node health work, general executable Skills and Recorder remain missing. |
| Embedded / Network / Scientific | EXTEND | Existing signed Node/Device, Serial host contracts and numerical reference. Physical/WAN and strict-isolation computation/report gates remain pending or blocked. |
| Native Windows installation | FIX | Actual verifier still fails on missing locked `nousd` bytes; worker also absent. No local Rust/MSVC/PowerShell/Windows SDK toolchain. A separate PR #84 extends the existing Desktop workflow with an opt-in frozen-source Windows rebuild diagnostic; no packaging, installation or hash match is implied by compiling. A different rebuild hash cannot replace the lock. |
| Additional Harnesses / protocols / general engines | DEFER | See the dated official-source/license adoption table in the existing Provider contract; no copied Harness, scheduler, inference engine or workflow engine. |

Defect evidence is retained privately outside source. Work overflow reproduction
against accepted main: **2 failed, 1 passed** (0.38 s); the old path dispatched
truncated input instead of rejecting it. Original Goal/constraint overflow,
complete Unicode JSON/tail constraints, the exact inclusive bound and durable
WAITING_USER/no-Provider/no-tool behavior now have regressions. Prepared input
character count is not measured token usage; no cost-saving percentage is claimed.

Node duplicate-terminal reproduction: **5 failed, 2 passed**. The first fixture
omitted a capability requirement and was corrected before the defect baseline;
those setup failures are retained separately. Initial preservation exposed a real
compatibility failure in the existing reconnect test (pending retry not retired),
which was corrected rather than skipped. Canonical comparison distinguishes bool,
integer and float payload changes. Tests cover signed real-socket reconnect,
conflicting result/binding/receipt/sender/key, persisted original envelope/CAS
binding, pending queue cleanup and both ALREADY_TERMINAL stop/result orderings.
No timeout increase, execution replay or weaker MATCH assertion is introduced.
This proves a duplicate-envelope defect, not the historical cause of Issues
#4/#8/#82; those remain open until their original failures are explained.

Pre-composition checks: **275 Node tests passed**, **56 Work tests passed**.
Original HTTP approval/MATCH selection: **2 passed**. Initial preservation's
Reality/Automation selection: **169 passed**; this earlier patch scope is not
presented as final combined qualification. Counts overlap. The candidate reuses
PR #81 through a normal merge preserving its exact accepted source SHA; its
own final combined regression, source CI and protected main integration remain
required before claiming integration. Original Kernel, component lock, PID64,
credential/sandbox boundaries and native release rules are unchanged.

The initial direct ModelCenter DTO probe showed missing entity aliases, but a
real authenticated HTTP round trip exposed the existing route override. That
probe must **not** be reported as proof that the public model list loses every
model. The actual Control Plane adapter already supplies both identities. Its
missing benchmark measurements were nevertheless rendered as zero and declared
availability as measured health; review follows the actual HTTP producer through
Desktop consumption. The legacy ModelCenter action DTO remains unchanged;
identity regressions qualify the actual public HTTP projection instead.
Protected HTTP tests now use the real active Gateway and persisted registry,
including unauthenticated denial and reopen/removal. Missing or invalid benchmark
values remain null, unobserved health is UNKNOWN, and only canonical enabled
models are offered. The existing central redactor permits only the exact nullable
finite nonnegative numeric model-price field; strings, credentials, bools,
negative/nonfinite values and other sensitive keys remain redacted. Complete
Desktop REST loading follows bounded pagination and rejects duplicates, changed
totals or Controller changes before publishing membership. Positive zero is
preserved as evidence.

Focused real model/API/UI checks include retained pre-fix failures; these are
software fixtures and authenticated loopback HTTP, not actual model inference.
Pagination regression: **5 failed,12 passed** before, **17 passed** after.
Current full Desktop: **40 files,239 tests passed**, with lint, typecheck and Vite
build passing. Shared-redactor Governance/credential/usage regression: **264
passed**. Full composed Python and exact-source CI remain required. A proposed
unnecessary legacy DTO alias also exposed that file's original formatting failure
in source0a75af7 Security CI. The alias is withdrawn instead of reformatting the
unrelated legacy implementation or weakening the changed-file formatter. The
failed run and baseline-format evidence are retained.

The pre-final bare-host full run recorded **5540 passed,58 skipped,3 failed**
(719.21s). One existing Provider catalog test incorrectly equated enabled with
healthy. Its corrected contract now asserts UNKNOWN and absent price/latency,
then requires an explicitly recorded health result before reporting healthy;
the existing identity/state assertions remain. The other two original process
cleanup assertions found zombies adopted by this container's non-reaping PID1
`tail`, a previously documented unsupported environment. No process assertion,
timeout or Kernel code changes. The same unchanged ProcessSession/startup scope
under a process-local Linux child reaper passes **22 tests**; four adopted
children were reaped and no owned children remain. This is initialized test
environment evidence, not a new product sandbox or Scientific qualification.
The bare-host failures remain retained separately from initialized/final CI.

Initialized full regression at source22ceee8: **5545 passed,58 skipped**
(691.76s);18 adopted children reaped, no owned children remaining. A subsequent
targeted audit nevertheless proved a missing parallel-billing case: original
CostController receipts correctly retained uncertain charges, while parallel
results/events showed zero or omitted failed-child cost and could dispatch a
second budgeted candidate. Controlled method-only22ceee8 reproduction against
unchanged accounting semantics: **2 failed**; the original parent-cancel test
also fails while its event loop remains alive. No paid Provider calls occurred.

The same CostController now supplies an exact-request, transaction-consistent
read of all original attempts/reservations, with binding validation and additive
request-ID indexes. Gateway projects those facts on failure/cancellation, retains
UNKNOWN and stops further budgeted admission; proven non-dispatch stays zero.
Parent cancellation joins original children and retains unsettled accounting.
No alternate ledger, credential authority, retry or execution store is added.
Focused accounting/Gateway **94 passed**; broader model/Work/Context/Control
Plane/Provider **1312 passed** (69.35s), Python3.11 Model Runtime **314 passed**
(3.20s). Counts overlap. Final composed source qualification remains required.
These changes do not qualify durable replay of a parent fan-out across restart.

An additional policy-boundary probe retained **22 failed,9 passed** before the
fix: non-finite/ambiguous budgets were accepted and a zero aggregate budget
still dispatched the first Provider call. Parallel limits now validate numeric
types/finiteness and reject zero-budget work before any child dispatch. Model
Runtime regression after this correction: **345 passed** on each of Python3.12
(2.76s) and Python3.11 (3.02s). These are software/fake-Provider tests, not billed
requests or a cost benchmark. Positive aggregate limits stop further admission;
they cannot retroactively prevent charges for concurrent already-dispatched
requests. Original CostController per-request/daily reservations remain separate.

Independent review then reproduced a child `CancelledError` escaping through the
parent-cancellation handler although the caller had not cancelled. Two retained
regressions fail before correction. The Gateway now accounts for that failed
child and preserves the existing fan-out/budget rules; actual parent cancellation
still joins its children. Model Runtime **347 passed** on Python3.12 and
Python3.11. No authority leak, repeated effect, orphan or paid incident was
demonstrated by this in-memory/temporary-ledger case.

Candidate28aa586 Multi-Arch run39119424955 failed the same Gateway fan-out test
on Linux AMD64 and ARM64/Python3.11. Original raw logs are retained. A controlled
75ms preparation stall reproduces the old assumption that zero-delay mock
Providers necessarily finish within a whole-call50ms limit; the precise CI
scheduling cause remains UNKNOWN. Ordering/concurrency are now event-coordinated
and the separate pending-cancellation test retains50ms. Independent controlled
regressions prove two product defects: an exhausted parallel deadline could still
dispatch a child with the original1s limit, and one response could report
`successful=True` despite `min_successes=2`. Child deadlines and the result
predicate now enforce those original policy inputs. Partial responses, original
request bindings and usage are retained; no timeout, retry or authority is
expanded. Both Python3.11 and3.12 focused Model Runtime suites pass274 tests at
that patch scope. Final composed checks and cross-platform CI remain required.

The PR #84 opt-in native diagnostic was actually exercised at Distribution
424429c/run39121517509 on Windows Server2025/Rust1.99.1. Both frozen Kernel
release components built in1m49s, both PE machines are0x8664 and tracked Kernel
source stayed clean. **Both hashes differ from the original lock**, so the
diagnostic correctly fails and native integrity remains BLOCKED. The retained
six-file logs/report artifact12134755674 has ZIP SHA-256
`f35a283b49584d8a81e2effb99585a718f1a80ee8d544788479a9d684e8baf8e`,
independently downloaded and checked. Exact expected/actual hashes are in PR #84.
No component is staged/relocked, no mismatched EXE is offered for installation,
and no installer, NKI runtime or Windows10 lifecycle qualification is claimed.


### Linux ProcessSession descendant reaping — 2026-10-21

**REUSE / FIX** the existing Distribution ProcessSandboxHost and durable
ProcessSession projection. On main `e3cd2a2`, the original
`test_child_process_is_cleaned_up_with_parent` and
`test_natural_parent_exit_does_not_leave_child` both fail in this container
with PID1 `tail -f /dev/null`. The original child creation tokens remain in
`/proc` because dead children are zombies adopted by a non-reaping PID1.
The same pair fails on `ae75148` and `d5b20ef`; no assertion or timeout changed.

The isolated Linux host now enables `PR_SET_CHILD_SUBREAPER` before workload
spawn, then reaps only adopted children in the original workload process group
after the existing termination signals. Startup without that Linux primitive
fails closed before spawning. Unconfirmed reaping cannot publish terminal
success. The exception path also waits for the original process and cleans its
group before recording recovery; it never launches a replacement command.
The frozen Rust Kernel, NKI, component lock, Governance and sandbox limits are
unchanged. The Python module's historical `nous_runtime.kernel` package name
does not change its Distribution runtime-service execution scope.

The original failing pair passes **2 tests (1.54s)** in the same bare-PID1
environment. ProcessSession/startup/reaping regression passes **29 tests
(27.00s)** before adding the real post-spawn persistence-failure case; the final
new reaping suite passes **8 tests (2.25s)**, including three-generation process
exit/terminate/kill, recovery after host failure, unavailable startup control,
group-only waiting, and fail-closed wait errors/timeouts. Counts overlap.
Full regression and source/main CI remain required. Container init is still
needed for detached host processes and arbitrary process groups outside this
bounded ownership contract; no complete PTY or isolation qualification is added.

Source `525e7ec` full local regression is **5453 passed,58 skipped,4 warnings
(693.02s)**. Its four-platform Core run
[39541361099](https://github.com/untrod/apeir/actions/runs/39541361099) passes both
Linux versions, but macOS has **1 failed,5414 passed,62 skipped (999.73s)**:
the new startup-denial test blocked the `ps` subprocess used to observe the
helper's own creation token. The test now acquires that actual token before
installing its strict no-workload-spawn guard; the original guard and
RECOVERY_REQUIRED assertions remain unchanged. Final focused regression:
**30 passed (27.34s)**. New exact-source macOS CI remains required.

Windows in that same run has **1 failed,5320 passed,156 skipped (2034.45s)**:
an initial remote Skill install exceeds its unchanged five-second HTTP deadline.
The captured request-handler stack is GovernanceStore connection close at line42,
after `skill.management.completed`, rather than the commit at line36 seen in
the earlier Python3.11 failure. This is additional evidence for
[Issue88](https://github.com/untrod/apeir/issues/88), not a confirmed reaper
regression or proof of its timing cause. No timeout, durability, Skill authority
or assertion is weakened and the failed run remains retained.

After normal synchronization with accepted MCP main `ad773890` on 2026-10-23,
the documentation conflict retains both original evidence sections. Source
ProcessSession/startup/reaping checks pass **30 tests (26.20s)**; related terminal,
approval, sensitive-output, process-sandbox, MCP, Work submission and repository
checks pass **390 tests,1 skipped (19.90s)**. An initialized Linux test harness
reaped12 adopted test children and confirmed no remaining children; this is
not qualification of arbitrary escaped process groups or native installation.
Ruff, changed-file formatting, compile,235-file local links, document/comment/
identity/metadata/version audits and diff checks pass. Security retains0 HIGH
and5 existing MEDIUM findings. Exact synchronized-source CI is separate; main
integration still requires verified repository protection, with no merge probe.

### Scoped MCP / original Work submission software qualification

Audit classification: **REUSE** existing MCP SDK, authenticated Runtime HTTP,
Governance/PermissionEngine, OperationsPlane, DeviceRegistry, WorkSupervisor,
DistributedWorkStore, checkpoint store, EventStream and redaction; **EXTEND** the
existing extension CLI with a fixed stdio bridge and five tool adapters;
**FIX** authenticated original Work submission/retry and concurrent cold SQLite
initialization; **DEFER** complete Codex Harness, remote human identity, native
installation, physical effects and unqualified Work Harness model disclosure.
No second authority, Work/Artifact registry, scheduler, verifier or agent is added.

Accepted-main `629b13f` ignored a supplied idempotency key: an actual HTTP test
with original canonical human approval produced two Runs (1 failed1.21s).
A test-only first fixture omitted approval and was correctly denied; it is not
reported as an execution reproduction. The corrected fixture explicitly approves
through the existing local-human boundary. A later combined run exposed cold
SQLite `PRAGMA journal_mode=WAL` contention (1 failed220 passed19.20s). Both raw
failure logs remain private. The canonical store now serializes initialization
with existing file locking and closes connections on initialization errors.
Ordinary 30-second SQLite limits, checksum checks and retention assertions remain.

After the correction, MCP/Work/Agent regressions: **278 passed19.44s**.
Broader Extension/Work/Agent/Governance/API regressions: **666 passed17 skipped
30.79s**. Public CLI stdio/HTTP and original-submission suite, including two actual
Runtime processes sharing the cold workspace: **38 passed13.33s**. Counts overlap.
The model deliberator in these tests is an explicit fixture; no paid-provider,
physical or native Desktop qualification is claimed. Exact final source and
resulting-main CI are required before integration.

Official Codex 0.163.0 App Server (native SHA-256
`399ff69c431c066e40de318fba45c2b07f45a76b19939d247ee4828fc70c4215`)
was also run against the real Runtime HTTP/MCP bridge: initialize, ephemeral
read-only thread start, APEIR tool discovery, canonical Node list, original
Distributed Work status, and new Work requiring human approval. Direct protocol
qualification: **1 passed5.74s**; zero model Turns, no Work execution and no
remaining owned process-group members. Private report
`apeir-codex-mcp-direct-nkig8sul/report.json` retains calls, timings, module hash
and cleanup without account identifiers or credentials. A separate metadata probe
successfully read configured-account presence and five model descriptors.
Configured authentication is not complete Harness qualification: generated
0.163.0 schemas do not expose the scoped filesystem contract described by newer
web documentation; disabling shell does not disable all native file tools.
Do not start a model Turn before actual credential/filesystem isolation and
approval mapping are qualified. This work does not change Kernel, component
locks, PID64, sandbox boundaries, published tags or production-release status.

Current additional admission/leakage checks: **807 passed17 skipped37.94s**
(Extension/Work/Agent/Governance/public API freeze/Control Plane). A controlled
scope change during original API admission must prevent Work creation; the
initial unpublished prototype failed that assertion (1 failed1.32s), then gained
an immediate pre-submit scope recheck. Sensitive credential registration stays
at the new authenticated MCP execution boundary. A broader prototype registered
all legacy API fixture tokens globally and collided with the six-character
fixture value used in SecretHandle field names (1 failed32 setup errors774 passed);
it is rejected without changing the redactor, legacy fixtures or their assertions.
Raw failures remain separate from passing results. This is scoped software
qualification; final composed source CI and actual-provider Gates remain separate.

Composed candidate `08f2416` (including all queued integration dependencies):
**1195 passed,19 skipped (76.91s)** across Extension/Work/Agent/Governance,
Control Plane/Skill/Environment/Artifact/benchmark, API freeze and focused Node
shutdown/reconciliation. Python3.10: **289 passed (24.86s)**. Gateway accounting,
cost and Context combination: **560 passed (19.60s)**. These overlapping scopes
are not added into a synthetic total.

A further real-socket cancellation test fails the old blocking-thread bridge
(**1 failed,7.08s**): cancelling the caller leaves its HTTP request running.
The bridge now uses the MCP dependency's async HTTP client, a whole-call deadline,
explicit no-redirect/no-retry and bounded uncompressed responses. Cancellation
closes its own transport, not the original Runtime Work. The corrected focused
CLI/MCP/submission set, with invalid keys rejected before requesting approval,
is **50 passed (17.86s)**. This is correctness/resource ownership, not a measured
speed improvement. Official Codex direct-MCP qualification against that async
code: **1 passed (9.66s)**, report `apeir-codex-mcp-direct-duw7n7vt/report.json`,
no model Turns and clean owned-process exit. Final composed CI remains required.

Installed external MCP consumer: source `5bd50e5`, independently built wheel
SHA-256 `d0ba3843f706b1338bc36bc0609bf6ca359e4f857f5eda86deb565cf139ad2b5`,
installed with the existing MCP extra into a new isolated venv. From an empty
working directory outside the checkout, public `apeir extension serve-mcp`
initialized/discovered five described tools, read actual Node and Distributed
Work state, and stopped Work submission at canonical human approval. **1 passed
(4.03s)**; installed module resolved under venv site-packages, no model call,
raw test credential leak or remaining owned process. The protected consumer
manifest/report retains exact wheel/source/cleanup evidence. This is a source
wheel, not native Windows installation or production supply-chain qualification.

The separate Windows Automation failure at source97c9a8/run38939446275 is now
[Issue82](https://github.com/untrod/apeir/issues/82). Its missing verdict must not
be promoted to MATCH. Source5bd50e5 Linux Automation: **114 passed (195.36s)**;
this does not identify or resolve the Windows cause. The same original assertion
now emits the full failed projection and additionally checks original Work/effect
count, without another attempt, more delay or a larger timeout. Original failure
logs and the failed run remain retained; general reliability/product status is
not upgraded on the strength of another passing candidate.


### Distribution compatibility migration atomicity and Windows startup follow-up

MCP source5bd50e5 manual full Core run38944737418: Linux3.12, Linux3.10 and
macOS3.12 passed; Windows3.12 job117120890834 aborted at the unchanged60-second
pytest limit during a Context fixture's legacy Capability schema migration,
before MCP tests. The stack is retained. This is not relabelled a passed Windows
run, and no claim is made that the Automation failure in Issue82 has the same cause.

Audit identified a separate deterministic defect in Distribution's existing
Python compatibility database (`remote_terminal/nous_core/db.py`): executescript
committed each DDL before the version record; an injected later SQL error left
a partial table behind (**1 failed0.08s**). Existing file migrations now each
own one transaction, including their version record, and inline bootstrap is
atomic as well. The old connection manager still commits/rolls back/closes;
WAL, foreign keys, FULL synchronization and5-second busy timeout are unchanged.
No migration SQL, native Rust Kernel repository/revision, NKI contract,
`nous_runtime/kernel`, component lock or authority model is modified. Formatting
of the touched legacy file preserves the measured implementation AST.

The existing Pack test also assumed another test had imported its registry and
leaked NOUS_DATA_DIR globally. Focused qualification exposed **1 failed71 passed**;
it now explicitly imports the same owner and restores its temporary environment.
No assertion was removed. Migrations/Context guard/API admission: **72 passed
3.34s**. Wider Extension/Work/Agent/Governance/Context/migrations/Environment/
Artifact/API freeze: **1356 passed19 skipped56.51s**. Python3.10 public MCP,
submission,CLI,migrations and Context guard: **114 passed20.85s**. Counts overlap.

Controlled cold-schema A12/B12/B12/A12,24 fresh databases per variant on one CPU
of the shared Linux host: before p50/p95/p99 **51.455/56.662/62.573ms**, CPU
**0.46595s**; atomic after **30.883/37.761/42.755ms**, CPU **0.34982s**.
All databases pass integrity_check and contain all14 version records. Private
`apeir-legacy-migration-ab-t5xxj7g7/report.json` retains raw samples and module
hash/AST equivalence. Small-sample p99 is the observed maximum, not a stable
production tail estimate. This does not establish Windows timeout root cause,
Node end-to-end improvement, model cost savings or physical qualification.
Exact updated source must run fresh full Core/Multi-Arch before integration.

### Windows negative-path follow-up — 2026-10-19

Candidate `0cb8257` retains two actual Windows failures. Core run39146298658
has **1 failed,5464 passed,149 skipped**: the UNKNOWN independent-observation
case has no persisted verdict, while the original mutation is VERIFIED and its
effect count is one. Multi-Arch run39146301822 has **1 failed,5171 passed,
131 skipped,292 deselected**: an HTTP Skill acquisition negative case times out.
Its retained thread stack is preparing the Extension SBOM before the final
publication check. Neither run is PASS; Issues4/8/82 remain open.

Review of that Skill path proves avoidable preparation after the download has
already invalidated the original authority or catalog review. Strengthening the
existing HTTP/TLS negative cases to require no install preparation gives
**6 failed,1 passed** before correction. The same existing Skill Registry now
revalidates under its existing state lock immediately after acquisition, before
CAS/Extension/SBOM preparation, and retains the final publication callback for
later revocation/races. Skill/HTTP-TLS/Extension regression: **309 passed,
17 skipped (46.93s)**. No deadline, TLS, permission or supply-chain check changes.
This establishes the unnecessary-preparation defect; it does not prove every
cause of the Windows filesystem stall or claim measured latency improvement.

The independent-observation test retains its original verdict assertion and now
reports bounded/redacted run errors, observation Work states and Node journal
phases only when the verdict is missing. It does not dump output, credentials or
signed envelopes, retry the mutation, infer a verdict or extend a timeout. The
Windows cause remains unresolved pending exact-source CI evidence. Successful
Linux tests or simulated effect counts cannot qualify Windows recovery, a real
Provider, physical hardware or native installation.

The same follow-up also checks ordinary workspace reads and Skill retention,
instead of inferring safety from registered APIs. Existing path admission was
separate from pathname reopening in Workbench, Chat and Proposal observations.
Nine controlled leaf/ancestor/hardlink replacement cases returned an owned
benign private marker or its digest before correction; all nine fail closed
after reusing one bounded reader in the existing isolation module. Root
replacement, inode changes, descriptor cleanup and unavailable safe-open APIs
are covered. Existing single-link/empty-file/internal-alias compatibility and
selected-input hash, budget and transfer admission remain separate. Workspace/
Proposal/selected-input integration: **182 passed,1 skipped (21.08s)** on
Python3.12; related Python3.11 scope: **115 passed,1 skipped (2.73s)**. The skip
requires real Windows native handles. Windows reader implementation is not yet
Windows qualification; selected Provider input retains its existing POSIX-only
eligibility. This does not claim adversarial-host mutation isolation.

Three independent retention reproductions show rejected updates leaving an
unnecessary permanent pin, Catalog updates retaining old pins, and uninstall
collecting bytes still held by a user or another registry sharing the same CAS.
The existing CAS now has additive opaque retention owners in the same pins.json,
with legacy/default retention and a format guard that the actual frozen old
loader rejects. Skill preparation, installation, update and removal release
only their own holds under the existing lifecycle fences. Canonical Extension
references take precedence over stale legacy projections. Failed promotion
after publication and ambiguous historical/crash holds remain protected and
require explicit review. Artifact/Skill/Extension-fence/HTTP regression:
**217 passed (37.54s)**. The stale-review test injects its original mutation
after the actual lifecycle fence is acquired; no review assertion is weakened.
All scopes overlap. Exact composed-source CI remains required before integration.

Frozen composed source `b7b17b4` full regression retains **2 failed,5637 passed,
59 skipped,4 warnings (692.03s)**. Both snapshot fixtures still injected through
Path.open, which the descriptor reader no longer uses; the intended mutation
did not occur during the Runtime call. The snapshot test now changes the file
after actual bounded acquisition and traps any subsequent pathname reopen for
the digest, retaining its original successful content/hash assertions. The growth
test changes the source before the real descriptor opens and retains the actual
256KiB refusal. This also exposes and restores the old precise size diagnostic
through a typed bounded-read error; strict inode/version checks are unchanged.
Original failing logs remain retained, not relabelled successful qualification.

Frozen composed source `7a9c3af` subsequently passes **5643 tests,59 skipped,
4 warnings (699.92s)** with a process-local child reaper:18 adopted children
reaped,zero owned children remaining. This Linux result is not Windows
qualification. A subsequent minimal Windows-only ordinary-name guard rejects
colon/stream syntax and trailing dots/spaces before protected path resolution
and before native file opening. It preserves anchors, existing traversal
admission,POSIX filenames and explicit legacy scope. No private-state bypass has
been reproduced on Windows. Pure Windows-name/pre-resolution/native-preflight
checks plus related workspace/snapshot/selected-input regressions pass
**127 tests,3 skipped** on both Python3.12 and3.11. The skips require actual
Windows handle sharing and two owned alternate-stream cases; their presence is
not native acceptance. Exact-source Windows CI remains required.

Source `458e036` Multi-Arch then passes: Linux ARM64 **5317 passed,62 skipped,
292 deselected** and Windows **5240 passed,139 skipped,292 deselected**. The
owned alternate-stream rejection cases run and pass on Windows Server2025;
this is not installed Desktop or Windows10 qualification. Core Linux3.12 passes
**5640 tests,50 skipped**, Linux3.10/macOS each **5629 passed,61 skipped**.
Windows Core retains **1 failed,5532 passed,157 skipped (2099.72s)**: original
ProcessSession recovery is RUNNING with the same PID, but the subsequent fresh
control admission refuses RECOVERY_REQUIRED. The whole ProcessSession module
takes about9.27seconds in the log, so its30-second child lifetime is not evidence
of the failure cause. This separate unresolved failure is
[Issue85](https://github.com/untrod/apeir/issues/85), not an Automation verdict
or Relay diagnosis. The original log omits the refusal reason; a passing rerun
cannot identify whether the current host record or OS identity query failed.

The existing ProcessSession control exception now reports allowlisted reason
codes while preserving its ValueError contract and message prefix. Arbitrary
host errors, commands, output and environment are not reflected. Five negative
diagnostic cases fail before this change and pass after; control admission,
identity checks, deadlines and execution are unchanged. The crash-rebind test
now owns its child lifetime through stdin and checks terminal evidence during
cleanup, without repeating an accepted or uncertain control. A real-host negative
case denies an unverified control before any request is written, restores the
same original target/helper identities without respawn, and submits exactly one
valid kill. ProcessSession/startup/admission regressions: **28 passed** on
Python3.12 (24.48s) and3.11 (24.32s); each owned test reaper collects four children
with zero remaining. This improves diagnostics and fixture ownership; the
historical Windows cause and complete product Gate remain unresolved.

Frozen diagnostic source `c1272b8` full initialized Linux regression subsequently
passes **5668 tests,61 skipped,4 warnings (719.93s)**, with18 adopted children
reaped and zero owned children remaining. Fresh isolated Distribution/SDK wheels
also pass the nine public Demo/Provider/instruction-Skill invocations; this is
runtime-service/simulation, not a paid model, native installation or hardware.
Desktop and Security pass; the exact-source Windows diagnostic remains separate.

The next wiring audit classifies the shared safe workspace reader as REUSE and
the saved-file input platform gate as EXTEND. SelectedInput still required POSIX
descriptors even after the ordinary Windows native reader was exercised. It now
uses the same backend, with typed unavailable errors and no pathname fallback.
Source-private rules are reapplied to the canonical location, and Windows tilde
and namespace spellings are refused before acquisition. Seven prequalification
probes fail on the preceding methods and pass with these guards; Windows input
was previously blocked, so this is not a reproduced Windows private-data leak.
Read and Provider-transfer permissions, exact source/recipient/Work bindings,
SHA, byte/token budgets and per-attempt revocation remain independent.

Related source-reader/Context/HTTP tests pass **252 tests,7 skipped** on each of
Python3.12/3.11. After adding explicit owner-policy scope, Context/Model Runtime/
Governance/Work/Agent/workspace combination passes **1462 tests,8 skipped
(44.38s)**. Counts overlap. Existing POSIX mid-read link assertions stay intact;
native Windows equivalents check pre-open links, held-handle mutations and either
OS-denied or detected mid-read links. Those native cases await Windows execution.
Two existing default API bootstrap cases retain their POSIX owner-file scope;
an added Windows negative must prove the owner-file loader remains denied. The
safe reader does not qualify Windows ACL policy bootstrap, seed permissions,
authenticate a remote human or complete installed Desktop/model qualification.

### Windows owner-policy spelling admission — 2026-10-21

**REUSE / FIX** the existing PermissionEngine, native handle reader and private
file ACL helper. Source `d5b20ef` Core run
[39457023307](https://github.com/untrod/apeir/actions/runs/39457023307) passed
Linux/macOS, but Windows recorded **2 failed,5633 passed,88 skipped,4 warnings
(2613.44s)**. Both failures are the unchanged trailing-dot/space negative tests:
Win32 normalization removed the ambiguous spelling before file admission.
The reader now checks the supplied spelling with the existing Windows component
validator before `abspath`, then retains the same pinned-handle ACL/owner checks.
The trusted-host `NOUS_PERMISSION_POLICY` entrypoint performs that admission
before its own `.absolute()` call. Eight host-independent negative cases prove
neither entrypoint reaches normalization for ambiguous names. Native loader and
host-bootstrap tests retain the same deny requirement. Related policy/selected-
input regression: **63 passed,12 skipped (14.21s)** on Linux.
New native Windows execution is still required before policy qualification.

An uninitialized container full run on `d5b20ef` recorded **2 failed,5681 passed,
74 skipped,4 warnings (730.83s)**. Both failures are ProcessSession orphan
reaping assertions; the same pair fails on main `e3cd2a2` and parent `ae75148`.
Actual child status is zombie under the environment's non-reaping `tail` PID1.
This is retained baseline evidence, independent of Windows owner-policy changes.


### Workspace connection lifetime and source-browser qualification — 2026-10-21

REUSE the existing connection epoch, Workbench/Proposal HTTP APIs, Governance,
Workflow, CAS and EventStream. FIX the Workspace view lifetime and original
approval continuation; no execution authority or store is added. The original
component reproduced four failing cases: same-address token replacement,
Controller/token ABA and view closure during an outstanding approval. The
bounded fix checks the captured connection before dispatch/after responses and
before follow-on actions, and resets Workspace state on connection-epoch change.
A late response cannot publish success or start reads against the new connection.
Closing the view is not proof that an admitted backend operation was cancelled.

A sandbox-enabled Chromium run used the actual Vite frontend and Runtime HTTP
server, a deterministic fake ModelWorkDeliberator adapter and the existing signed
fake-OIDC test fixture. The original Work read both existing files before
preparing one two-file proposal. Browser review and Approve Once changed both
files, with the original admission and fresh CAS-backed file MATCH. Reload and a
new Runtime process retained the original proposal/authorization/manifest;
explicit reconciliation reported no replay. Both browser runs had zero page
errors. No real account credentials, installed executable or physical device was
used. The first fixture attempt correctly refused to propose unread existing
files; its original recovery record is retained, not retried as another effect.

Related Work/proposal/API/Context regressions: **221 passed (9.94s)**. Final
Desktop regression: **40 files / 248 passed (64.74s)**; lint, typecheck, build,
Ruff, compile, documentation and repository checks pass. Security has **0 HIGH,
5 existing MEDIUM** findings. Component-lock contracts have **3 passed**; the
actual native-byte verifier still fails at the missing locked Windows nousd. The real
strict-sandbox probe returned `STRICT_SANDBOX_UNAVAILABLE`; no unrestricted host
fallback ran. Therefore the complete model→edit→test product Gate remains PARTIAL:
file-byte MATCH does not verify tests, and the source Work is not declared
completed merely because its proposal was applied. Native binaries, deployed
human identity, real model/provider and physical qualifications remain separate.


### Environment continuation connection binding — 2026-10-21

REUSE `EnvironmentInspector`, Runtime API, existing connection epoch, human nonce
and Governance. FIX the URL-only view checks: token rotation, A→B→A and unmount
could continue a reviewed Environment request. Four controlled pre-change cases
fail (**4 failed,8 passed,1.91s**), including an extra refresh after unmount. The
existing URL/token/epoch guard now binds the panel lifetime, all read/result
publication and each service continuation. Connection changes remount the panel
and clear old approvals/output. Approval nonce acquisition receives the same
view guard; an additional client-boundary case proves closing the view prevents
the decision POST after its nonce arrives. Original exact-body continuation,
service-cookie separation, lost-response/no-retry and fail-closed isolation
assertions remain. No backend authority, Environment, process store or Kernel is
added or changed.

Focused frontend cases: **16 passed (2.77s)**. Full Desktop regression:
**40 files,253 passed (57.51s)**. Related existing Environment/HTTP/target-binding
regression: **132 passed,2 skipped (2.40s)**. Lint, TypeScript and production web
asset build pass; the existing Tauri static/dynamic import warning remains.
Sandbox-enabled Chromium with actual Vite/Runtime HTTP and signed fake OIDC
exercised denial without host permission, exact human nonce/approval, service
resubmission and persisted OCI environment contract creation. Reload reads the
actual created record with zero page errors; screenshots are source-browser
records, not installed APEIR.exe captures. No OCI workload ran; strong isolation,
real IdP/model, hardware and native installation remain separately unqualified.
Required source and resulting-main CI remain separate integration gates.


### Original mutation result delivery before tamper qualification — 2026-10-21

Windows Core [39689311331](https://github.com/untrod/apeir/actions/runs/39689311331/job/119531250658)
at `90b44845` retains **1 failed,5647 passed,88 skipped,4 warnings (2250.03s)**.
The semantic-device-tamper case fails before tampering: Workflow failed,
mutation Work RUNNING, verification absent, reconciliation required and effect
count1. Linux/macOS passes do not resolve that failure. A controlled local drop
of the first original mutation terminal message reproduces the same failed
precondition (**1 failed,6.08s**); its exact error identifies the original
mutation Work timeout. This establishes a delivery-loss failure class, not the
reason the hosted Windows message was late or lost. Issue #82 remains open.

REUSE existing Automation consumer, Node journal signature/binding validation,
reconciler and independent observation. FIX only the acceptance precondition:
for that exact original mutation timeout, require RUNNING with no Controller
receipt/verification, one effect, reconciliation required and the original bound
signed terminal journal before opening recovery transport. Perform one explicit
reconcile/resume of the same Work/run, with mutation invocation forbidden during
recovery. The existing observation-loss continuation uses that same no-mutation
assertion. Missing/changed evidence still fails; all final COMMITTED/MATCH,
wrong-device and semantic tamper assertions remain. No Runtime deadline, retry,
result state, execution policy, authority or Kernel code changes.

Existing Automation plus Verified Demo regressions: **130 passed (211.17s)**,
including the new controlled mutation-result-loss case, original observation
loss, corrupted journals/evidence, denied authority, restart and effect_count1.
Current-source cross-platform CI and resulting-main qualification remain required;
this is not a claim to have fixed Windows transport timing or closed #4/#8/#82.

The unchanged Environment view correction also passed an actual sandbox-enabled
Chromium/Runtime HTTP negative: hold its real human nonce response, leave the
Environment view, then deliver that response. The original approval stays
PENDING; no decision POST, service continuation or additional environment occurs,
with zero page errors. Verification uses the existing legacy approval projection
`/api/v1/control/approvals`; `/api/v1/approvals` and Operations expose the distinct
Operation approval projection. Private fixture/locator corrections are not
reported as product defects. No OCI workload, actual IdP or native UI is qualified.

### Chat response and view lifetime binding — 2026-10-22

REUSE the existing Chat/Conversation Runtime, shared Desktop API, connection epoch,
EventStream, human nonce and original proposal owner. FIX two observed gaps.
First, a late model result/history/event replay could publish callbacks or data
after same-URL token rotation, A→B→A, conversation navigation or panel closure.
Six controlled pre-change Chat cases fail (**6 failed,9 passed,1.65s**); three
shared-client delayed-response/body cases fail (**3 failed,981ms**). The shared
API now checks its captured connection before parsing and after reading a body,
returning the existing structured `NOUS_CONTROLLER_CHANGED` error. Four existing
Node/Usage negatives now require that exact code rather than their former
helper-specific strings; they still reject all original connection changes.

Chat binds pending results and history to the original mounted conversation and
connection epoch. It aborts only its client request and closes its event
subscription on closure/replacement; these actions do not prove Runtime
execution stopped. Old callbacks cannot open a proposal/conversation or clear a
new request's loading state. Chat approval passes the same mounted-view guard to
existing nonce acquisition, so a late nonce cannot cause a decision POST after
closure, navigation or credential rotation. No automatic mutation/model retry,
new execution authority, backend record store or Kernel change is introduced.

Second, the canonical Chat HTTP response retains the Runtime result under
`data.result`, while the client expected only top-level `result`. The original
proposal navigation contract fails (**1 failed,3 passed,874ms**). The existing
client now projects that original nested result, preserving proposal and approval
IDs and its previous top-level compatibility. The original waiting-approval state
and human approval are unchanged; a proposal reference is not a grant or success.

Focused Chat/API/Node/Usage regression: **48 passed (5.97s)**. Full Desktop:
**41 files,267 passed (53.74s)**. Existing related Chat, selected-input, proposal
and Work flow regressions: **133 passed,1 skipped (21.98s)**. ESLint, TypeScript
and production web assets pass, retaining the existing Tauri mixed-import warning.
Security scan has **0 HIGH,5 unchanged MEDIUM** findings.

Sandbox-enabled Chromium with actual Vite and authenticated Runtime HTTP rejects
a held original conversation read after credential rotation. A real Chat request
then persists its original conversation before its HTTP response is released;
closing the actual Workspace view does not resubmit it. Exactly one Chat POST,
two persisted conversation messages and zero browser page errors are observed.
No model is configured: the actual original request status is `failed`, not a
coding success. This qualifies software response/history boundaries only, not
real model execution, installed Desktop, native bytes, IdP or physical effects.
Earlier browser qualification scripts initially selected no Chat view and then
the disabled code-editor textarea; those selector failures are retained as
qualification-fixture errors, not Runtime defects or passing product evidence.
Source PR and resulting-main qualification remain separate integration gates.

### Event consumer lifetime qualification — 2026-10-22

REUSE existing EventClient, Runtime/Run subscription helpers, shared API,
EntityStore, Inspector and connection epoch. FIX retired consumer publication:
closing a subscription while a page is pending still delivered callbacks;
changing credentials between polls reused the original cursor on a new
connection; a stop/start race could publish an old page and create another loop.
Original subscription contracts retain **10 failed,2 passed (1.43s)**. Corrected
original EventClient fixture retains **4 failed,1 passed (1.02s)**, including old
backfill and WebSocket callback ownership. An earlier incomplete fixture exhausted
its mocked transport and raised TypeError; that fixture failure is retained
separately and is not attributed to production transport.

The existing helpers now validate the original connection and active lifetime
before dispatch, after a page and between callbacks; close clears its scheduled
timer. EventClient generations bind polling, backfill, socket callbacks and
reconnect scheduling to one original start. Retired completions cannot ingest
entities, disconnect a replacement socket or schedule another loop. Inspector
remounts its existing panels on connection change. Original transient read retries
and bounded polling intervals remain; none submits or retries an execution.
This changes no authority, EventStore, backend database, Work, Kernel or lock.

Focused Chat/API/event-consumer regression: **39 passed (4.38s)**. Full Desktop:
**43 files,284 passed (60.37s)**. Lint, TypeScript and production web assets pass;
the existing Tauri mixed-import warning remains. Actual sandbox-enabled Chromium,
Vite and authenticated Runtime HTTP read two persisted diagnostic Run events:
closing the held original subscription delivers zero callbacks, a fresh
subscription receives both, and credential rotation causes zero additional
requests from that old subscription. Browser page errors: zero. These are real
HTTP/event-consumption observations, not model, execution, native WebSocket,
installed Desktop, IdP or physical qualification.

DEFER the separate compatibility cursor alignment audit: the global Event Bus
HTTP endpoint accepts event IDs, while the older EventClient backfill uses
per-domain numeric sequence values. Lifetime tests preserve that existing path;
they do not establish complete historical replay, retention-gap handling or
uniform ordering across Event Bus and per-Run EventStream. No full event-history
or overall product PASS follows from these bounded lifecycle checks. Source CI
and protected resulting-main integration remain separate required gates.

### Global Event Bus cursor and persistence alignment — 2026-10-23

This follows up the explicitly deferred cursor audit above. REUSE the global
RuntimeEventBus/SQLite owner, EventClient, existing API/Inspector, EntityStore and
per-Run EventStream; FIX their incompatible cursor assumptions. Bus replay accepts
an original event ID, while the old client sent a per-domain numeric sequence.
The old server searched only the recent page, substituted a recent snapshot for
an unavailable cursor and initially returned reverse order. Its first flush could
also clear queued events before a database existed. Original backend contracts:
**9 failed (0.12s)**; original client cursor contracts: **4 failed (1.22s)**.

The existing Bus now queues publication and flushes under its owner lock. A first
flush initializes the same database; unavailable persistence retains the queued
batch and cannot certify empty history. Stream reads flush that original batch
and use one SQLite read snapshot for event-ID lookup and chronological paging.
The initial empty cursor explicitly selects only a recent bounded window;
retained cursors page forward beyond that window. Missing/pruned cursors return
`NOUS_EVENT_CURSOR_UNAVAILABLE`/HTTP409, and unavailable/corrupt history returns
`NOUS_EVENT_STREAM_UNAVAILABLE`/HTTP503 with a fixed, payload-free diagnostic.
There is no guessed cursor repair, new journal or schema, authority, execution
retry or Kernel change. WAL, synchronous NORMAL and existing SQLite/HTTP timeout
settings are unchanged. The global Bus remains a retained activity projection,
not the authoritative Work/effect journal or a promise of indefinite retention.

EventClient now retains opaque event IDs only for its current connection and
resumes that cursor across stop/start. A changed connection discards that cursor;
a cold process reads the current recent window and existing authoritative REST
snapshots rather than claiming complete historical replay. Non-advancing pages
and unavailable history stop and surface a fixed diagnostic through the existing
Inspector/toast path. The shared HTTP client checks IDs, duplicates and last-ID
consistency before publishing a page. Per-Run numeric sequence cursors remain
unchanged. One earlier fixture asserted numeric `201` for the global API; it now
requires the actual original event ID `current-199`, retaining its201-event and
single-loop assertions. The server contract demonstrates why the old expectation
was incorrect; no denial/no-retry assertion was relaxed.

Final event/HTTP/task projection/AgentSession/Reality related regression:
**122 passed (66.46s)**; final targeted backend contracts **13 passed (1.69s)**
include actual authenticated HTTP, restart, pagination, concurrent writers, domain
filtering, retained queue, missing cursor and payload-free storage failure. The
last fixture-only credential spelling check reran these13 cases successfully
(1.46s); the deterministic fake token remains identical in client and server.
Client cursor/lifetime/integrity and Inspector cases: **26 passed (8.06s)**.
Full Desktop: **44 files,292 passed (52.93s)**; lint/typecheck/web assets pass with the existing
Tauri mixed-import warning. Repository checks pass, with0HIGH/5existingMEDIUM
security findings. An inline deterministic fake Bearer header initially added a
scanner match; the fixture now uses its single declared fake token in both the
server and request. Scanner rules and negative assertions are unchanged. These
counts overlap and are not added together.

Actual sandbox-enabled Chromium/Vite/authenticated Runtime HTTP and the original
SQLite Bus replayed239 diagnostic events across pages with zero duplicate IDs.
The existing EventClient cold view consumed the recent200 in order. Another
SQLite owner then removed its original cursor: HTTP409 was observed, the error
callback fired, and no further requests followed the stopped consumer; browser
page errors: zero. These are diagnostic projection events, not model, operation,
physical-effect, native Desktop or IdP qualification. Original backend/client
failure logs and private browser records are retained. Exact-source CI and
protected resulting-main acceptance remain required; no performance percentage or
overall product PASS is inferred from these correctness checks.


## Event projection owner admission — 2026-10-24

REUSE the existing RuntimeEventBus singleton, retained SQLite projection and
original event-ID cursor. FIX its configured-owner admission and absolute path
pinning; changing a process owner fails closed until an explicit Runtime restart.
No event system, root authority, database pool or automatic evidence migration
is added. Original records outside the configured owner are left intact; they
cannot be silently assigned to another workspace. Per-Run EventStream and Work
records are unaffected. Detailed failure evidence is retained privately.

Five original deterministic ownership/replay tests failed on main `d14859c`.
The same tests pass after the bounded owner fix, including actual independent
CLI/HTTP startup, original event IDs, rejected unrelated cursors, relative paths
and deterministic concurrent first-owner admission. Event/replay/Control Plane
regression passed52 tests locally. Source-browser qualification covers the
existing EventStream widget through the real authenticated Controller switch;
no model, physical or native qualification is inferred. Exact PR and resulting
main CI remain separate requirements.

## R5 Workflow Builder software integration — 2026-10-25

REUSE WorkflowDefinition, Compiler, TaskGraph, WorkflowRuntime, WorkflowStore,
EventStream, API authentication/nonce, Gate, Broker/LeaseManager, human-session
identity/permissions, stable Studio panel portals and private-draft protection.
EXTEND the existing `workflow` panel and HTTP route family; no new executor,
scheduler, event bus, database or authority is introduced. Public JSON codecs in
the existing models now serve CLI and Store. FIX CAPABILITY-without-action to
return a validation error instead of an incidental compiler KeyError.

The React Flow12.12.0 MIT editor supports nodes/dependency edges, multi-selection,
copy/delete, parameter JSON, layout/undo/redo and explicit portable draft files.
Coordinates stay separate from canonical CLI definitions and Studio version1
layouts. Unapplied/invalid parameters block registration/execution. Moving a
panel retains its React state; Controller retirement retains private draft export
and cannot import old authorization into the new Controller. Graph imports do
not execute. Pure Wait/Condition/Transform/Approval handlers are the only bound
step types. Host-specific actions, command/Agent/Connector/Capability execution,
expression conditions and compensation hosts are unavailable here. WAIT is an
immediate barrier. Declared JSON input/output schemas do not imply typed output
routing; edges represent dependencies.

Governed mutations bind the actual server workspace and immutable definition,
not a request-body workspace. Run submission compares the reviewed draft with
the registered version and uses an original idempotency key. Run recovery never
accepts client `approved_steps`. Step approval additionally requires the existing
nonserialized current human identity and original-step permission; the same
HTTP human nonce protects that request. An ordinary service lease cannot approve
it. Index endpoints transfer bounded identity/state summaries; private definitions
and results are fetched explicitly. The existing Store persists original IDs,
bindings, checkpoints and outcome uncertainty; no independent physical effect is
claimed from these computational results.

Actual sandbox-enabled Chromium/CLI/HTTP qualification creates and connects two
steps, validates, exports a canonical definition accepted by the existing CLI,
saves/restores a private draft, registers through a one-use approval lease, runs
the real pure handlers, inspects original events, restarts the owned Runtime and
loads the same Run ID. A different Controller cannot retrieve it, and a missing
bearer is rejected. The independent test approver uses the actual public CLI and its attested local
OS-owner context outside the browser; this is software authority-fixture
evidence, not real-IdP qualification. Separate cryptographic fake-IdP tests exercise current human
approval, wrong scope, serialized identity, changed binding and revocation.
Full exact-commit required CI and protected resulting-main acceptance remain
separate gates. No model, strong-sandbox command, physical, Windows native,
Token-saving or end-to-end performance PASS follows from this software scope.


A clean Python3.12 wheel consumer outside the checkout additionally reproduced
an existing public CLI disconnect: approving a Gate-bound API request recorded
APPROVED without issuing its execution lease, so the original registration
remained blocked. The CLI now routes bound approval/denial through the existing
ApprovalBroker's attested-human/original-proposal checks and one-use lease
transaction. Unbound compatibility decisions retain their old non-executing
semantics. Local listing includes the owner's Gate-bound API requests. Original
installed-wheel failure evidence and process-cleanup results are retained
privately. This is a necessary source-user path, not a new approval authority.

After the CLI fix, a new clean Python3.12.14 virtual environment installed the
wheel for `e0dbf6ffcf8994803096918fb7fbd41a19c35fb7` (SHA256
`6d3a4f41a1568d23696cbf8366d0fe764527a3db81c724571bb5013f4be92f02`).
From an owned temporary workspace outside the checkout, the public installed CLI
validated the definition, supplied the original API approval and admitted
registration/execution through the real HTTP Gate. After stopping and restarting
the installed Runtime, detail/events and repeated same-key submission retained
Run `wfr_fd79c162e6c948c8b12c9c6658a09955`, with exactly one persisted run. Normal
process cleanup passed. The browser path also uses this public CLI approval,
not a low-level lease fixture. This is Linux installed-wheel software evidence;
exact resulting-main qualification, model, sandbox and native gates remain
independent.


### R5 source-entry CI follow-up — 2026-10-25

PR95 at `a7b919f3351f07ceb9237c0e0b05f2971c804580` failed Core run
[40181568192](https://github.com/untrod/apeir/actions/runs/40181568192), Linux
Python3.10 job121133551259. The README omitted the existing local-first contract;
the text was restored in both languages. Separately, the actual CLI event-owner
startup probe raised `TimeoutError` before receiving HTTP headers. The CLI binds
before initialization to protect the active session on port conflict; a connected
socket therefore does not establish HTTP readiness. The read-only startup loop
now handles this transient outcome, with the same1-second request timeout,
10-second overall deadline and unchanged original/foreign-event assertions.
Fault injection covers connection refusal and pre-serving timeout, then exercises
the real CLI/HTTP path. The affected EventStream/startup/hygiene checks passed29
locally. This corrects probe handling; it does not qualify or close the separate
historical Windows SQLite, relay, signed-response or Automation timing issues.

### R5 declarative UI host qualification — 2026-10-25

The Studio UI child schema (`apeir.studio-ui/v1`) is additive metadata in the
existing Extension IR. Existing Registry, package/provenance verification, CAS
and pins, Governance dispatcher, current-human nonce, Workflow Runtime and Studio
layout/subscription owners are reused. This is data-only rendering; executable
third-party JavaScript remains BLOCKED pending isolation. Kernel revision,
component-lock bytes and historical tags are unchanged.

The actual source CLI/HTTP + sandbox-enabled Chromium consumer acquired the
System Monitor manifest outside the checkout, reviewed its digest, requested
installation, used a separate public OS-owner CLI approval, enabled it, read
actual Runtime status, added a Panel and Dashboard Widget and saved version-1
layout. It checked default-disabled installation/update, same-version content
conflict, disablement denying new data reads, enablement, update, browser reload,
Controller A/B absence isolation, actual Runtime process restart, retained package
state, uninstall and inert missing-component slots. It does not inject test grants
or import private Runtime modules to install the example. The example's standalone
standard-library HTTP client uses those same public endpoints. Source screenshot:
[`studio-extension-runtime-source.png`](../media/studio-extension-runtime-source.png).

A first real browser attempt exposed an incorrectly assumed human-session response
shape in the new shared UI helper. It denied the service request before install.
The fix reuses the existing read-only session probe, catches only its explicit
no-human errors, and checks the original Controller before dispatch. Current humans
still need the exact-body nonce; a failed mutation is never retried automatically.
The Workflow panel reuses the same helper while retaining its strictly human-only
step approval. Regression cases cover service/human surfaces, nonce/body binding,
Controller switch during the probe and a lost mutation response.

Registry/CAS tests cover digest and version binding, same-version replacement,
stale installer review, original package integrity, mirrored display-state lock,
no execution grants, dependency failure, denied undeclared reads, schema/code/URL
rejection, escaped literal HTML and retained missing-layout state. Real Gate/API
tests additionally require the original lease for optional declared pure Workflow
actions, preserve the same idempotent Run and reject new actions after permission
revocation. Unsupported command handlers do not create a Run. No Widget creates
execution authority; approval, handler execution and physical verification remain
separate gates.

The first full nine-case source-browser suite passed; an additional extension
case then passed Controller A/B and process-restart checks in 13.7 seconds. The
affected Extension/Workflow/Governance/Control Plane/repository suite passed
1,013 cases with 33 explicit platform skips; the additional actual action API case
passed separately. These local results are not exact resulting-main CI. Retained
pre-fix failures include incorrect test fixtures, original helper denial and UI
locator errors; no timeout or safety assertion was weakened. Current-head required
CI and resulting-main CI must qualify their exact submissions independently.

The first SDK acquisition profile accepts bounded native JSON manifests and
already-installed compatible dependencies. It does not acquire executable UI,
resolve remote packages or certify publisher claims. Its lifecycle event interface
is bounded metadata reads from the original bus, not an additional event stream.
Chart samples are transient display data, not persisted observations. The Source
Preview job now also runs on normal main pushes, preserving its clean isolated
wheel consumer, hash/manifest/report uploads and all native component gates.

No real model, host command sandbox, real IdP, remote physical device, Windows10
installation, signing or formal release qualification follows from these results.
R4 unapproved candidates and their original hash mismatch remain independent.

The clean base-wheel consumer at SDK candidate `a7d7505` then found an undeclared
`packaging` import in dependency validation, despite development tests passing.
The original failure (`No module named packaging`) is retained separately. The
fix declares the normal pure-Python package dependency in Distribution metadata;
it does not add a private module or manually patch the consumer environment.
A rebuilt wheel must pass the same external public client and restart sequence
in a new venv before claiming that installed path PASS.

The corrected base Wheel at `4d8d19e` passed in a new Python
3.12.14 venv outside the checkout. Its SHA-256 is
`b237e8011ccbe441210e8efb0b3a7490423504aebd1bc9ffc3584b8fe5a154ef`. The copied standalone example
client performed review, install, enable, real sanitized read, lifecycle metadata
read, disable/denial, same-version conflict, update, restart recovery and remove.
Every mutation used the public original owner approval CLI; there were no private
Runtime imports or manually added consumer dependencies. Original Workflow Run
`wfr_9557396af0664f2eae45cb1328d05c9b` remained unchanged after restart and repeated original
idempotency key. This is Linux installed-source software evidence, not a native
or physical qualification. Initial undeclared-dependency and local disk-exhaustion
failures remain retained; a fresh venv was used after freeing only reproducible
inactive frontend dependency directories. Original source and native evidence
were preserved.

Final contract review also reproduced a valid multi-package response exceeding
the first 1 MiB frontend/example-client projection bound. The fixed 5 MiB
consumer limit matches 64 bounded 64 KiB UI packages plus verified envelopes;
per-view types, depth, source and action limits are unchanged. A 20-package
counterexample now loads, while malformed rendered record primitives and the
65th package fail admission. This is a bounded contract fix, not a performance
improvement claim.

The original DistributedWork contract defines `VERIFIED` as receipt verification
before independent effect admission (`record_effect_verification` requires that
stage). Dashboard previously rendered that stage using the generic success tone.
The source renderer now separates `RECEIPT_VERIFIED` from the actual reported
`effect_verification.verdict`; absent or invalid verdicts stay UNKNOWN. Regression
cases cover receipt-verified UNKNOWN/MISMATCH, digest-only MATCH and a separately
reported effect MATCH. No verification is calculated or granted by the UI.

Final new-host review bound optional Widget actions to the existing canonical
Workflow resource, rather than the presentation Registry path. Install/enable
permissions remain Registry-scoped; execution requires permission on the actual
`.nous/workflows.db`, and reuses canonical Workflow read admission. The reviewed
proposal additionally names the originally declared Workflow ID/version, without
copying raw inputs. Regression proves that display-resource permissions alone
cannot authorize a Workflow target and that the genuine original Gate lease still
admits the correctly scoped pure action. This corrects the new, unmerged SDK
adapter; no parallel permission system or Workflow executor was introduced.

### Resulting-main ProcessSession attachment investigation — 2026-10-25

Resulting main `daa71091a3c91dc911400ebf8b6af91ab90eb668` passed Core/Desktop/
Security but failed Windows Multi-Arch run40205953411, job121206804852:
`test_startup_reobserves_original_identity_without_spawning_again[True-2]`.
Startup returned RUNNING; immediate reattachment returned RECOVERY_REQUIRED.
The original assertion did not include that attachment's reason. The full raw
job log is retained; neither a retry nor historical PR success qualifies main.
Issue85 and the older Windows reliability issues remain open.

Code review identified a separate negative pathname check before reading the
helper's repeatedly replaced `host.json`. A controlled negative pathname sample
reproduced the same false missing-record projection while a current bound record
and both live original identities were readable. Removing that redundant precheck
uses one direct current record read. Missing, inaccessible or malformed records
still fail closed; OS PID/creation-time and original command/helper binding checks
remain mandatory. No previous snapshot is reused, no control is replayed and no
deadline or timeout is increased. This is a demonstrated admission-path fix,
not proof that the original Windows incident had that particular OS cause.

The original startup test retains its exact RUNNING, identity, single-launch and
single-control assertions and now includes attachment state, current host state,
content-free OS read errors and sampled creation tokens on failure. Windows
Multi-Arch runs the original failing case before its unchanged complete suite,
providing earlier original evidence. Local affected startup/control/reaping
regression:39 passed. Exact Windows and resulting-main qualification remain
PENDING until their real CI completes. Frozen Rust Kernel and component lock are
unchanged; the patch is in Distribution's existing process-session reader.

### R5 Windows integration follow-up: durable authorization publication

PR #97 candidate `d685a06` exposed two unchanged Windows Core tests in run
`40209354483`, job `121217158218`. The original full log is retained. MCP's
original five-second HTTP call timed out while Governance reported a 1094 ms
commit; the Node heartbeat observer independently raised PermissionError reading
an atomically replaced status file. Its missing finally cleanup left a daemon
thread reaching a later test's hostname-probe fault injection. These observations
do not establish one root cause for Issues #4/#8/#82/#85/#88.

The existing Gate previously committed proposal, decision and chained audit
separately. A real SQLite trace reproduces three commits for one decision and
retained partial records on later insertion failure. The correction reuses the
same Store, SQL inserts, operation_transaction and hash chain to publish the
three records in one FULL/WAL transaction. Commit/insert failure denies authority;
an uncertain commit is not retried. Existing individual Store methods and
compatibility-store failure contracts remain available. There is no pool,
additional database, credential change or new authorization authority.

A controlled Linux HTTP experiment with 0.7 seconds injected per actual SQLite
write commit reproduces the original five-second MCP timeout. The candidate
returns the original approval-required result in 4.226 seconds (six commits,
zero tool effects); this is fault-model evidence, not a Windows latency guarantee
or a general performance improvement percentage. All original HTTP deadlines,
durability settings and approval requirements remain unchanged.

The live-heartbeat test now always stops and joins its owned daemon in finally.
A transient unreadable/missing status is not an ONLINE observation: it reobserves
within the original five seconds, and explicitly requires a fresh sequence >= 2.
The final STOPPED/watchdog/telemetry assertions and three-second join remain.
The injected read-failure counterexample is retained; permanent unreadability
still fails. No Node delivery, identity, permission or workload replay behavior
is relaxed. New regressions cover atomic rollback at each insert/commit, independent
writers' audit bindings, uncertain commit with one publication attempt, and both
ordinary and interrupted live status reads. Current candidate and resulting-main
Windows CI must qualify independently of these local experiments.

The SDK/process/Governance source combination at `856a377` passed nine actual
sandboxed Chromium cases, including public human approvals, original Workflow
registration/run/restart, extension lifecycle/revocation and Controller/layout
isolation. A newly built base wheel installed in a new outside-checkout Python
3.12.14 venv has SHA-256
`27b3294081df4b525726a485c054e05c0022a5e0d26bc01b655acb835ffe8833`.
The copied standalone SDK client (`python -I`) passed install/update/disable,
permission rejection and restart through public CLI/API. Original Run
`wfr_0c73efadbd264159a443e4a054a6f3b4` survived repeat-key recovery unchanged.
Official source qualification kept production models without Kernel BLOCKED,
usage UNKNOWN, unauthenticated requests denied and owned shutdown clean.

The compiled frontend and installed wheel from that same `856a377` source also
passed actual browser extension use, graphical Workflow execution and a manually
edited two-file proposal: separate original owner approval, actual file writes,
fresh file MATCH and original Work `work_1e8dadd98bbe5e1a8a9344e21001a070`.
Installed simulated lost-response recovery retained effect_count=1. These Linux,
model-disabled runtime-service results do not imply a generated model proposal,
a sandboxed test execution, native installation or physical verification. Exact
protected-main integration and corresponding CI/artifacts qualify separately.

## Windows ProcessSession ACK observation — 2026-10-26

PR100 Core40363014941 failed the original kill/terminal-state test when opening
its already-published ACK raised PermissionError. The full job retained
1 failed/5825 passed/95 skipped; the original assertion and log are preserved.
Three new real-process counterexamples reproduce transient permission/missing
reads and persistent unreadability. All three fail before the correction.

The existing ProcessSessionStore now opens the original ACK directly and
reobserves only FileNotFoundError/PermissionError within its unchanged five-second
deadline. It writes one control request; it never repeats a signal, restarts the
process or treats an unreadable ACK as success. Permanent unreadability still
raises the original timeout, and recovery independently observes the original
process. Malformed JSON is not hidden by the read retry. Local process/control,
startup, identity-denial and descendant-reaping regressions pass (37 cases).
Current Windows qualification remains required.

Native run40363123393 separately failed the original startup/attach assertion
(RECOVERY_REQUIRED instead of RUNNING) before packaging. Its displayed context
was truncated, so neither an OS identity-query miss nor a journal-read race is
established as its cause. The original assertion is unchanged; compact failure
context and an opt-in ProcessSession path in the existing diagnostic workflow
preserve the actual refusal reason. This diagnostic cannot satisfy Core gate.
Issue85 remains open. No Portable/NSIS or Windows10 installation PASS follows
from these software tests.

## Frozen Kernel test-environment separation — 2026-10-27

Native run40416794872 admitted the approved component bytes and passed the
Distribution/desktop regressions and Kernel Rust tests. The original frozen
Kernel Python E2E then failed test15: four Evidence directory entries instead
of two. The unchanged standalone fixture is a Python namespace package; a
regular installed Distribution Wheel takes precedence over it, even behind the
fixture in PYTHONPATH. The production CAS correctly creates objects, index,
lock and receipt entries. Its directory shape is not the standalone fixture's
two content-addressed files. Neither implementation should be changed to imitate
the other.

A controlled experiment with the actual downloaded main086 Wheel reproduced
the four entries and production module origin. A clean stdlib-only interpreter
selected the original frozen fixture and produced exactly two matching digest
files. The editable-install control did not reproduce the collision and is
retained separately; it is not a substitute for the regular-Wheel experiment.

The official Windows builder now invokes the unchanged Kernel scripts/test.ps1
inside a temporary stdlib-only Python environment. The wrapper excludes inherited
Python paths/home/user packages, verifies the Distribution is absent, preserves
the original script's exit status, and leaves its parent environment/directory
unchanged. It installs no alternate Kernel or Artifact implementation and changes
no frozen source, assertion, hash, timeout or production CAS. This is dependency
separation for trusted build tests, not a security sandbox. Real Runtime/Kernel
sidecar smoke still uses the ordinary Distribution build environment afterward.
Current Windows wrapper and complete Native qualification remain required.

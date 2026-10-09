# Engineering review and research comparison

Review date: 2026-10-09. Read-only baseline: Distribution
`5c9cdd987af3823d4be9e6909311af65b9be2299`; frozen Kernel
`87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
[ROADMAP](../../ROADMAP.md) remains the sole current milestone-status source.
This record distinguishes reproduced defects, inspected risks and unqualified
external dependencies. It is not an exhaustive proof that the repository is
bug-free, a physical acceptance, or production certification.

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
| P1 | Node Relay/state publication performs synchronous file IO and fsync | Correlate Node journal, signed delivery, Controller projection and Workflow wake timestamps for #4/#8. A timeout is an unknown outcome, not permission to repeat the effect. Move IO only after ordered persistence/cancellation tests demonstrate equivalent semantics. |
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

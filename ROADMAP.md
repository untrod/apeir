# APEIR roadmap and status

Current status for APEIR Runtime and APEIR Studio. This is the only roadmap.
Use [Quick Start](docs/operations/getting-started/QUICK_START.md) to run the
software; use [Engineering Review](docs/acceptance/ENGINEERING_REVIEW.md) for
dated tests, failures and build records.

**状态说明 / Status:** PASS applies only to the stated scope. PARTIAL means a
usable subset exists. PENDING means not yet accepted. BLOCKED names a missing
prerequisite. A successful software test does not qualify hardware or installation.

Kernel remains frozen at `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
Distribution is `0.1.0-rc1`; Provider SDK is `1.0.0b2`, NKI wrapper `0.1.1`.
See the [architecture contracts](docs/architecture/README.md) before changing
authority or execution.

## Product delivery qualification

| Level | Status | Qualified scope / remaining work |
| --- | --- | --- |
| SOURCE_READY | PASS | Independent wheel installation, authenticated model-free API, browser Studio and simulated original-result recovery. Download matching source bundles from a qualified main run. |
| PRODUCT_READY | PARTIAL | Setup, saved Provider management, reviewed file proposals, evidence and restart paths work in software. Live-model development and safely executed tests still need their separate prerequisites. |
| NATIVE_READY | PARTIAL | Approved components and unsigned Portable/NSIS builds exist. Current Windows 10 installed lifecycle is not qualified. |
| NATIVE_COMPONENT_READY | PASS | PR101 admitted the approved frozen-source x64 PE files through the existing component lock. [Exact inputs](docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md#approved-component-lock-migration--2026-10-26). |
| NATIVE_BUILD_READY | PASS | Full-mode run 40835150844 produced checked Portable/NSIS from older main 05e061e4, before PR110 integration. That source has a separately recorded Windows Context timeout; build/smoke success does not resolve it or qualify installed Windows 10. [Build identity and hashes](docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build). |
| NATIVE_INSTALL_READY | PENDING | Requires current-version Windows 10 x64 GUI, install, upgrade, restart, uninstall and Defender checks. No such host is attached. |
| RELEASE_READY | BLOCKED | Installed lifecycle, signing, supply-chain review and explicit publication authorization remain required. No stable Release is claimed. |

## Current usage boundaries

| Component | Status | Implemented | Remaining / evidence |
| --- | --- | --- | --- |
| Studio | PARTIAL | Docking, eight presets, named layouts, Dashboard, themes, bilingual navigation and Controller isolation | Executable third-party UI and live media are not qualified. [Studio guide](docs/development/DEVELOPER_PLATFORM.md#apeir-studio). |
| Direct development | PARTIAL | Project reads, drafts, two-file Proposal review, independent approval, file readback and original history | Live-model Proposal qualification and tests in a qualified strict sandbox. File MATCH is not test PASS. |
| Models | PARTIAL | Saved Provider lifecycle, credential references, qualified catalog IDs, explicit selection and cloud/local coexistence in software tests | Actual accounts/local services and endpoint capabilities need qualification. Frozen Worker has no Anthropic Messages backend. |
| Chat activity | PARTIAL | Recorded model/tool events, governed search, approval/receipt references, history inspection and reconnect state | NKI returns complete responses; incremental model text is not available. Full Skill-use attribution is pending. |
| Workflow | PARTIAL | Visual editor, Compiler, canonical definitions, pure handlers, approvals, original Runs and restart history | Model/Agent hosts and typed output-to-input bindings are not connected in the Studio API. [Builder limits](docs/development/DEVELOPER_PLATFORM.md#visual-workflow-builder). |
| Context / cost | PARTIAL | Bounded selected context, source/version manifests, budgets and nullable usage accounting | No general Token-saving percentage, live twenty-task comparison or complete incremental project-cache qualification. |
| Skills | PARTIAL | Reviewed local/HTTPS instruction catalogs, integrity, install/load/enable/disable/remove | Public publisher trust and arbitrary executable Skill workflows are not qualified. |
| UI extensions | PARTIAL | Reviewed declarative Panel/Widget contributions, sanitized reads and governed lifecycle | Arbitrary third-party JavaScript remains BLOCKED pending verified isolation. |
| Terminal / Git | PARTIAL | Governed fixed command profiles, ProcessSession records and bounded Git reads where isolation is available | Complete interactive PTY and Git write experience. No unrestricted host fallback. |
| Nodes / Devices | PARTIAL | Signed identity, pairing, trust, resource freshness, distributed Work, evidence and reconciliation | Current connected status is required; historical registration is not online readiness. Physical writes need separate acceptance. |
| Automation | PARTIAL | Structured simulated Workflow consumer, manual keys, one-shot due polling, history and original-trigger recovery | Recurring/background Cron, Event, Webhook and Recorder are not implemented. Free-text enabled configuration is not executable qualification. |
| Environment / scientific | PARTIAL | Persistent contracts, governed lifecycle and numerical reference tasks | Default local execution remains BLOCKED without its required strict sandbox; libraries or a created contract do not prove execution. |

The [Developer Platform](docs/development/DEVELOPER_PLATFORM.md) explains these
paths. A catalog entry, installed package or healthy endpoint is not proof that
a particular model or tool has run.

## Closure matrix

Accepted historical software milestones retain their original evidence. Later
changes require current-head regression; these rows do not transfer an old CI
result to a new commit.

| Milestone | Status | Implemented / remaining |
| --- | --- | --- |
| M3.1 Coordination | PASS | Durable AgentSession, TaskPlan, canonical Workflow and event wake/resume; tests/agent_collaboration and tests/agent_execution. |
| M3.2 Reliability | PASS | Durable delivery, journals and original-effect reconciliation; broader Windows timing issues remain open below. |
| M3.3-A/B Reality | PASS | Stable Device identity and independently observed simulated effects; [Reality audit](docs/acceptance/REALITY_ARCHITECTURE_AUDIT.md). |
| M3.3-C Physical Reality | PENDING | Jetson→ESP32 physical effect, observation and physical fault evidence. |
| M3.4 Governance / credentials | PASS | Scoped approvals, grants, revocation, execution-bound credential leases and redaction; production secret-store deployment remains separate. |
| M3.5 Control Plane software | PASS | Canonical-state API, trusted human/session admission, Operations Console and recovery; deployed real-human qualification remains pending. |
| M3.6 Developer Platform | PASS | Public canonical SDK, conformance suites and independent installed-wheel consumers; SDK remains beta. |
| Architecture consolidation | PASS | One authoritative constitution, execution path, state owner, security contract and Provider model. |
| M4 Interoperability | PARTIAL | OPA and OpenBao software references, generic external-agent reference and bounded Ray qualification. Complete authenticated Harness and industrial Providers remain unqualified. |
| M5 Hardware | PARTIAL | Signed read-only Serial/ESP32 host contracts. Physical mutation, power-loss recovery and a second hardware family remain pending. |
| M6 Scale / Federation | PENDING | Local locking and protocol drafts are not Controller HA or multi-site authority. |
| M7 Open specification / benchmark | PENDING | Existing RFC/CTK foundations; no complete Verified Reality Benchmark acceptance. |
| M8 Governed evolution | PENDING | Reserved future work; no autonomous deployment or self-approval. |

## Next engineering work

1. Connect Workflow model execution and typed step bindings to existing
   Gateway/AgentSession owners, with original-request accounting and recovery.
2. Qualify one cloud Provider and one local service with explicit account and
   cost authorization. Keep unsupported protocols unavailable.
3. Run the direct developer loop's test step in a qualified strict sandbox.
4. Qualify the current native package on Windows 10 x64.
5. Complete physical device acceptance only when hardware and authorized fault
   testing are available.

External blockers do not justify rebuilding existing Runtime, Workflow,
Registry, Governance or Credential systems.

## Engineering blockers before scale and verified releases

| Issue | Current limitation |
| --- | --- |
| [#88 Windows Skill HTTP](https://github.com/untrod/apeir/issues/88) | Original five-second failures include separate admission, write and commit phases. Read-lock/schema preparation fixes do not prove one cause for every historical timeout. |
| [#116 Windows Context HTTP](https://github.com/untrod/apeir/issues/116) | Main 05e061e4 exceeded the original ten-second deadline during the transfer-revocation case. Slow SQLite close was observed; the full server-side cause is not established. |
| [#4 signed response loss](https://github.com/untrod/apeir/issues/4) / [#8 Relay shutdown](https://github.com/untrod/apeir/issues/8) | Deterministic ordering/stop defects have fixes; retained Windows timing failures still need qualification. |
| [#82 Automation recovery](https://github.com/untrod/apeir/issues/82) | Historical Windows resume lacked an effect-verification verdict; later green runs do not establish its cause. |
| [#85 ProcessSession recovery](https://github.com/untrod/apeir/issues/85) | Original Windows control refusal remains recorded separately from supported-host cleanup fixes. |
| [#2 native components](https://github.com/untrod/apeir/issues/2) | Approved lock migration supplies exact binary inputs; current installation and release acceptance remain separate. |
| [#1 physical hardware](https://github.com/untrod/apeir/issues/1) | Jetson/ESP32 writes, independent physical observations and physical faults need real equipment. |

Failure logs and dated qualification live in
[Engineering Review](docs/acceptance/ENGINEERING_REVIEW.md),
[Known Limitations](docs/acceptance/KNOWN_LIMITATIONS.md) and
[Compute Mesh recovery](docs/operations/compute-mesh/EXECUTION_RECOVERY.md).
Do not close an unexplained timing issue because a retry passed.

## Execution protocol and governance

`main` is the only permanent development branch. Keep at most two short-lived
branches. Use normal PR merges, current required checks and resolved discussions;
preserve accepted SHAs and delete a completed branch only after reachability and
evidence checks. Never force-push main or change historical tags.

The maintainer confirmed corrected main protection on 2026-10-24. Detailed
administration reads remained forbidden to the integration; unobserved settings
are not inferred. The [consolidation record](docs/acceptance/REPOSITORY_CONSOLIDATION.md)
retains the old required-check mismatch, merge observation and screenshots.

## Release discipline

Follow the [Release Runbook](docs/acceptance/RELEASE_RUNBOOK.md). Component
integrity, build, installation and release authorization are independent Gates.
A new document or a successful source test does not change a binary's identity.

The master execution baseline `d955899`, closure audit `ff4d7b4` and immutable
milestone tags remain historical records. Detailed M4–M8 targets are preserved
in Git history and their architecture/RFC documents; this page tracks current
work rather than repeating each development round.

APEIR 1.0 requires exercised remote-human trust, Provider compatibility, physical
effects, fault recovery, public conformance, scale and verified release Gates.
There is no 1.0 readiness claim or production version reservation.

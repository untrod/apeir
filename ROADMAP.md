# APEIR roadmap and milestone status

This is the authoritative current status source. **PASS** means the named Gate
was exercised within its stated scope; **PARTIAL** means implemented portions
remain short of the complete Gate; **PENDING** means acceptance/implementation
has not been performed; **BLOCKED** identifies a concrete unavailable prerequisite.
Dated acceptance records describe historical evidence, not current blanket claims.

Audited Distribution baseline: `ff4d7b4f47b5821f05b3c1a6ef2429847a64cf6d`.
Kernel: `87fd1b2ff28ef14ab1a515a58162592b452fda2e` (frozen).

## Closure matrix

| Milestone / acceptance item | Status | Actual evidence and limits |
| --- | --- | --- |
| M3.1 autonomous coordination | PASS | `1e26d5e`: durable AgentSession, TaskPlan→existing Workflow, event wake/resume and Distributed Work; regression suites `tests/agent_collaboration`, `tests/agent_execution`, `tests/node_runtime`. |
| M3.2 reliability | PASS | `c95029d`: durable delivery/journals, restart/disconnect reconciliation, at-most-once effects; `tests/node_runtime` and recovery/reliability suites. Local durable ownership, not HA. |
| M3.3-A Reality foundation | PASS | `701d053`: stable managed Device identity, registry/graph projection, existing Capability/Observation/EffectVerifier; `tests/reality`. |
| M3.3-B simulated Reality | PASS | `935dcb7`: stateful simulated mutation through Work/Node, independent MATCH, deterministic faults/lost response; [Reality evidence](docs/acceptance/REALITY_ARCHITECTURE_AUDIT.md). |
| M3.3-C real hardware acceptance | PENDING | No complete Jetson→ESP32 physical-effect/observation/commit and physical fault evidence. Historical ARM64 host qualification is not this Gate. |
| M3.4-A Governance Core | PASS | `2fdea90`: four deterministic decisions, durable approval of original Work/Operation, scoped grants, revoke/expire/revalidate/audit; `tests/governance`. |
| M3.4-B Credential Governance | PASS | `26256dd`: execution-bound leases and redaction/leakage negatives; existing approval backend; fake Cloud secrets, not a production secret-store qualification. |
| M3.5 Control Plane software | PASS | `242acf8`: canonical-state API, nonce/session/identity-bound governance, realtime transitions, real-data responsive Operations Console; `tests/control_plane` and Desktop tests. [Contract](docs/architecture/CONTROL_CENTER_SPEC.md). |
| M3.5 real IdP / deployed remote-human qualification | PENDING | Signed fake identity proofs exercise the contract. No live production IdP or Windows enrollment ACL qualification is claimed. |
| M3.6 Developer Platform software | PASS | `6960175`: public canonical SDK, seven conformance suites, protocol/version checks and isolated installed-wheel consumer; [SDK evidence](docs/development/DEVELOPER_PLATFORM.md), `tests/developer_platform`. SDK remains beta, not a production stability promise. |
| Architecture Consolidation Gate | PASS | `070640b`: five canonical documents cover constitution, authority, execution, ownership/failure and Provider model. This consolidation reduces redundant navigation and stale status. |
| M4 Interoperability (complete target) | PARTIAL | Six Provider seams and exercised generic external-agent reference exist; industrial/reference integrations below remain unimplemented/unqualified. |
| M4 generic external-agent / restrictive policy reference | PASS | `05cfbc8`: actual isolated OCI subprocess plus canonical approval/Work/evidence/recovery and simulated downstream Reality; `tests/interoperability`. An external proposal never grants authority. |
| M4 authenticated Codex / industrial Providers | PENDING | Codex CLI discovery/help is not an integration. Ray/Kubernetes, OPA, Vault/OpenBao, SPIFFE/SPIRE, Viam/ROS/KubeEdge are prepared boundaries, not exercised services. |
| M5 Reality & Hardware (complete target) | PARTIAL | Read-only signed SerialTransport/ESP32 host contracts exist. Physical mutation, firmware persistence and a second device family remain missing. |
| M5 serial/ESP32 host-contract preparation | PASS | `ff4d7b4`: 28 focused tests, bounded signed frames/fresh nonce/stable identity/trust preservation; `tests/reality/test_serial_contract.py`. No firmware-write capability advertised. |
| M5 physical ESP32 write / power-loss acceptance | PENDING | Requires real Jetson/ESP32, firmware/NVS behavior and physical fault-injection evidence. |
| M5 second real hardware family | PENDING | No materially different real device family accepted. |
| M6 Scale & Federation | PENDING | Local locking and federation drafts are not Controller HA, multi-site authority, fleet lifecycle, rolling upgrades, quotas or tenant isolation. Implementation must wait for stable M3–M5 contracts. |
| M7 Open Specification & Verified Reality Benchmark | PENDING | Existing RFCs/CTK and generic evaluation machinery are reusable foundations; no evidence-backed Verified Reality Execution Benchmark or complete open-spec Gate exists. |
| Component-lock contract validation | PASS | Existing `tests/repository/test_kernel_component_lock.py`: 3 tests. This checks the lock contract, not native bytes. |
| Native component-lock binary hash validation | BLOCKED | Locked `nousd` and provider-worker Windows x64 binaries are absent. Actual verifier must run before any verified binary release; source CI cannot certify integrity. |

## Next independent Gates

Work from current `main` on one short-lived milestone branch. Complete missing
qualification/hardening in M3.5 and M3.6 first, retaining their accepted software
history. Then review the architecture Gate and add one exercised M4 Provider at
a time. Physical M3.3-C/M5 stays PENDING until hardware exists. Independent
software work may continue while hardware/credentials are unavailable, but M6
implementation starts only after the required core M3–M5 contracts are stable.
M7 formal specifications and reproducible benchmark results follow those contracts.

Example branch names: `feature/m3.5-control-plane`,
`feature/m3.6-developer-platform`, `feature/m4-interoperability`,
`hardware/m5-real-acceptance`, `feature/m6-federation`,
`research/m7-spec-benchmark`. A branch completes one coherent Gate, merges by PR,
receives a scoped acceptance tag where appropriate, and is deleted. `main` is
the only permanent development branch; there is no `develop` branch.

## Release discipline

Distribution remains `0.1.0-rc1`; SDK remains `1.0.0b2` and NKI wrapper `0.1.1`.
There are no published GitHub releases at the audit baseline. Checkpoint tags
preserve evidence and do not create production versions. Do not invent v1.0.
Formal SemVer releases require a sufficiently stable SDK/packaging/compatibility
boundary and [release acceptance](docs/acceptance/RELEASE_RUNBOOK.md), including
actual component hashes, reproducible build metadata, checksums, SBOM and
provenance/attestation where supported. No signing capability is assumed.

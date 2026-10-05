# Repository consolidation audit

Audit baseline: Distribution `ff4d7b4f47b5821f05b3c1a6ef2429847a64cf6d`.
Kernel remains `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
This is a repository/documentation governance change; no Runtime architecture
or Kernel implementation is replaced. The current milestone status lives only
in [ROADMAP](../../ROADMAP.md); dated acceptance records retain their original
scope and counts.

## Read-only GitHub and ancestry audit

Requeried remote heads, all refs, tags, releases, all-state PRs, workflows and
rulesets before mutations. Five branches, no published tags, releases or PRs
were present. `main` was `bfcedd8d2ba358129aa73837be1972962b3e83e7`.
The autonomous branch was 30 ahead/0 behind main; compute-mesh at
`40c1e85cb3e1bf7c7e87b237456dbd9b54966add` was its ancestor, 20 commits behind.
ARM64 at `8bc57dcca2ab6a353c8fb3ab58981cabd0c634a3` was 0 ahead/64 behind main.
Reality-v2 equalled main. GitHub reported admin permission, but the protected
branch endpoint returned HTTP 403 (integration permission limitation).

## Documentation classification before reorganization

The entire documentation tree was inventoried by content and responsibility.
REUSE retains a distinct contract, reference, guide or dated evidence record.
MOVE retains that content in a stable domain. MERGE removes a navigation copy
or redundant current architecture/status description and redirects internal
references to the authoritative owner. DELETE removes obsolete migration/version
promises whose historical copy remains in the checkpoint's Git history.
Protocol/specification drafts retain their scope; they are not implemented M6/M7
or physical acceptance. Stable subdomains contain multiple related references.
No generic archive is created.

| Original document | Classification | Canonical destination / reason |
| --- | --- | --- |
| `docs/ARCHITECTURE.md` | MERGE | `docs/architecture/README.md` |
| `docs/INSTALL.md` | MERGE | `docs/operations/INSTALLATION.md` |
| `docs/README.md` | REUSE | `docs/README.md` |
| `docs/SECURITY.md` | MERGE | `SECURITY.md` |
| `docs/USER_GUIDE.md` | MERGE | `docs/operations/USER_GUIDE.md` |
| `docs/adr/ADR-0001-kernel-next-architecture.md` | MOVE | `docs/rfc/adr/ADR-0001-kernel-next-architecture.md` |
| `docs/adr/ADR-0002-event-ledger-authority.md` | MOVE | `docs/rfc/adr/ADR-0002-event-ledger-authority.md` |
| `docs/adr/ADR-0003-governed-network-authority.md` | MOVE | `docs/rfc/adr/ADR-0003-governed-network-authority.md` |
| `docs/architecture/ARCHITECTURE.md` | MERGE | `docs/architecture/README.md` |
| `docs/architecture/ARCHITECTURE_OVERVIEW.md` | MERGE | `docs/architecture/RUNTIME_COORDINATION.md` |
| `docs/architecture/ARTIFACT_POLICY.md` | REUSE | `docs/architecture/ARTIFACT_POLICY.md` |
| `docs/architecture/CAPABILITY_CONTRACT.md` | REUSE | `docs/architecture/CAPABILITY_CONTRACT.md` |
| `docs/architecture/CLAIM_EVIDENCE_CONTRACT.md` | REUSE | `docs/architecture/CLAIM_EVIDENCE_CONTRACT.md` |
| `docs/architecture/CLI_ARCHITECTURE.md` | REUSE | `docs/architecture/CLI_ARCHITECTURE.md` |
| `docs/architecture/COMPATIBILITY_POLICY.md` | REUSE | `docs/architecture/COMPATIBILITY_POLICY.md` |
| `docs/architecture/COMPONENT_DEPENDENCIES.md` | REUSE | `docs/architecture/COMPONENT_DEPENDENCIES.md` |
| `docs/architecture/CONTROL_CENTER_ALIGNMENT.md` | REUSE | `docs/architecture/CONTROL_CENTER_ALIGNMENT.md` |
| `docs/architecture/CONTROL_CENTER_SPEC.md` | REUSE | `docs/architecture/CONTROL_CENTER_SPEC.md` |
| `docs/architecture/DESKTOP_ARCHITECTURE.md` | REUSE | `docs/architecture/DESKTOP_ARCHITECTURE.md` |
| `docs/architecture/DISTRIBUTION.md` | REUSE | `docs/architecture/DISTRIBUTION.md` |
| `docs/architecture/ERROR_MODEL.md` | REUSE | `docs/architecture/ERROR_MODEL.md` |
| `docs/architecture/EXECUTION_CONTRACT.md` | MERGE | `docs/architecture/EXECUTION_PATH.md` |
| `docs/architecture/EXECUTION_PATH.md` | REUSE | `docs/architecture/EXECUTION_PATH.md` |
| `docs/architecture/FOUNDATION_1_0.md` | REUSE | `docs/architecture/FOUNDATION_1_0.md` |
| `docs/architecture/GLOSSARY.md` | REUSE | `docs/architecture/GLOSSARY.md` |
| `docs/architecture/GOVERNED_DOCUMENT_RUNTIME.md` | REUSE | `docs/architecture/GOVERNED_DOCUMENT_RUNTIME.md` |
| `docs/architecture/GOVERNED_ENVIRONMENT_RUNTIME.md` | REUSE | `docs/architecture/GOVERNED_ENVIRONMENT_RUNTIME.md` |
| `docs/architecture/GOVERNED_NETWORK_GATEWAY.md` | REUSE | `docs/architecture/GOVERNED_NETWORK_GATEWAY.md` |
| `docs/architecture/GOVERNED_SCIENTIFIC_RUNTIME.md` | REUSE | `docs/architecture/GOVERNED_SCIENTIFIC_RUNTIME.md` |
| `docs/architecture/GOVERNED_SIMULATION_RUNTIME.md` | REUSE | `docs/architecture/GOVERNED_SIMULATION_RUNTIME.md` |
| `docs/architecture/KERNEL_ARCHITECTURE_V1.md` | DELETE | `docs/architecture/DISTRIBUTION.md` |
| `docs/architecture/KERNEL_MODULE_MAP_V2.md` | MOVE | `docs/development/RUNTIME_MODULE_MAP.md` |
| `docs/architecture/LAYERS.md` | MERGE | `docs/architecture/DISTRIBUTION.md` |
| `docs/architecture/LEARNING_DOMAIN_MIGRATION.md` | DELETE | `docs/development/LEGACY_COMPATIBILITY.md` |
| `docs/architecture/NETWORK_EGRESS_CONTRACT.md` | REUSE | `docs/architecture/NETWORK_EGRESS_CONTRACT.md` |
| `docs/architecture/OBJECT_MODEL.md` | REUSE | `docs/architecture/OBJECT_MODEL.md` |
| `docs/architecture/OBSERVATION_LAYER.md` | REUSE | `docs/architecture/OBSERVATION_LAYER.md` |
| `docs/architecture/PACK_SPEC_V1.md` | REUSE | `docs/architecture/PACK_SPEC_V1.md` |
| `docs/architecture/PROCESS_MODEL.md` | REUSE | `docs/architecture/PROCESS_MODEL.md` |
| `docs/architecture/PROJECT_RUNTIME.md` | REUSE | `docs/architecture/PROJECT_RUNTIME.md` |
| `docs/architecture/PROVIDER_CONTRACT.md` | REUSE | `docs/architecture/PROVIDER_CONTRACT.md` |
| `docs/architecture/README.md` | REUSE | `docs/architecture/README.md` |
| `docs/architecture/REALITY_ARCHITECTURE_AUDIT.md` | MOVE | `docs/acceptance/REALITY_ARCHITECTURE_AUDIT.md` |
| `docs/architecture/REGISTRY_CONTRACT.md` | REUSE | `docs/architecture/REGISTRY_CONTRACT.md` |
| `docs/architecture/REGISTRY_SPEC.md` | REUSE | `docs/architecture/REGISTRY_SPEC.md` |
| `docs/architecture/RUNTIME_ARCHITECTURE_RC2.md` | MERGE | `docs/architecture/STATE_OWNERSHIP.md` |
| `docs/architecture/RUNTIME_BOUNDARY.md` | MERGE | `docs/architecture/DISTRIBUTION.md` |
| `docs/architecture/RUNTIME_COORDINATION.md` | REUSE | `docs/architecture/RUNTIME_COORDINATION.md` |
| `docs/architecture/SECURITY_BOUNDARY.md` | REUSE | `docs/architecture/SECURITY_BOUNDARY.md` |
| `docs/architecture/SECURITY_CONTRACT.md` | REUSE | `docs/architecture/SECURITY_CONTRACT.md` |
| `docs/architecture/SECURITY_HARDENING.md` | REUSE | `docs/architecture/SECURITY_HARDENING.md` |
| `docs/architecture/SOFTWARE_DESIGN.md` | DELETE | `docs/architecture/README.md` |
| `docs/architecture/STATE_OWNERSHIP.md` | REUSE | `docs/architecture/STATE_OWNERSHIP.md` |
| `docs/architecture/SYSTEM_MAP.md` | REUSE | `docs/architecture/SYSTEM_MAP.md` |
| `docs/architecture/intelligence/EXECUTION_MODEL.md` | REUSE | `docs/architecture/intelligence/EXECUTION_MODEL.md` |
| `docs/architecture/intelligence/PLANNER.md` | REUSE | `docs/architecture/intelligence/PLANNER.md` |
| `docs/architecture/intelligence/PROVIDER_ROUTING.md` | REUSE | `docs/architecture/intelligence/PROVIDER_ROUTING.md` |
| `docs/compatibility/BREAKING_CHANGES.md` | MOVE | `docs/development/BREAKING_CHANGES.md` |
| `docs/compatibility/VERSIONING_POLICY.md` | MOVE | `docs/development/VERSIONING_POLICY.md` |
| `docs/compute-mesh/DISTRIBUTED_EXECUTION.md` | MOVE | `docs/operations/compute-mesh/DISTRIBUTED_EXECUTION.md` |
| `docs/compute-mesh/DISTRIBUTED_WORK.md` | MOVE | `docs/operations/compute-mesh/DISTRIBUTED_WORK.md` |
| `docs/compute-mesh/EXECUTION_RECOVERY.md` | MOVE | `docs/operations/compute-mesh/EXECUTION_RECOVERY.md` |
| `docs/compute-mesh/JETSON_NODE_SETUP.md` | MOVE | `docs/operations/compute-mesh/JETSON_NODE_SETUP.md` |
| `docs/compute-mesh/OPERATIONS.md` | MOVE | `docs/operations/compute-mesh/OPERATIONS.md` |
| `docs/compute-mesh/RECOVERY_MATRIX.md` | MOVE | `docs/operations/compute-mesh/RECOVERY_MATRIX.md` |
| `docs/compute-mesh/WORK_LIFECYCLE.md` | MOVE | `docs/operations/compute-mesh/WORK_LIFECYCLE.md` |
| `docs/development/API_COMPATIBILITY_LEGACY.md` | REUSE | `docs/development/API_COMPATIBILITY_LEGACY.md` |
| `docs/development/API_REFERENCE.md` | REUSE | `docs/development/API_REFERENCE.md` |
| `docs/development/CLI_REFERENCE.md` | REUSE | `docs/development/CLI_REFERENCE.md` |
| `docs/development/COMPATIBILITY_MATRIX.md` | REUSE | `docs/development/COMPATIBILITY_MATRIX.md` |
| `docs/development/DEPRECATION_POLICY.md` | REUSE | `docs/development/DEPRECATION_POLICY.md` |
| `docs/development/DEVELOPER_PLATFORM.md` | REUSE | `docs/development/DEVELOPER_PLATFORM.md` |
| `docs/development/ECOSYSTEM.md` | REUSE | `docs/development/ECOSYSTEM.md` |
| `docs/development/FOUNDATION_DEVELOPMENT.md` | REUSE | `docs/development/FOUNDATION_DEVELOPMENT.md` |
| `docs/development/GETTING_STARTED.md` | REUSE | `docs/development/GETTING_STARTED.md` |
| `docs/development/LEGACY_COMPATIBILITY.md` | REUSE | `docs/development/LEGACY_COMPATIBILITY.md` |
| `docs/development/PACK_DEVELOPMENT.md` | REUSE | `docs/development/PACK_DEVELOPMENT.md` |
| `docs/development/PROVIDER_DEVELOPMENT.md` | REUSE | `docs/development/PROVIDER_DEVELOPMENT.md` |
| `docs/development/README.md` | REUSE | `docs/development/README.md` |
| `docs/development/WRITE_A_MODULE.md` | REUSE | `docs/development/WRITE_A_MODULE.md` |
| `docs/development/WRITE_A_PROVIDER.md` | REUSE | `docs/development/WRITE_A_PROVIDER.md` |
| `docs/development/community/BETA_TEST_TEMPLATE.md` | MOVE | `docs/development/BETA_TEST_TEMPLATE.md` |
| `docs/development/community/GOVERNANCE.md` | MOVE | `docs/development/GOVERNANCE.md` |
| `docs/development/community/MAINTAINERS.md` | MERGE | `MAINTAINERS.md` |
| `docs/development/design/PACK_MODEL.md` | MOVE | `docs/development/PACK_MODEL.md` |
| `docs/development/rfcs/0000-template.md` | MOVE | `docs/rfc/0000-template.md` |
| `docs/development/standards/README.md` | DELETE | `docs/rfc/README.md` |
| `docs/kernel/EXECUTION_PATHS.md` | MOVE | `docs/architecture/kernel/EXECUTION_PATHS.md` |
| `docs/kernel/TRUSTED_COMPUTING_BASE.md` | MOVE | `docs/architecture/kernel/TRUSTED_COMPUTING_BASE.md` |
| `docs/platform/WINDOWS_ARM64_NATIVE_QUALIFICATION.md` | MOVE | `docs/acceptance/WINDOWS_ARM64_NATIVE_QUALIFICATION.md` |
| `docs/protocol/ESP32_SDK.md` | MOVE | `docs/architecture/protocol/ESP32_SDK.md` |
| `docs/protocol/MESSAGE_ENVELOPE.md` | MOVE | `docs/architecture/protocol/MESSAGE_ENVELOPE.md` |
| `docs/protocol/NEP_SPEC.md` | MOVE | `docs/architecture/protocol/NEP_SPEC.md` |
| `docs/protocol/NFP_SPEC.md` | MOVE | `docs/architecture/protocol/NFP_SPEC.md` |
| `docs/protocol/NKP_SPEC.md` | MOVE | `docs/architecture/protocol/NKP_SPEC.md` |
| `docs/protocol/NOUS_PROTOCOL_OVERVIEW.md` | MOVE | `docs/architecture/protocol/NOUS_PROTOCOL_OVERVIEW.md` |
| `docs/protocol/NSP_SPEC.md` | MOVE | `docs/architecture/protocol/NSP_SPEC.md` |
| `docs/reference/ERROR_MODEL.md` | MOVE | `docs/architecture/kernel/ERROR_MODEL.md` |
| `docs/release/APEIR_0_1_BASELINE.md` | MOVE | `docs/acceptance/APEIR_0_1_BASELINE.md` |
| `docs/release/API_V1_FREEZE.md` | MOVE | `docs/acceptance/API_V1_FREEZE.md` |
| `docs/release/KNOWN_LIMITATIONS.md` | MOVE | `docs/acceptance/KNOWN_LIMITATIONS.md` |
| `docs/release/PUBLIC_RELEASE_CHECKLIST.md` | MOVE | `docs/acceptance/PUBLIC_RELEASE_CHECKLIST.md` |
| `docs/release/R6_BASELINE.md` | MOVE | `docs/acceptance/R6_BASELINE.md` |
| `docs/release/R6_LAPTOP_CHECKPOINT.md` | MOVE | `docs/acceptance/R6_LAPTOP_CHECKPOINT.md` |
| `docs/release/README.md` | MOVE | `docs/acceptance/README.md` |
| `docs/release/RELEASE_CHECKLIST.md` | MERGE | `docs/acceptance/PUBLIC_RELEASE_CHECKLIST.md` |
| `docs/release/RELEASE_NOTES_0.1.0-rc1.md` | MOVE | `docs/acceptance/RELEASE_NOTES_0.1.0-rc1.md` |
| `docs/release/RELEASE_PROCESS.md` | MERGE | `docs/acceptance/RELEASE_RUNBOOK.md` |
| `docs/release/RELEASE_RUNBOOK.md` | MOVE | `docs/acceptance/RELEASE_RUNBOOK.md` |
| `docs/release/VALIDATION_MATRIX.md` | MOVE | `docs/acceptance/VALIDATION_MATRIX.md` |
| `docs/rfc/RFC-0001-KERNEL-BOUNDARY.md` | REUSE | `docs/rfc/RFC-0001-KERNEL-BOUNDARY.md` |
| `docs/rfc/RFC-0002-KERNEL-OBJECT-MODEL.md` | REUSE | `docs/rfc/RFC-0002-KERNEL-OBJECT-MODEL.md` |
| `docs/rfc/RFC-0003-WORKLOAD-IR.md` | REUSE | `docs/rfc/RFC-0003-WORKLOAD-IR.md` |
| `docs/rfc/RFC-0004-NKI-V1.md` | REUSE | `docs/rfc/RFC-0004-NKI-V1.md` |
| `docs/rfc/RFC-0005-ENGINE-ABI.md` | REUSE | `docs/rfc/RFC-0005-ENGINE-ABI.md` |
| `docs/rfc/RFC-0005-rc8-agent-process-kernel.md` | REUSE | `docs/rfc/RFC-0005-rc8-agent-process-kernel.md` |
| `docs/rfc/RFC-0006-DEVICE-ABI.md` | REUSE | `docs/rfc/RFC-0006-DEVICE-ABI.md` |
| `docs/rfc/RFC-0007-MEMORY-FABRIC.md` | REUSE | `docs/rfc/RFC-0007-MEMORY-FABRIC.md` |
| `docs/rfc/RFC-0008-RESOURCE-MODEL.md` | REUSE | `docs/rfc/RFC-0008-RESOURCE-MODEL.md` |
| `docs/rfc/RFC-0009-SCHEDULER.md` | REUSE | `docs/rfc/RFC-0009-SCHEDULER.md` |
| `docs/rfc/RFC-0010-SECURITY.md` | REUSE | `docs/rfc/RFC-0010-SECURITY.md` |
| `docs/rfc/RFC-0011-STATE-RECOVERY.md` | REUSE | `docs/rfc/RFC-0011-STATE-RECOVERY.md` |
| `docs/rfc/RFC-0012-MODEL-PACKAGE.md` | REUSE | `docs/rfc/RFC-0012-MODEL-PACKAGE.md` |
| `docs/rfc/RFC-0013-AGENT-PROGRAM.md` | REUSE | `docs/rfc/RFC-0013-AGENT-PROGRAM.md` |
| `docs/rfc/RFC-0014-CONFORMANCE.md` | REUSE | `docs/rfc/RFC-0014-CONFORMANCE.md` |
| `docs/rfc/zh/README.md` | REUSE | `docs/rfc/zh/README.md` |
| `docs/rfc/zh/RFC-0001-内核边界.md` | REUSE | `docs/rfc/zh/RFC-0001-内核边界.md` |
| `docs/rfc/zh/RFC-0002-内核对象模型.md` | REUSE | `docs/rfc/zh/RFC-0002-内核对象模型.md` |
| `docs/rfc/zh/RFC-0003-Workload-IR.md` | REUSE | `docs/rfc/zh/RFC-0003-Workload-IR.md` |
| `docs/roadmap/README.md` | MERGE | `ROADMAP.md` |
| `docs/security/ABUSE_CASES.md` | MOVE | `docs/architecture/security/ABUSE_CASES.md` |
| `docs/security/OVERVIEW.md` | MOVE | `docs/architecture/security/OVERVIEW.md` |
| `docs/security/PACK_TRUST_MODEL.md` | MOVE | `docs/architecture/security/PACK_TRUST_MODEL.md` |
| `docs/security/README.md` | MOVE | `docs/architecture/security/README.md` |
| `docs/security/SECURITY_CHECKLIST.md` | MOVE | `docs/architecture/security/SECURITY_CHECKLIST.md` |
| `docs/security/SUPPLY_CHAIN_SECURITY.md` | MOVE | `docs/architecture/security/SUPPLY_CHAIN_SECURITY.md` |
| `docs/security/THREAT_MODEL.md` | MOVE | `docs/architecture/security/THREAT_MODEL.md` |
| `docs/security/TRUST_BOUNDARIES.md` | MOVE | `docs/architecture/security/TRUST_BOUNDARIES.md` |
| `docs/specs/ACCESS_CLIENT_SPEC.md` | MOVE | `docs/architecture/specs/ACCESS_CLIENT_SPEC.md` |
| `docs/specs/CANDIDATE_MODEL_SPEC.md` | MOVE | `docs/architecture/specs/CANDIDATE_MODEL_SPEC.md` |
| `docs/specs/CAPABILITY_SPEC.md` | MOVE | `docs/architecture/specs/CAPABILITY_SPEC.md` |
| `docs/specs/CIRCUIT_BREAKER_SPEC.md` | MOVE | `docs/architecture/specs/CIRCUIT_BREAKER_SPEC.md` |
| `docs/specs/CONTINUATION_PROTOCOL_SPEC.md` | MOVE | `docs/architecture/specs/CONTINUATION_PROTOCOL_SPEC.md` |
| `docs/specs/DECISION_LIFECYCLE_SPEC.md` | MOVE | `docs/architecture/specs/DECISION_LIFECYCLE_SPEC.md` |
| `docs/specs/DECISION_OUTCOME_SPEC.md` | MOVE | `docs/architecture/specs/DECISION_OUTCOME_SPEC.md` |
| `docs/specs/DECISION_SCORING_SPEC.md` | MOVE | `docs/architecture/specs/DECISION_SCORING_SPEC.md` |
| `docs/specs/DECISION_STORE_SPEC.md` | MOVE | `docs/architecture/specs/DECISION_STORE_SPEC.md` |
| `docs/specs/DEVICE_CREDENTIAL_LIFECYCLE_SPEC.md` | MOVE | `docs/architecture/specs/DEVICE_CREDENTIAL_LIFECYCLE_SPEC.md` |
| `docs/specs/FAILURE_CLASSIFICATION_SPEC.md` | MOVE | `docs/architecture/specs/FAILURE_CLASSIFICATION_SPEC.md` |
| `docs/specs/FEDERATION_SPEC.md` | MOVE | `docs/architecture/specs/FEDERATION_SPEC.md` |
| `docs/specs/LONG_RUNNING_PROJECT_SPEC.md` | MOVE | `docs/architecture/specs/LONG_RUNNING_PROJECT_SPEC.md` |
| `docs/specs/MODEL_PROFILE_SPEC.md` | MOVE | `docs/architecture/specs/MODEL_PROFILE_SPEC.md` |
| `docs/specs/MODULE_SPEC.md` | MOVE | `docs/architecture/specs/MODULE_SPEC.md` |
| `docs/specs/NODE_IDENTITY_SPEC.md` | MOVE | `docs/architecture/specs/NODE_IDENTITY_SPEC.md` |
| `docs/specs/POLICY_RUNTIME_SPEC.md` | MOVE | `docs/architecture/specs/POLICY_RUNTIME_SPEC.md` |
| `docs/specs/PROFILE_STORE_SPEC.md` | MOVE | `docs/architecture/specs/PROFILE_STORE_SPEC.md` |
| `docs/specs/PROVIDER_PROFILE_SPEC.md` | MOVE | `docs/architecture/specs/PROVIDER_PROFILE_SPEC.md` |
| `docs/specs/PUBLIC_NETWORK_SECURITY_SPEC.md` | MOVE | `docs/architecture/specs/PUBLIC_NETWORK_SECURITY_SPEC.md` |
| `docs/specs/RELAY_PROTOCOL_SPEC.md` | MOVE | `docs/architecture/specs/RELAY_PROTOCOL_SPEC.md` |
| `docs/specs/RETRIEVAL_SPEC.md` | MOVE | `docs/architecture/specs/RETRIEVAL_SPEC.md` |
| `docs/specs/RETRY_POLICY_SPEC.md` | MOVE | `docs/architecture/specs/RETRY_POLICY_SPEC.md` |
| `docs/specs/RUNTIME_INTELLIGENCE_SPEC.md` | MOVE | `docs/architecture/specs/RUNTIME_INTELLIGENCE_SPEC.md` |
| `docs/specs/SCHEDULING_ENGINE_SPEC.md` | MOVE | `docs/architecture/specs/SCHEDULING_ENGINE_SPEC.md` |
| `docs/specs/SELF_DEVELOPMENT_PIPELINE_SPEC.md` | MOVE | `docs/architecture/specs/SELF_DEVELOPMENT_PIPELINE_SPEC.md` |
| `docs/specs/TASK_DELIVERY_SPEC.md` | MOVE | `docs/architecture/specs/TASK_DELIVERY_SPEC.md` |
| `docs/specs/UPDATE_AND_ROLLBACK_SPEC.md` | MOVE | `docs/architecture/specs/UPDATE_AND_ROLLBACK_SPEC.md` |
| `docs/specs/WORKSPACE_RUNTIME_SPEC.md` | MOVE | `docs/architecture/specs/WORKSPACE_RUNTIME_SPEC.md` |
| `docs/user/CAPABILITY_AVAILABILITY.md` | MOVE | `docs/operations/CAPABILITY_AVAILABILITY.md` |
| `docs/user/FAQ.md` | MOVE | `docs/operations/FAQ.md` |
| `docs/user/INSTALLATION.md` | MOVE | `docs/operations/INSTALLATION.md` |
| `docs/user/LOCAL_MEMORY.md` | MOVE | `docs/operations/LOCAL_MEMORY.md` |
| `docs/user/MIGRATION_GUIDE.md` | MERGE | `docs/development/LEGACY_COMPATIBILITY.md` |
| `docs/user/PROJECTS.md` | MOVE | `docs/operations/PROJECTS.md` |
| `docs/user/README.md` | MOVE | `docs/operations/README.md` |
| `docs/user/TERMINAL_EXPERIENCE.md` | MOVE | `docs/operations/TERMINAL_EXPERIENCE.md` |
| `docs/user/USER_GUIDE.md` | MOVE | `docs/operations/USER_GUIDE.md` |
| `docs/user/configuration/CONFIG_REFERENCE.md` | MOVE | `docs/operations/configuration/CONFIG_REFERENCE.md` |
| `docs/user/deployment/DEPLOYMENT.md` | MOVE | `docs/operations/deployment/DEPLOYMENT.md` |
| `docs/user/deployment/README.md` | MOVE | `docs/operations/deployment/README.md` |
| `docs/user/deployment/WINDOWS_10_ARM64_LOCAL.md` | MOVE | `docs/operations/deployment/WINDOWS_10_ARM64_LOCAL.md` |
| `docs/user/deployment/WINDOWS_10_X64_LAUNCHER.md` | MOVE | `docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md` |
| `docs/user/getting-started/INSTALL_DOCKER.md` | MOVE | `docs/operations/getting-started/INSTALL_DOCKER.md` |
| `docs/user/getting-started/INSTALL_LINUX.md` | MOVE | `docs/operations/getting-started/INSTALL_LINUX.md` |
| `docs/user/getting-started/INSTALL_MACOS.md` | MOVE | `docs/operations/getting-started/INSTALL_MACOS.md` |
| `docs/user/getting-started/INSTALL_WINDOWS.md` | MOVE | `docs/operations/getting-started/INSTALL_WINDOWS.md` |
| `docs/user/getting-started/PLATFORM_FIRST_RUN.md` | MOVE | `docs/operations/getting-started/PLATFORM_FIRST_RUN.md` |
| `docs/user/getting-started/QUICK_START.md` | MOVE | `docs/operations/getting-started/QUICK_START.md` |
| `docs/user/getting-started/TROUBLESHOOTING.md` | MOVE | `docs/operations/getting-started/TROUBLESHOOTING.md` |
| `docs/user/guides/CLI_GUIDE.md` | MOVE | `docs/operations/guides/CLI_GUIDE.md` |
| `docs/user/guides/PACK_GUIDE.md` | MOVE | `docs/operations/guides/PACK_GUIDE.md` |
| `docs/user/guides/PROVIDER_GUIDE.md` | MOVE | `docs/operations/guides/PROVIDER_GUIDE.md` |
| `docs/user/guides/USER_GUIDE.md` | MOVE | `docs/operations/guides/USER_GUIDE.md` |
| `docs/user/platform/PLATFORM_SUPPORT_POLICY.md` | MOVE | `docs/operations/platform/PLATFORM_SUPPORT_POLICY.md` |

## GitHub governance and CI audit

Added root AGENTS entrypoint and refreshed README, ROADMAP, CONTRIBUTING and
SECURITY with distinct responsibilities. PR template covers milestone,
architecture/authority, failure, security, hardware, tests/baselines, docs and
Kernel impact. Issue templates cover bug, feature, RFC, Provider and hardware;
security disclosure links privately to Advisories. Four labels were added:
`rfc`, `provider`, `hardware`, `security`; existing bug/enhancement labels reused.
Physical acceptance is tracked in [issue 1](https://github.com/untrod/apeir/issues/1),
native component bytes in [issue 2](https://github.com/untrod/apeir/issues/2).

The two previous workflows duplicated full Python tests and hygiene across
platforms, lacked explicit minimal permissions/retention, and called an x64
metadata check Windows ARM64 cross-compilation. Responsibilities are now:

| Workflow | Scope |
| --- | --- |
| Core CI | Full PR Linux regression; broader four-platform/Python matrix on push/main; stable Core gate |
| Desktop CI | Frontend lint/tests/typecheck/build; separately gated native packaging, actual locked-byte preflight |
| Multi-Arch CI | Main/release or explicit dispatch: native Linux amd64/ARM64 Python/wheels, Windows x64, clearly named ARM64 metadata and Lite checks; separate architecture SBOMs |
| Security and Supply Chain | Ruff, changed-source format, compile, document/link/identity/security/version checks, lock contract and explicit source-only native status |
| Release Preflight | Manual actual native hash verifier; fails without staged locked bytes; no publication or invented version |

Actions use read-only contents permissions; build artifacts retain 14 days.
Main runs are not cancelled by later pushes. No untrusted pull_request_target
execution or production secret input is introduced. No new validation framework
or artificial smoke substitute replaces the existing regression suites.

## Settings requiring maintainer action

Current integration can read repository metadata and create labels/issues/tags,
but branch-protection REST/GraphQL reads, ruleset POSTs and repository-settings
PATCH returned HTTP 403. **No new main/tag protection or merge-setting change
was applied.** Existing main protection was visible on branch metadata, but its
required contexts could not be inspected. No personal token/workaround is used.

Apply these settings in GitHub Settings → Rules → Rulesets:

- Active main branch ruleset, target `refs/heads/main`: require PR, zero mandatory
  reviewer approvals, resolve all conversations, require `Core gate`,
  `Repository checks`, `Frontend Build Validation`, and require current-base CI.
  Block force pushes and deletion. No signed-commit requirement; no bypass actor.
- Active tag ruleset, targets `refs/tags/milestone/*` and `refs/tags/v*`:
  block update and deletion of published tags. Creation remains permitted.
- Repository merge settings: allow merge commits; disable squash/rebase for
  accepted milestone history. Keep main the only permanent development branch.

If old required contexts reference the removed duplicate Python/hygiene jobs,
replace them with the three stable contexts above; do not bypass a failing Gate.
Review signing support and release provenance only when actually qualified.

## Preserved immutable checkpoints

| Tag | Distribution commit | Scope |
| --- | --- | --- |
| `milestone/arm64-lab` | `8bc57dcca2ab6a353c8fb3ab58981cabd0c634a3` | Historical ARM64 Lab, not ESP32 physical acceptance |
| `milestone/distributed-execution-v0.2` | `40c1e85cb3e1bf7c7e87b237456dbd9b54966add` | Accepted compute-mesh history, including pipeline and discovery corrections |
| `milestone/m3.4-b-software` | `26256dd0cef1ca632625cf54a38e72157e676164` | Credential Governance software/fake-secret acceptance |
| `milestone/m5-host-contract` | `ff4d7b4f47b5821f05b3c1a6ef2429847a64cf6d` | Read-only host preparation, physical acceptance PENDING |
| `milestone/pre-consolidation-main` | `bfcedd8d2ba358129aa73837be1972962b3e83e7` | Main before integration |

Tags were created only after requery confirmed none existed; remote objects
were fetched locally. No historical commit, tag or Kernel file was rewritten.

## Validation and baseline preservation

The first full local run reported **3653 passed, 35 skipped, 14 failed,
4 warnings**. Five failures were consolidation regressions: README omitted its
existing local-first contract and four documentation-existence assertions still
pointed at removed forwarding pages. README was corrected and those assertions
now require the actual canonical files; none was skipped/weakened. The initial
failure log is retained outside source. Repository/productization/hygiene
regressions then passed **272 tests**.

The other nine failures match the previously reproduced managed-Cloud baseline:

- `tests/extensions/test_mcp_sdk_execution.py::test_stdio_bridge_runs_only_through_strong_policy_without_permit_egress` (managed interpreter path)
- `tests/test_production_suite.py::TestDesktopApiEndpoints::test_automations_crud`
- `tests/test_production_suite.py::TestDesktopApiEndpoints::test_knowledge_crud`
- `tests/test_production_suite.py::TestDaemonStability::test_service_start_stop`
- `tests/test_production_suite.py::TestLongRunningStability::test_automations_persistence_under_stress`
- `tests/test_rc_validation.py::TestDesktopApiContract::test_automations_crud`
- `tests/test_rc_validation.py::TestDesktopApiContract::test_knowledge_crud`
- `tests/tools/test_process_session.py::test_child_process_is_cleaned_up_with_parent`
- `tests/tools/test_process_session.py::test_natural_parent_exit_does_not_leave_child`

The API/daemon failures require writable user-home state unavailable in this
managed environment; process tests expose its container orphan-cleanup limits.
These are retained, not rewritten as part of repository governance. Hosted CI
exercises its own environment and must pass independently. Native hash verifier
was actually invoked and raised FileNotFoundError for the locked Windows x64
Kernel binary; its status is BLOCKED, not success. The lock contract's three
tests passed. Kernel/component lock and Runtime implementation remain unchanged.
The follow-up SDK export change described below is formatting only.

Final local full regression: **3657 passed, 35 skipped, 10 failed, 4 warnings**
(3702 collected). Nine are the confirmed baseline failures above. The additional
failure was the unchanged
`tests/reality/test_simulated_execution.py::test_response_loss_restart_reconciles_persisted_result_and_fresh_observation_without_replay[lost_response-0-FAILED]`:
its three-second restored-run wait observed RUNNING before expected FAILED.
This is **not classified as a confirmed baseline failure**. The same test file's
blob is `a7cf657d1b9b93843b3cff4b4e6ade7abf16f911` at the accepted baseline and in
this worktree, and Runtime code is unchanged. Its two parameters passed an
isolated diagnostic rerun (**2 passed**); the full affected suite also passed
**738 tests**, including real OCI reference execution with fake credentials.
The failed full log is retained; no timeout/assertion is changed for consolidation.
Hosted PR/main regression must be assessed separately; no local full PASS is claimed.

Frontend: **47 tests / 25 files passed**, ESLint, TypeScript and production build
passed. Ruff, changed-Python formatting (3 files), compile, document hygiene,
**232 Markdown link checks**, comment/identity/Git checks, security scan
(**0 findings**) and release version consistency (**8 manifests**) passed.
Component-lock contract: **3 passed**; native verifier: **BLOCKED** as recorded.
The three existing documentation contract tests files changed paths/format only;
they continue asserting canonical files and public-data boundaries.

## PR validation correction

Initial PR Security CI [37336060701](https://github.com/untrod/apeir/actions/runs/37336060701)
failed its new history-wide changed-file format check: 76 files were formatted,
but the accepted SDK `nous_provider/__init__.py` still had noncanonical spacing/line wrapping.
This formatting finding is preserved rather than suppressed. Only that file’s formatting
was normalized; before/after Python ASTs are identical. No SDK contract or
Runtime behavior changed. Public SDK regressions validate the correction.

Previously published `Python Tests (...)` and `Public repository hygiene` check
names are preserved in their new owner workflows so migration does not orphan
existing required contexts. `Core gate` and `Repository checks` aggregate actual
job results for the recommended future ruleset; they cannot pass failed/skipped
validation. The new failed run and any earlier runs cancelled by the corrective
push remain visible in GitHub. The intermittent recovery test is tracked in
[issue 4](https://github.com/untrod/apeir/issues/4), separately from confirmed baselines.

After the formatting-only correction, SDK/Reality regressions passed **102 tests**
with loopback-network permission. An initial SDK-only invocation without that
permission had **13 passed, 1 failed** because its simulation could not bind
127.0.0.1; its original log is retained separately from test/code failures.
History-wide changed-source formatting now passes **77 Python files**.

The next PR Security run
[37336900912](https://github.com/untrod/apeir/actions/runs/37336900912)
passed formatting and then found a genuine repository-checker defect: human
`git branch -a` display text classified detached HEAD and GitHub's generated
`remotes/pull/3/merge` as contributor branches. The existing metadata auditor now
reads actual head/remote refs. It recognizes only exact numeric GitHub PR head/merge
refs and remote HEAD aliases; local or disguised pull branches still fail naming
checks. Forbidden prefixes apply across named remotes and symbolic contributor
branches. `hardware/` is supported, main is exact, and Git command failures cannot
silently become empty successful audits. No Runtime execution path changes.

Ten meaningful repository contract regressions cover these positive/negative
cases using real temporary Git refs. The repository suite passes **248 tests**.
The failed CI run remains published; the fix does not skip Git metadata auditing.

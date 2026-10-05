# Provider model and contract

A Provider supplies a bounded replaceable implementation. APEIR owns heterogeneous
execution semantics, governance, Work/Operation lifecycle, evidence, observation,
effect verification and recovery. Reuse mature external agent harnesses, cluster
schedulers, policy engines, secret stores, identity systems and device ecosystems
instead of rebuilding them as competing authorities.

## Roles and existing boundaries

| Role | Existing authoritative path | Authority constraint |
| --- | --- | --- |
| Intelligence | Model Gateway, existing Provider adapters and Agent planning | Output is a proposal/observation, never approval |
| Execution | admitted Runtime capability or Distributed Work/Node; NPA engine for Kernel scope | Placement and callbacks cannot grant execution authority |
| Policy | existing ApprovalPolicy/PermissionEngine/Operation Gate and policy inputs | An external result cannot bypass Core deny/UNKNOWN or issue a grant |
| Secret | existing SecretBackend and CredentialBroker | Resolve only for current authorized scoped Operation; no general Provider store access |
| Identity | existing Node identity/trust and trusted human-session boundary | Identity evidence is verified by the configured trust boundary; self-declaration is insufficient |
| Device | existing DeviceProvider/DeviceTransport and Reality contracts | Discovery is not trust; a locator is not identity; receipt is not state observation |

These roles describe ownership boundaries, not six newly implemented systems.
External Codex, Ray/Kubernetes, OPA, OpenBao/Vault, SPIFFE/SPIRE and
Viam/ROS/KubeEdge integrations need explicit implementation and exercised
conformance before being called supported. A local class named VaultSecretBackend
is not evidence of an exercised external Vault service.

## Public SDK

Import Distribution contracts from `nous_provider.runtime`, conformance from
`nous_provider.conformance`, and existing Kernel NPA interfaces from
`nous_provider`. The facade reexports canonical types rather than copying Work,
Capability, Observation, Verification or Artifact models.

`nous_provider.Device` remains a Kernel compute Device;
`nous_provider.runtime.ManagedDevice` is a Reality resource. Legacy NPA
`ExecutionProvider` is an inference interface, not a new Distributed executor.
Runtime `ProviderAdapter` declares a `ProviderManifest`, `invoke` and `health`;
`DeviceProvider` supplies discovery/identity/independent state acquisition.
They serve different roles and need not share an artificial universal interface.
See [Provider Development](../development/PROVIDER_DEVELOPMENT.md) and the
[Developer Platform audit](../development/DEVELOPER_PLATFORM.md#m36-public-runtime-sdk-audit).

## Runtime admission and evidence

- Discovery/capability advertisements and claimed health are untrusted metadata.
  Current trusted Capability 2.0 risk, side effects, idempotency and verification
  declarations inform policy. A Provider cannot lower its own required authority.
- Host registration is not Operation approval. Models, planners, schedulers,
  resource graphs, Nodes and Providers cannot approve themselves.
- Submit through the existing authorized execution path. Provider credentials
  arrive only at the current Operation execution boundary through scoped leases.
- Bind AgentSession/Plan/Workflow, Work/Operation, Node, Capability, target resource,
  Artifact inputs, Receipt, Observation and verification IDs where available.
- Map unsupported capabilities, unhealthy/unknown state, timeouts and transport
  loss to bounded explicit errors. Never relabel UNKNOWN as success.
- A lost acknowledgement after a possible effect requires reconciliation of the
  original operation and a fresh Observation, not another provider invocation.
  Valid authority does not imply safe redelivery.

## Conformance and replaceability

Use the existing CTK. Metadata validation never invokes Operations. Executable
legacy probes require an explicit governed host fixture; `test_mode=True` is not
a safety boundary. Opt-in runtime suites inspect supplied canonical records,
signed envelopes and CAS bytes, and independently recompute effect verification.
Missing targets are SKIP; a required SKIP, duplicate probe identity or mismatched
result cannot certify. Reports identify `validation_level=contract` and
`execution_performed=false`; they are not native/physical/performance qualification.

A real integration needs capability discovery, health reporting, standard error
mapping, bound evidence, recovery semantics and its own exercised conformance.
An unavailable external credential or device leaves that specific integration
PENDING. Cloud uses deterministic fake secrets and never claims physical results.

## M4 interoperability audit

| Concern | Classification | Authoritative path |
| --- | --- | --- |
| Intelligence discovery/invoke/stream/cancel | REUSE | Model Gateway and ModelBackendAdapter |
| Provider registration and metadata | REUSE | Existing registry and ProviderAdapter |
| External-agent lifecycle | EXTEND | AgentDescriptor/RunRequest/RunResult, CommandAgentAdapter, ProcessSupervisor |
| External-agent admission | EXTEND | Existing Workflow/DistributedWork/Node and Operation Gate |
| Process/environment isolation | REUSE | Host-supplied Environment Provider; new handler has no host-process fallback |
| Capability risk and verification declarations | REUSE | Host-owned CapabilityContractRegistry |
| Human authority and grants | REUSE | ApprovalBroker, GovernanceStore and human-session boundary |
| Replaceable policy evaluation | EXTEND | Restrictive PolicyProvider hook in the same Operation Gate |
| Secrets and identity | REUSE | SecretBackend/CredentialBroker and HumanIdentityProvider |
| Artifacts, receipts, observation and recovery | REUSE | Existing CAS, Node journal, Work evidence and Reality verification |
| Public replaceable role contracts | EXTEND | `nous_provider.interoperability` exports canonical types |
| Real Codex, Ray/Kubernetes, OPA, OpenBao/Vault, SPIFFE/SPIRE, Viam/ROS/KubeEdge | MISSING | Specific external integrations PENDING; interfaces are preparation, not qualification |

The public interoperability SDK aliases IntelligenceProvider to ModelBackendAdapter,
SecretProvider to SecretBackend, IdentityProvider to HumanIdentityProvider, and
reuses DeviceProvider. ExecutionProvider describes the existing bound Node handler;
it differs from legacy NPA inference. PolicyProvider returns exactly the four
Operation decisions. No parallel provider registry or authority is introduced.

`ExternalAgentWorkflowHandler` fixes descriptor and Node in trusted host
configuration. A Plan supplies an objective, Work identifier and bounded timeout,
never an executable, environment or credentials. The input enters existing CAS;
GovernanceRequest binds all available AgentSession/Plan/Workflow, Work/Operation,
Node, resource, Capability and input identities. The existing DistributedWorkflowAdapter
pauses for human approval and resumes the same Work. Changed inputs cannot reuse
approval. `ExternalAgentOperationHandler` accepts only an attested Node execution
context, at-most-once delivery and immutable bound CAS input. It revalidates
authorization immediately before the existing Supervisor invokes an isolated
Environment runner. Missing isolation fails closed.

Command heuristics and `always_allow` metadata are proposals, never Governance
authority. Legacy direct CommandAgentAdapter is a trusted-host compatibility API
and must not be exposed as an unrestricted model tool. The new handler gives no
Gate, Broker, secret backend or CredentialContext to ordinary agent context.
Secret requirements are currently rejected for external harnesses; authenticated
model credential delivery needs a future adapter at a scoped transport boundary,
not credential environment variables. The host runner must enforce isolation,
bounded output/time and cancellation. Production default OCI still requires its
existing strict backend; Cloud acceptance uses an explicit fixture-owned engine
runner and the existing OCI provider's non-root user, network-disabled/read-only
root filesystem and scoped workspace mount. It does not qualify a production
Linux controller deployment.

Outputs enter CAS as `untrusted-provider-result`, with available provenance.
Process completion is not device effect verification. Failure/timeout cannot
commit Work. Lost responses reach the existing Node journal; restart/duplicate
delivery reconciles evidence without invoking the harness again. A subsequent
device mutation requires its own authority and independent fresh Observation/MATCH.

External policy receives detached request facts. ALLOW only lets Core evaluation
continue; it cannot override Core denial, changed facts, revocation, expiration
or missing grants. DENY/UNKNOWN, malformed results and exceptions fail closed.
REQUIRE_APPROVAL suppresses read-only auto-approval. Policy is re-evaluated at
admission and immediately before execution, recorded in the existing audit trail
as `provider.policy.evaluated`. Trusted hosts must choose bounded-I/O adapters;
the hook does not itself provide an OPA transport or remote authority.

The real OCI reference probe is reproducible with an already installed image:

```sh
APEIR_OCI_TEST_IMAGE=python:3.11-slim python -m pytest tests/interoperability -q
```

It exercises an actual isolated reference subprocess, a durable AgentSession
approval pause, the original Distributed Work/Node receipt, and separate simulated
firmware approval, CredentialLease, Observation and MATCH. Without this explicit
environment only the real OCI probe skips; contract/security tests still run.
Cloud has a Codex CLI, but no authenticated Codex model/remote egress integration
was exercised. That specific provider, other external services and all physical
qualification remain PENDING.

### M4 Cloud validation record

The explicit real-OCI interoperability suite has **25 passed**; directly affected
Agent/Workflow/Node/Reality/Governance/Control Plane/SDK/recovery regressions have
**709 passed**. Full Cloud regression with the OCI probe enabled has **3625 passed,
35 skipped and 9 unchanged baseline failures**. These are the previously reproduced
managed-interpreter, read-only host-home/Desktop automation and orphan-process
cleanup failures recorded in the existing security validation history; none is
rewritten, suppressed or counted as a new interoperability success.

Ruff, changed-file formatting, compilation, all 245 current Markdown local-link
checks, document/comment/identity/Git-metadata hygiene, release version checks and
security scan pass (zero findings). Component-lock contract tests: **3 passed**.
The actual native component verifier remains blocked by the baseline missing
locked Windows Kernel binaries. Kernel sources, C SDK and the Kernel component
pin remain unchanged at `87fd1b2ff28ef14ab1a515a58162592b452fda2e`.
Built Distribution/Provider SDK wheels import their public roles outside the
repository under `python -I -O`. Relevant Desktop/Multi-Arch CI is evaluated on
the pushed SHA before the M4 software Gate is reported. This record certifies the
bounded software/reference flow, not authenticated Codex service integration,
production Linux OCI, a remote authority topology or physical hardware.

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

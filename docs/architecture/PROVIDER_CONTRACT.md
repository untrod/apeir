# Provider model and contract

Current overall milestone status is authoritative in [ROADMAP](../../ROADMAP.md).
Acceptance counts below are dated, scoped records, not broader qualification.

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
The exercised OPA software reference below does not qualify production remote
policy deployment. The KV-v2 OpenBao reference qualifies only scoped software
reads. External Codex, Ray/Kubernetes, SPIFFE/SPIRE and
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
| OPA Data API software reference | EXTEND | Real OPA service plus existing Governance/approval/Work/Node/evidence/Recovery; production authenticated remote-policy deployment remains PENDING |
| OpenBao KV-v2 software reference | EXTEND | Real read-only KV-v2 service through canonical CredentialBroker, leases and Work recovery; production deployment and dynamic server leases remain PENDING |
| Production secret deployment, dynamic server leases and external Vault | MISSING | Static OpenBao KV-v2 software reads do not qualify these separate acceptance items |
| Real Codex, Ray/Kubernetes, SPIFFE/SPIRE, Viam/ROS/KubeEdge | MISSING | Specific external integrations PENDING; interfaces are preparation, not qualification |

The public interoperability SDK aliases IntelligenceProvider to ModelBackendAdapter,
SecretProvider to SecretBackend, IdentityProvider to HumanIdentityProvider, and
reuses DeviceProvider. ExecutionProvider describes the existing bound Node handler;
it differs from legacy NPA inference. PolicyProvider returns exactly the four
Operation decisions. No parallel provider registry or authority is introduced.
Matching request/result types and model enums are exported from that same public
namespace, including GovernanceRequest/Decision, SecretHandle, HumanIdentity,
ModelRequest/Response, AdapterProbe and ProviderExecutionResult. Third-party
adapters can implement these contracts without importing internal Runtime modules.

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
the hook itself does not supply remote authority.

### M4.3 OPA Data API software reference

`OpaPolicyProvider` extends that existing `PolicyProvider` protocol. Its trusted
host selects a credential-free service origin and policy path; neither Work nor
model output can select them. Plaintext is restricted to loopback. HTTPS uses
the platform trust store, redirects are refused, connect/read socket timeouts
are explicit, and response bodies are limited to 65,536 bytes. This is not a
hard end-to-end RPC deadline or authenticated production policy-service claim.
No implicit retry, secret-store access, approval API or grant issuance is added.
Ambient `.netrc` service credentials are explicitly suppressed while platform
proxy/CA configuration remains enabled. A negative test reproduces the default
Requests credential lookup before the corrective transport guard.

The public SDK consumer imports only the published boundary:

```python
from nous_provider.interoperability import OpaPolicyProvider

policy = OpaPolicyProvider("http://127.0.0.1:8181", policy_path="apeir/decision")
# Trusted controller host: supply this object as operation_policy_provider
# to the existing ExecutionAuthorizationGate, never to a model as authority.
```

The adapter posts to `/v1/data/apeir/decision` with an OPA `input` object:

```json
{
  "schema": "apeir.opa-policy/v1",
  "authorization_id": "gov_<sha256-of-exact-canonical-request>",
  "request": {"operation_id": "work-example", "work_id": "work-example"}
}
```

The request shown is abbreviated: actual detached facts include subject,
AgentSession/Plan/Workflow, Node, Capability 2.0 risk/side-effect/idempotency/
verification metadata, resource, expected effect, CAS references and optional
SecretHandle identifiers. Raw secret material is rejected before transmission.
The OPA response must bind its result to that exact authorization ID:

```json
{"result":{"decision":"REQUIRE_APPROVAL","authorization_id":"gov_<same-request-hash>"}}
```

Only ALLOW, DENY, REQUIRE_APPROVAL and UNKNOWN are accepted. Missing/stale binding,
extra authority fields, malformed output, service/TLS/timeout errors and oversized
responses become UNKNOWN. Error bodies and exceptions do not enter Work/audit.
Core still owns current capability facts, explicit read-only policy, grants,
expiry, revocation, human approval and before-effect admission. An OPA ALLOW
cannot authorize an unapproved mutation; REQUIRE_APPROVAL cannot issue approval.
The existing append-oriented audit binds the evaluated verdict and host-selected
implementation type to the canonical request and its complete provenance. It
does not dump endpoint configuration or provider-authored authority fields.
Discovery's `policy.evaluate` capability describes a role, never trust/permission.

The focused audit classified Governance Gate/Store/Broker, Capability 2.0,
CredentialBroker, Work/Node journal, CAS, fresh Observation/EffectVerification
and public SDK as **REUSE**; policy transport/health and SDK exposure as
**EXTEND**; actual remote service identity/authentication and production rollout
as **MISSING**. No additional authority, policy ledger or execution system exists.

Reproduce actual software acceptance using an already installed image:

```sh
APEIR_OPA_TEST_IMAGE=openpolicyagent/opa:1.21.1-static \
  python -m pytest tests/interoperability/test_opa_policy.py -q
```

The exercised engine was OPA **1.21.1**, image digest
`sha256:4675ab04ad1627f74741d2d9c5142698c79e18b7b09f192587d31d6dba20838e`.
The actual binary reported build commit `2a109e54103370d2ef288782ef3cb4c8a37902b2-dirty`,
platform `linux/amd64`, Rego v1 and Go 1.27.1. These are upstream binary metadata,
not a claim of reproducible/signature/CVE qualification. Core CI's Ubuntu 3.12
lane provisions this exact image digest and runs the real-service cases; other
lanes still run contracts and explicitly skip unavailable service qualification.
The pytest fixture provisions a local read-only, unprivileged service. It tests
real Rego evaluation, health/disconnection, the four decisions, firmware Goal →
approval → Credential → Distributed Work/Node → Receipt → fresh Observation →
MATCH/COMMIT, DENY after approval and immediately before effect, and response
loss/restart reconciliation without another mutation. Pausing the actual OPA
process during recovery blocks commitment; restoring it permits a fresh read
and MATCH, not replay of the mutation. Accounts, credentials and devices are fake.

M4.3 local acceptance: the initial focused suite had **50 passed**, including six
actual-service cases; the initial OPA/Governance audit combination had **270 passed**.
Post-merge credentialless transport audit added a failing ambient-netrc negative;
the corrected Interoperability/Governance combination has **296 passed**, including
all **51 OPA cases**. Initial affected regressions had **853 passed, 1 skipped**
(unavailable strong process sandbox). Final full regression after that correction,
with the actual OPA and OCI references enabled, has **3754 passed, 35 skipped,
9 unchanged managed-Cloud baseline failures, 4 warnings**. The original
interpreter/persistence/daemon/orphan-process failures remain visible in issues
#9 and the existing validation history. Initial real-OPA fixture runs failed due
to missing fixture credential registration, conflicting Rego provisioning and
incorrect read-only policy classification; those fixtures were corrected without
weakening runtime admission. The paused-service response-loss stress has **10
passed across five rounds**, with one effect and fresh MATCH after recovery.
Repository contracts have **244 passed**. Ruff, formatting of four changed Python
files, compile, 232 Markdown link checks, standard hygiene/version/security checks
pass; the security scan has zero findings. Component-lock contracts have **3
passed**; the actual native hash verifier remains **BLOCKED** by missing locked
Windows binaries. Kernel and its component pin are unchanged. CI on the pushed
and resulting main SHAs must pass before this scoped software Gate is reported.
Without the explicit image configuration the real-service cases skip; protocol,
security and public-SDK contracts still run. These skips do not claim live OPA.

### M4.4 OpenBao KV-v2 software reference

Audit: REUSE the canonical SecretBackend, SecretHandle (Kernel SecretRef),
CredentialBroker/Lease/Context, Operation Gate, Node journal and Reality recovery.
EXTEND only a host-configured KV-v2 reader and public SDK export. MISSING remains
production remote deployment/bootstrap rotation and dynamic server secret leases.
The local AES-GCM VaultSecretBackend is distinct from this external integration.

`nous_provider.interoperability.OpenBaoKv2SecretBackend` accepts an explicit
protected store token and opaque handle bindings `(mount, path, field)`. Runtime
Work carries handles only; the operator provisions the token read-only outside
Work. Only the existing CredentialBroker resolves it after current authorization,
Node, resource, capability, expiry and handle admission. Providers receive the
current execution-only CredentialContext, never the backend or store token.
The adapter has no writes, grant issuance, approval or renewal methods.

HTTP is loopback-only; HTTPS keeps platform certificate validation. Origins and
paths reject credentials/injection, ambient netrc lookup is suppressed while
proxy/CA settings remain, redirects and implicit retries are forbidden. Responses
are bounded to 64 KiB, socket timeouts to ten seconds; this is not a hard total
RPC deadline. Health checks send no store token and convey availability only.
Undefined/malformed/denied/unavailable values fail closed with generic errors.
Static KV values use APEIR operation-scoped leases, not dynamic OpenBao leases.
Store token expiration/revocation fences new reads; it does not revoke an already
fetched static target credential. Native Handle/Grant/CredentialLease revocation
and expiry remain the use fence; dynamic server lease coupling is unqualified.

The centralized redactor registers the store token before transport and fetched
material before delivery. Protected transport logging is thread-local and Python
stdout/stderr is discarded during resolution; like existing Broker capture,
stdout redirection is process-wide. It is not a native file-descriptor sandbox
or protection against a malicious backend. Host configuration is nonserializable
and redacted. Existing Broker sanitization covers provider outputs/errors and
persisted evidence; no raw response/configuration is added to audit.

```sh
APEIR_OPENBAO_TEST_IMAGE=openbao/openbao@sha256:6d2b93856e3fcf7b18ad855a0b51eaba474dc8b79cf554379ea32034797d2acf \
  python -m pytest tests/interoperability/test_openbao_secret.py -q
```

Local validation: **40 OpenBao cases**, including **5 actual-service cases**,
and **34 existing credential cases** pass together (**74 passed**). Affected
regressions have **781 passed**, repository contracts **244 passed**, and component
lock contracts **3 passed**. The full local run has **3792 passed, 35 skipped,
9 known baseline failures, 4 warnings**; the final real-token-expiry case was
added after its collection and is covered by the final 74-case run. The unchanged
failures remain tracked in issue #9, not skipped or rewritten. Initial Deny
fixture failure used an incorrect approval interface and was corrected to the
existing canonical ApprovalBroker. No Runtime contract was weakened.
Ruff/format/compile, 232 Markdown links and standard repository audits pass;
security scanning finds zero issues. Actual native binary hash verification
remains BLOCKED by absent locked Windows components; Kernel and lock are unchanged.

Actual engine: OpenBao 2.7.1, upstream commit
`a5db72cef75c24b920ade02065b18dd8eb666bac`. Tests provision an unprivileged,
read-only local dev server and deterministic fake root/read tokens and material.
Fixture administration creates a read-only exact-path policy; it is not an APEIR
approval channel. Real service tests exercise denied writes/wrong paths, token
revocation, original firmware Goal/approval/Work/receipt/fresh MATCH commitment,
Deny with no mutation, and response loss/restart after store token revocation
without credential re-resolution or repeated effect. Observation in that scenario
is independently read-only and requires no mutation credential. This does not
qualify credential-dependent observations when their credentials are unavailable.

Core CI provisions the pinned image on Ubuntu 22.04/Python 3.12; other platforms
explicitly skip actual service cases but run contracts. This reference does not
qualify production authentication, dynamic leases, image provenance/signatures,
physical hardware, remote human identity or complete M4. Source `5d47e29196cd16617ad5bee864ec9d8cf9d073d3` and PR #12 Core,
Desktop and Security workflows all passed. Source Ubuntu 3.12 (real services)
has **3801 passed, 36 skipped, 4 warnings**; Ubuntu 3.10 and macOS each have
**3790 passed, 47 skipped, 4 warnings**; Windows has **3797 passed, 40 skipped,
4 warnings**. PR Ubuntu 3.12 has **3802 passed, 36 skipped, 4 warnings**.
These are distinct platform runs, not summed counts. Desktop frontend tests,
lint, typecheck and build passed; native builds remain intentionally unqualified.
Final documentation-head and repaired-main CI passed before the immutable
software checkpoint was created. This is scoped reference acceptance, not full M4.

Initial resulting-main validation on `630434c4f49b71ed0aba5b7f8ee55ed59c8c85d2`
had all Core/Desktop/Security workflows pass, but Multi-Arch Windows Python 3.11
had **1 failed, 3507 passed, 40 skipped, 272 deselected, 4 warnings**. The existing
revocation test expected FAILED immediately after a bounded Workflow wait, while
signed ACK/projection was delayed; this is additional timing evidence, not one
of the nine confirmed local environment failures. SBOM aggregation skipped and
no OpenBao checkpoint was created for that incomplete Gate. Evidence remains in
[issue #4](https://github.com/untrod/apeir/issues/4#issuecomment-6011144748).
A controlled delivery experiment reproduced the ordering in both grant/resource
cases. The test-only correction awaits actual signed result delivery and uses
canonical reconciliation; it retains FAILED, zero-effect, old firmware and audit
assertions. Explicit hold/release tests verify Node FAILED versus Controller
RUNNING before delivery and denied terminal projection afterward, without
resubmission or changed Operation inputs. No Runtime or Kernel behavior changes.
Local projection correction: **4 focused passed** and **40 passed over 10
controlled rounds**, **784 affected passed**,
**246 repository passed**, **3 component-lock contracts passed**; full local
**3797 passed, 35 skipped, 9 unchanged baseline failures, 4 warnings**.
Ruff/changed-file format/compile and standard docs/link/hygiene/version/security
checks pass with zero security findings. Broader Windows latency/root-cause
qualification remains OPEN, not resolved by passing reruns. Repaired main
`c3eeeaca434118565f09300e96e1e9663b749c6e` passed Core, Desktop, Multi-Arch and
Security/Supply-Chain CI, including SBOM collection. Core Ubuntu 3.12 recorded
**3804 passed, 36 skipped, 4 warnings**; Windows 3.12 recorded **3800 passed,
40 skipped, 4 warnings**. Multi-Arch Linux amd64/ARM64 each recorded platform
**13 passed**, then **3502 passed, 48 skipped, 272 deselected, 4 warnings**;
Windows amd64 recorded **3510 passed, 40 skipped, 272 deselected, 4 warnings**.
The exact accepted main is frozen by `milestone/m4.4-openbao-kv2-reference` and
`milestone/m3.2-terminal-projection-contract`. Windows ARM64 remains metadata
validation, and native binary hashes remain BLOCKED; neither is physical acceptance.

The real OCI reference probe is reproducible with an already installed image:

```sh
APEIR_OCI_TEST_IMAGE=python:3.11-slim python -m pytest tests/interoperability -q
```

It exercises an actual isolated reference subprocess, a durable AgentSession
approval pause, the original Distributed Work/Node receipt, and separate simulated
firmware approval, CredentialLease, Observation and MATCH. Without this explicit
environment only the real OCI probe skips; contract/security tests still run.
Cloud has a Codex CLI, but no authenticated Codex model/remote egress integration
was exercised. That specific provider, remaining external services and all physical
qualification remain PENDING.

### M4 Cloud validation record

The explicit real-OCI interoperability suite has **25 passed**; directly affected
Agent/Workflow/Node/Reality/Governance/Control Plane/SDK/recovery regressions have
**710 passed**. Full Cloud regression with the OCI probe enabled has **3626 passed,
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

The original SDK-complete commit's Desktop CI passed, but its
[Multi-Arch run](https://github.com/untrod/apeir/actions/runs/37303867700)
retains a Windows Python 3.11 failure: the expired-handle reconnect test expected
FAILED immediately after a bounded Workflow wait while Work was still RUNNING.
A controlled delayed signed rejection reproduces that assertion failure without
credential resolution or a device effect. The corrected normal/delayed cases
await the original signed terminal evidence, resume the same Workflow/Plan and
require FAILED, zero backend resolutions, zero effects and no leakage. Runtime
admission/retry behavior is unchanged; the nine unrelated Cloud baseline failures
remain intact. Corrective CI must pass before reporting the M4 software Gate.

## Dispatch admission after provider setup

Audit classification: **REUSE** the external-agent handler, Governance admission,
Node journal, supervisor and CAS; **EXTEND** the host runner callback boundary;
**MISSING** remains the full production Ray execution/verification integration.
Slow container or cluster setup cannot extend an approved Operation's authority.

The public Provider SDK exports `AdmissionAwareExecutionRunner`. A trusted,
host-selected runner implements `execute_admitted(..., before_dispatch=...)`,
performs setup, then calls the supplied callback immediately before submitting
the one authorized task. The supervisor preserves the pre-setup check and adds
current Governance revalidation at dispatch. Cancellation during setup prevents
dispatch. The callback permits one successful dispatch and becomes unusable
when the runner returns or raises. A successful report without invoking it is
rejected. The runner must clean up owned resources in `finally`, including when
admission fails; uncertain effects still use the existing Node journal.

This is a trusted execution-adapter contract, not a sandbox for malicious host
code. The callback must remain in the host process, never in task arguments,
credentials, model context, Work, CAS, logs or provider results. It grants no new
authority and cannot approve a request. Existing four-argument callable runners
remain compatible and retain their pre-call check; they cannot claim post-setup
admission unless they implement the new contract. Cancellation after task
submission and production Ray cleanup/verification remain separate acceptance
requirements. Tests in `tests/interoperability/test_dispatch_admission.py` cover
policy DENY/UNKNOWN and expiry during setup, omitted/duplicate/late callbacks,
pre-dispatch cancellation, missing admission and response-loss reconciliation.
Neither this boundary nor the diagnostic below changes default OCI PID64.

## M4.6 bounded Ray qualification diagnostic

### Workflow and post-start admission qualification

Starting main: `515208545736ae7d24306d84f5c0389c072965a1`.
Audit: **REUSE** ExternalAgentWorkflowHandler, the canonical AgentSession/Plan,
Distributed Work, Node identity/journal, Governance/Broker, CAS, CredentialBroker
and Reality EffectVerifier. **EXTEND** only the existing opt-in diagnostic with
the public admission-aware host runner contract. **MISSING** remains a production
Ray adapter/resource-profile admission, remote cluster identity/credentials,
arbitrary workload conformance, GPU and additional platform qualification.
No second execution ledger, approval implementation or verifier is introduced.

`RayDiagnosticAdmissionRunner` runs only the fixed qualification task. Its host
descriptor binds the immutable image, CPU/RAM/tmpfs/PID bounds and exact guest
bootstrap digest into the original approved resource identity. Ray initializes
inside the same isolated OCI environment, emits readiness and waits. The host
checks the pinned Ray version and unchanged profile, calls native Governance
revalidation, and exclusively creates a non-secret dispatch marker. No callback,
AuthorizationContext, grant, credential or model-selected program enters Ray.
The marker is an internal handshake in a fixture-owned workspace, not portable
authority or a defense against malicious trusted host/bootstrap code. Persisted
readiness/dispatch files fence reuse of an uncertain diagnostic directory.

The actual test chain in `tests/interoperability/test_ray_workflow.py` uses one
AgentSession and one durable Plan: independently inspect old simulated firmware,
pause for the Ray Work's Approve Once, execute via Distributed Work/attested Node,
store Ray task/evidence in native CAS, then pause for a separate firmware approval.
That second Operation obtains execution-time fake credentials and its existing
OperationReceipt; separate read-only Work acquires a fresh Observation. Only
MATCH completes the Session and commits the firmware Work. Ray completion has
`effect_verified=false` and grants no device authority. Deny leaves firmware
unchanged; MISMATCH/UNKNOWN never commit. Workflow/Session and Ray Node journal
reload preserve the original Work, approval and one task execution.

Live negative tests change policy to DENY/UNKNOWN, expire authority or alter the
profile after real Ray readiness: no Task is submitted. Cleanup checks the exact
owned container/process identities and execution thread, and verifies default
OCI PID64. Earlier actual Ray failure, cancellation and response-loss/restart
tests continue to reconcile native journals and fresh counter observations
without another task. Bootstrap/version/profile changes and stale dispatch
markers also have engine-free contract tests. Fake broker material is scanned
out of Ray output, Work, CAS and persisted execution records.

This qualification uses only the explicitly approved isolated diagnostic
exception, with PID216 selected for these probes. Observed same-Session task
peaks were 208–212 PID slots, at most 505,974,784 bytes cgroup memory; recorded
cleanup took 1.334–1.707 seconds with no tracked process/container/thread left.
It does not adopt 216 as a production default or prove a global minimum. The
normal OCI default remains64; Kernel and component lock remain frozen. Physical
effects, full production Ray and remote-human qualification are still pending.

### Original bounded resource diagnostic

Historical starting main: `583387eab58868155d6badc1c199694ee00fb6fb`; Kernel stays
`87fd1b2ff28ef14ab1a515a58162592b452fda2e`. The operator approved a temporary
local diagnostic PID ceiling at most256. This is **not a production Ray
ExecutionProvider**: complete M4 remains PARTIAL and production Ray is PENDING.
Normal OCI, its PID64 default, Kernel, SDK, credentials and CI resource limits
remain unchanged. The standalone CLI is an operator-owned resource probe, not a
new Runtime admission API; its acknowledgement flag never grants authority.

| Concern | Audit | Existing owner / scoped extension |
| --- | --- | --- |
| Containment and resource/time boundaries | REUSE | OCIContainerProvider, ExecutionEnvironment and EnvironmentCommand |
| Human approval and execution admission | REUSE | Governance/ApprovalBroker and bound ExternalAgentOperationHandler |
| Delivery, restart and uncertainty | REUSE | Canonical Node execution journal, not Ray retries |
| Resource profile and measurements | EXTEND | Immutable diagnostic profile in the host descriptor metadata, hence its approved resource digest; native result CAS retains provenance |
| Production profile admission/public Provider | MISSING | No production profile registration or Runtime schema is added |
| Remote cluster identity, credentials, GPU/platforms | MISSING | Network-none CPU diagnostics do not qualify them |

Every diagnostic keeps UID65532, read-only root, dropped capabilities,
no-new-privileges, network-none, private PID namespace, no host device/socket,
CPU1, memory2GiB, 512MiB noexec/nosuid/nodev temporary filesystem and45-second
execution budget. Profile inputs are host-owned, not supplied by a model/Work.
Governed tests bind image/PID/CPU/memory/tmpfs/timeout before approval and reject
changed profiles before create. Deny, revoke and six non-human self-approval
cases produce no engine invocation. There is no host-process fallback.

Ray2.49.2 uses pinned upstream Linux-amd64 image
`rayproject/ray@sha256:de04957cc0a2f30563389ab945b5f96358f601ae76bd49755f5727adbcb5e7ba`.
Its public Python directory is inaccessible to UID65532. An offline local
build runs `chmod o+rx /home/ray` and returns to UID65532; runtime execution
remains non-privileged. The exact `IMAGE_RECIPE`, immutable local image ID and
recipe digest are recorded. This derivative is neither signed nor release-qualified.
The repository scanner reports **0 HIGH, 3 MEDIUM** for these public image-layout
paths (recipe, Python constant, documentation), not credentials/personal homes.
They are reviewed findings; no scanner rule or allowlist is weakened to hide them.

| PID ceiling | Measured result | Peak PID slots |
| --- | --- | --- |
| 64 | Earlier startup/thread exhaustion; failed probes retained | No task acceptance |
| 192 | Starts but worker crashes during execution: FAIL | 192 |
| 208 | One task succeeds with only one slot of headroom | 207 |
| 216 | Entire governed diagnostic matrix passes repeatedly | Up to212 under concurrent full-regression load |
| 224 | Same matrix passes; completion peak varies above208 | 210 |
| 256 | Initial task succeeds at the approved upper bound | 207 |

216 is the smallest tested bound completing the matrix, **not a proven minimum,
production default or fleet capacity promise**. PID accounting includes threads.
Initial successful probes have at most11 processes: driver/helper Python,
GCS server, raylet, Ray worker and OCI keepalive shell/sleep. Later load/cleanup
may transiently add helpers. Startup phase mean CPU is approximately0.87–1.00
cores; simple task/idle means0.14–0.18 cores. Adjacent cgroup usage/timestamp
samples expose CPU peaks separately; short samples can span quota windows.
Cgroup memory includes cache; observed peaks range488,218,624–799,838,208bytes,
below the same2GiB limit. Summed RSS double-counts shared mappings. These are
resource measurements, not throughput benchmarks. Ray's default64MiB /dev/shm
warning and /tmp fallback remain; shared memory/noexec were not changed.

Final kernel-reading matrix: **31 passed** (105.36seconds), including four actual
Ray cases. Normal tasks have kernel PID peaks208/208, error202, cancellation205;
last cgroup memory peak501,346,304bytes. Kernel peak readings include the cleanup
helper. Controlled cancellation's actual container destruction is1.532seconds,
separate from the subsequent0.041-second absence check. Normal/error destruction
is1.500–1.548seconds. Every tracked PID plus start-time identity is absent after
cleanup, the container is absent, and default PID64 is rechecked. Earlier PID216
matrices also passed31 cases, including one under concurrent regression load.

Tasks set `max_retries=0`, `retry_exceptions=False`. Task/worker/Ray-node IDs are
untrusted execution evidence, never authority or stable APEIR Node identity.
Effect followed by lost response is reconciled from the original persisted Node
journal after restart and independently observed as counter1, with invocation1.
Error/cancel also leave counter1: neither proves an effect did not happen.
Duplicate delivery returns original terminal evidence without execution. Native
CAS provenance remains, and `effect_verified` stays false. No Reality receipt
or independent EffectVerification is fabricated, and no physical COMMIT is claimed.

Cleanup first exposed unreadable non-secret probe inputs under strict host umask
(no task ran), then pytest warnings from guest-private Ray logs. Only the two fixed
fake inputs use0644. Before destruction the same UID65532 normalizes its own fake
Ray-state files/directories, follows no symlinks and widens no mount. Earlier
warning-bearing results remain: host3854passed/40skipped/2knownPID1failures/
41warnings. Final host full regression: **3854 passed, 40 skipped, 2 unchanged
PID1 orphan failures, 4 warnings**; supported init-container: **3845 passed,
51 skipped, 4 warnings**, exit0. Affected regression780passed/7skipped; final
contract/environment67passed/6skipped; repository244passed; lock contracts3passed.
Ruff/format/compile/docs232/links/hygiene/identity/Git/version checks pass.
Actual native component hashes remain missing/BLOCKED, not substituted by contracts.

Reproduce only with an explicitly approved diagnostic exception:

```bash
# Build IMAGE_RECIPE offline from the pinned, already pulled image.
# Inspect and supply the immutable local image ID, not a mutable tag.
python -m scripts.ci.ray_bounded_diagnostic \
  --image sha256:<local-image-id> --workspace /tmp/apeir-ray-new-probe \
  --pids 216 --acknowledge-diagnostic-exception
# Add --mode failure or --mode cancel for fault injection.
APEIR_RAY_DIAGNOSTIC_IMAGE=sha256:<local-image-id> APEIR_RAY_DIAGNOSTIC_PIDS=216 \
  python -m pytest -q tests/interoperability/test_ray_diagnostic.py
```

The CLI rejects reused workspaces; an instance/restart also refuses prior probe
inputs/state even if the counter is missing. Keep raw reports/samples outside
source control. CI runs contracts and explicitly skips the four real cases without
a host image/exception; no GitHub CI high-PID exception is introduced. A future
production Gate must register a host-selected profile as governed resource facts,
revalidate admission immediately before task dispatch, integrate complete Work/
Workflow and independent effect verification, and qualify health/errors,
cancellation, cleanup, recovery, credentials/identity and conformance. A prior
approval, startup success or profile name alone cannot satisfy that Gate.

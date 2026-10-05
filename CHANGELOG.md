# Changelog

All notable changes to APEIR Distribution are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## Unreleased

- M5 read-only SerialTransport/ESP32 DeviceProvider preparation through existing
  Reality contracts and the public SDK: bounded signed state acquisition,
  fresh challenges, explicit host bindings and no retry or mutation surface.
  Physical firmware, fault-injection and second-family acceptance remain pending.

- M4 public replaceable provider roles, restrictive external policy inside the
  existing Governance Gate, and an admitted external-agent Workflow/Node bridge
  over existing CAS, process supervision, isolated Environment Providers and
  at-most-once recovery. Real OCI reference execution is separately qualified;
  unexercised external services and hardware remain pending.

- Architecture Consolidation Gate: five existing authoritative contracts now
  distinguish Kernel and Distribution execution scopes, authority, state/failure
  semantics and replaceable Providers. Legacy overviews forward to these paths;
  unknown effects and pending physical qualification remain explicit.

- M3.6 additive public Work/Node/Reality/Provider SDK facade over canonical
  contracts, independently installable SDK wheels, existing protocol/schema
  rejection and seven opt-in CTK runtime contract suites. Metadata conformance
  never invokes providers, and required skipped probes cannot certify. Native
  provider and physical qualification remain pending.

- M3.5 unified canonical Operations Control Plane, external OIDC/PKCE human
  identity with durable expiry/replay binding, existing governed controls, SSE
  transitions and a shared responsive Desktop/Web Operations Console. External
  IdP deployment, Windows file enrollment and physical acceptance remain pending.

- M3.4-B credential delivery scoped to existing authorized Node Operations,
  with durable handle/lease expiry and revocation, centralized output redaction,
  credentialed firmware simulation and recovery without effect replay. Pending
  approval list/detail and Once/Deny backend reuse the existing Governance
  authority; trusted remote-human identity remains pending.

- M3.4-A deterministic Operation governance through the existing Gate, Broker,
  scoped durable leases and audit trail. High-risk simulated firmware updates
  pause the original Workflow for human Approve Once or Deny; Node admission
  rechecks expiry and revocation, and recovery never licenses effect replay.

- M3.3-B stateful Reality simulation through existing AgentSession, Plan,
  Workflow, Distributed Work, Node and Artifact CAS paths. Device mutations
  commit only after independent fresh observation yields `MATCH`.
- Deterministic device, operation, delay, duplicate/stale evidence and response
  loss faults, with persisted at-most-once recovery and lifecycle events.
- Physical-device acceptance (M3.3-C) remains pending; Kernel is unchanged.

## [0.1.0-rc1] - 2026-09-07

First public release candidate of the APEIR user distribution.

### Included

- Native Windows desktop shell, authenticated loopback Runtime API, CLI, and SDKs.
- Pinned APEIR Kernel integration over NKI with fail-closed version checks.
- Governed file, process, document, network, model, MCP, Skill, environment,
  simulation, node, artifact, and deployment services.
- Provider-neutral model cost controls: request and output caps, daily and retry
  budgets, durable usage receipts, cache accounting, and credential-safe grouping.
- Windows x64 installer and portable packaging workflows.
- Compatibility aliases for existing `nous` commands, imports, environment
  variables, and `nous.*.v1` wire identifiers.

### Release policy

This candidate is not a general-availability release. Only results recorded in
the release report for a particular artifact apply to that artifact. Remote
multi-host, Linux, Jetson, MCU, and physical-device support require separate
qualification before they may be described as supported.

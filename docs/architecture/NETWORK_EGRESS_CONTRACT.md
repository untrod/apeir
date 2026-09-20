# Network Egress Contract

Status: P15 implemented vertical slice
Updated: 2026-08-31
Authority registry: `nous_runtime.network.egress`

## Decision

Nous has one authority per outbound protocol class. The public Research
WebGateway is not a generic proxy for Provider, Download, Runtime/Node, Edge, or
Device traffic. Private and loopback targets remain invalid for Research and
valid only for a configured protocol authority.

The authority registry is a static ownership contract. It does not create a
second policy engine, approval broker, credential store, event ledger, or
scheduler. Side-effect authorization remains owned by the existing Capability,
ExecutionAuthorizationGate, ApprovalBroker, and EventStream authorities.

## Protocol classes

| Authority | Owner | Scope | Private targets | Redirect policy | Credential boundary |
| --- | --- | --- | --- | --- | --- |
| research.public_web | WebGateway | public Internet | no | bounded and revalidated | credential_ref only |
| provider.model | Model/Provider Gateway | configured provider | provider-specific | adapter contract | Provider Registry reference |
| distribution.download | Model Distribution | artifact registry | no | registry/downloader contract | registry reference |
| control.runtime | Control Plane | loopback/configured control plane | yes | none | Runtime bearer token |
| control.node | Connectivity | configured node control plane | yes | none | node identity |
| control.edge | nous_edge | configured Brain | yes | none required | edge shared secret |
| device.agent | device_transport | configured Agent | yes | blocked | header only |
| device.android | Android adapter | configured Android Agent | yes | adapter contract | pairing token |

## P15 invariants

- Every low-level call site is either centralized or listed in
  `RETAINED_DIRECT_CALL_SITES` with an owner and protocol class.
- The architecture freeze fails on a new file, an extra call, a missing owner,
  a duplicate path, or an incomplete authority contract.
- Research resolves and validates every destination and every redirect, pins
  the validated address, rejects all non-global addresses, and blocks
  credentialed cross-origin redirects.
- Research uses one total request time budget, at most two retries for GET/HEAD
  transient connection failures, exponential bounded backoff, cooperative
  cancellation, a process-wide destination rate limit, and bounded response
  bytes.
- POST is never automatically retried without a separate idempotency contract.
- Device Agent requests are bound to the configured host and port, bypass
  ambient proxies, block redirects, restrict methods and headers, and bound
  request/response sizes.
- Expired approvals are atomically changed from PENDING to EXPIRED and cannot
  issue an authorization lease.
- Transport exception details and credential values never enter API responses
  or EventStream records.

## Retained low-level transports

The frozen raw-call count is 19 across 11 files:

- Provider/Model: 9
- Distribution/Registry: 4
- Runtime Control: 2
- Edge Control: 2
- Node Control: 1
- Android Device: 1

This is not an allowance to add arbitrary networking. These are
protocol-specific implementation points already behind named authorities.
The former six scattered Brain/device calls were removed and consolidated into
`remote_terminal.device_transport`.

## Failure model

Stable public gateway failures distinguish DNS, invalid DNS data, SSRF,
connection, timeout, connection reset, TLS, HTTP protocol, redirect loop,
rate-limit, cancellation, credential, response-size, content-encoding, MIME,
and HTTP-status failures. All failures close the run through EventStream.

## Evidence level

The current evidence is automated and integrated-host. Native Windows 10 x64
rebuild and real-public-TLS smoke verification are required before calling the
new binary release-certified. Provider, Distribution, Control, Edge, and
Android protocol transports remain individually owned and frozen; later
centralization can reduce the raw count without changing authority semantics.

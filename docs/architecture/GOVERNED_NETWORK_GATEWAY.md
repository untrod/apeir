# Governed Network Gateway

Status: Implemented vertical slice
Evidence level: integrated-host
Updated: 2026-08-31

## Decision

The Runtime research surface uses one outbound HTTP authority:
nous_runtime.evidence.web_gateway.WebGateway.

The gateway extends existing Nous authorities. It does not create a second
approval broker, event store, artifact registry, credential store, scheduler,
or process runtime.

Research request flow:

~~~text
Desktop / Runtime caller
  -> network.fetch capability
  -> ExecutionAuthorizationGate
  -> one-use Approval Lease
  -> WebGateway
  -> public HTTP target
  -> SourceRegistry
  -> immutable SnapshotStore
  -> ArtifactRegistry
  -> EventStream
~~~

Provider SDK traffic remains owned by the existing Model/Provider Gateway.
New research or business web integrations must use this boundary instead of
calling a general HTTP client directly.

## Request contract

WebRequest carries:

- request_id, method, URL;
- inline headers or workspace-scoped headers_ref;
- inline body or workspace-scoped body_ref;
- timeout and maximum response bytes;
- credential_ref, never a credential value;
- public_internet network scope;
- task, run, and trace identifiers;
- approval requirement and redirect limit;
- a total timeout budget, bounded GET/HEAD retry count and backoff;
- an optional cooperative cancellation check.

Version 1 supports GET, HEAD, and POST. The maximum request body is 1 MiB and
the maximum response is 5 MiB. Callers may request a smaller response bound.

## Security boundary

Before a connection, and again after every redirect, the gateway:

- accepts only HTTP and HTTPS;
- rejects URL user information, localhost, local/internal suffixes, and known
  metadata names;
- resolves every address and rejects the entire result if any address is not
  globally routable;
- connects to the validated address while preserving the original HTTPS name
  for certificate and SNI verification;
- blocks credentialed cross-origin redirects;
- rejects caller-controlled authentication, Host, length, connection, and
  transfer headers;
- blocks compressed responses in version 1;
- enforces Content-Length and streaming byte limits;
- verifies JSON, PDF, image/HTML, and JSON-path MIME consistency;
- detects redirect loops and DNS rebinding;
- applies a process-wide per-destination rate limit;
- retries only transient GET/HEAD connection failures, at most twice.

Sensitive query keys, including search query parameters, are redacted before URLs enter governance records,
events, Sources, Artifacts, errors, or Desktop responses. Request bodies enter
events only as SHA-256. Credential values are resolved at the final request
boundary and never enter Runtime state. The safe credential_ref remains
auditable through the shared recursive redactor.

## Evidence and event contract

A successful request persists the exact response bytes, their SHA-256, a
Source record, a Snapshot record, and an Artifact record. EventStream remains
the only run history and records:

- network.requested
- network.approval_required
- network.approved
- network.retry_scheduled (only when a bounded transient retry is used)
- network.connected
- network.response_received
- network.snapshot_created
- artifact.created
- network.completed
- run.completed

Failures record network.failed and run.failed with bounded messages.

## Desktop surface

Developer Platform now includes Research. It displays gateway status, performs
approval-gated Bing HTML search, requires manual result selection, accepts
public URL requests and optional Credential References, shows the explicit
approval requirement, consumes one approval lease, retries the identical
reviewed request, and displays source/snapshot/artifact/run identifiers. The same Research workbench
loads persisted Claims and creates an approval-gated Claim from a selected
Source without introducing a second workspace or ledger.

## Verified behavior

The rebuilt Nous.exe also completed an authenticated real-public-TLS fetch after a one-use approval and replayed all required network events. Automated coverage includes public fetch persistence, source/snapshot/artifact
reload, governed search parsing, search-query event redaction, result selection,
structured citations, event replay, localhost and private-address SSRF rejection, IPv4 and
IPv6 local ranges, redirect revalidation, credentialed cross-origin redirect
blocking, response size enforcement, compressed response rejection, MIME
mismatch rejection, sensitive query removal, secret non-persistence, API
approval/retry, and Desktop approval interaction.

## Current limitations

- Search provider integration, manual result selection, source-bound structured
  citations, and P14 deterministic Source/Snapshot-to-Claim linkage are
  implemented. Semantic entailment beyond the reference matcher is not.
- JavaScript browser rendering and browser automation are intentionally absent.
- Compressed HTTP responses are intentionally rejected in version 1.
- Snapshot download/export has no dedicated Desktop action yet.
- This is integrated-host evidence, not a public-network production
  certification.
- P15 classifies and freezes every retained protocol transport. The raw count
  is 19 across 11 files, down from 25 after six Brain/device calls moved behind
  Device Transport Authority. There are zero unclassified public-web calls.
- Provider, Distribution, Runtime/Node, Edge, and Android transports retain
  protocol-specific low-level implementations; they must not be routed through
  Research because their private-target, streaming, or provider semantics differ.
  See docs/architecture/NETWORK_EGRESS_CONTRACT.md.
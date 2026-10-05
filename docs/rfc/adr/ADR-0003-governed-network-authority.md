# ADR-0003: Governed Web Fetch Uses Existing Runtime Authorities

- Status: Accepted
- Date: 2026-08-30
- Scope: Runtime API, Governance, Evidence, Artifact, EventStream, Desktop

## Context

The former WebGateway returned placeholder content. Adding real web access
introduces external effects, SSRF, DNS rebinding, redirect, credential,
response-size, content-type, prompt-injection, and provenance risks. The
Runtime already owns approvals, credentials, events, artifacts, runs, and
workspace isolation; parallel replacements would split authority.

## Decision

Implement network.fetch as a high-risk built-in Runtime capability. Every
research fetch enters ExecutionAuthorizationGate and requires a hash-bound
one-use approval lease. The approved request is then executed by WebGateway.

WebGateway validates and pins public DNS destinations, revalidates redirects,
enforces bounds and MIME checks, resolves credentials only from references,
and persists successful responses as Source, immutable Snapshot, and Artifact
records. It appends the lifecycle to EventStream.

SourceRegistry, SnapshotStore, and ArtifactRegistry gain workspace-scoped
durability. EventStream keeps its existing schema and sequence authority and
is extended with network event types. The shared recursive redactor preserves
safe credential references while removing credential material.

## Consequences

- Research can retrieve real public HTTP evidence without an ungoverned HTTP
  path.
- Approval replay authorizes only the exact reviewed request.
- DNS and redirect checks fail closed before untrusted targets are contacted.
- Exact response bytes remain independently hash-verifiable after restart.
- Desktop is a control surface and owns no network, approval, or evidence state.
- Search and citation generation remain a subsequent P13 increment rather than
  being inferred from fetch support.
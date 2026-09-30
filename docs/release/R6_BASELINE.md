# R6 frozen baseline

R6 is frozen as the stable starting point for Compute Mesh development. This
freeze ends further R6 infrastructure work and paid Research retries; it does
not turn an unverified acceptance into a release claim.

## Frozen revisions

- Distribution: `841c1ffe513c2a365c75467f20b1992b1da2d1bb`
- Kernel: `87fd1b2ff28ef14ab1a515a58162592b452fda2e`

The freeze commit that adds this document is expected to advance the
Distribution revision without changing Runtime behavior.

## Verified foundation

- Kernel-governed execution and fail-closed admission
- durable Work state, Desktop reconnect, and forced-restart recovery
- governed Files, Persistent Shell, Web, Artifact, and approval paths
- deterministic Code Work control path
- Scientific Work on the source host
- provider-neutral model Usage and finish-reason telemetry
- Desktop and Multi-Arch release-class CI

## Known acceptance boundary

The last authorized live Research Work acquired independent official Python and
Rust sources and stored immutable evidence. It did not reach report creation,
verification, or `COMPLETED`: the following structured decision ended with
`finish_reason=length` at the then-authorized 1,024 output-token limit.

The boundary now reports provider-neutral Usage, preserves reasoning/cache
telemetry, and uses a bounded 1,536-token decision limit. No additional paid
Research run was performed after that change. Consequently:

- live Research completion remains unverified;
- a successful live-model Token baseline remains unavailable;
- neither item may be described as passed.

These limitations are accepted for the R6 freeze and remain visible in
`KNOWN_LIMITATIONS.md`. Compute Mesh work must not reopen R6 architecture unless
a concrete correctness or security defect requires it.

## Next development line

Development continues on `feature/compute-mesh-v0.1` with a narrow objective:
establish one long-running Controller, register heterogeneous Nodes, and complete
one governed remote Work with durable Artifact and cross-client observation.

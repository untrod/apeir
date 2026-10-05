# APEIR Distribution 0.1.0-rc1

This is the first public candidate of the APEIR user distribution. It pairs a
native Windows desktop application with the independently released APEIR
Kernel.

## Highlights

- Native desktop, authenticated local Runtime API, CLI, and SDK entry points.
- Pinned Kernel revision and executable hashes.
- Fail-closed NKI model execution with governed permits, leases, and receipts.
- File, development, document, network, model, MCP/Skill, environment,
  simulation, node, artifact, and deployment services.
- Provider-neutral Token and cost limits with durable local usage receipts.
- NSIS installer and portable Windows x64 packaging workflows.

## Compatibility

APEIR is the public product name. Existing `nous_runtime` imports, `nous`
command aliases, `NOUS_*` configuration, and `nous.*.v1` wire identifiers
remain available for compatibility.

## Support status

Windows 10 x64 is the only desktop certification target for this candidate.
Model and admitted extension workloads use NKI. Bounded local services use the
Runtime authorization scope and explicitly report that the Kernel was not
traversed; see the execution-boundary section in the main README.
See [Known limitations](KNOWN_LIMITATIONS.md) and the
[public release checklist](PUBLIC_RELEASE_CHECKLIST.md) before deployment.

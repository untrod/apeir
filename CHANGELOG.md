# Changelog

All notable changes to APEIR Distribution are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

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

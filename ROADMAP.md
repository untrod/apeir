# Roadmap

APEIR is developed around stable authority boundaries rather than a growing list
of surface features. This document describes direction, not delivery dates.

## Before 0.1.0

- Complete clean-checkout Windows 10 x64 packaging, install, upgrade, launch, and
  uninstall certification.
- Publish signed Kernel and Distribution artifacts with checksums, SBOM, and
  provenance.
- Close the documented capability test matrix with Kernel-path evidence.
- Complete maintainer review of public names, compatibility identifiers, licenses,
  and known limitations.

## After the first public release

- Qualify Linux x64 and remote two-node execution.
- Bind device discovery and reservations to Kernel resource leases.
- Expand OCI, Jetson, and embedded-device backends behind the same contracts.
- Stabilize extension SDKs and test compatibility with external MCP servers and
  community Skill formats.
- Add the optional desktop cost dashboard without moving policy authority into
  the UI.

Compatibility and security take priority over new integrations. Protocol changes
require an RFC and a versioned migration path.

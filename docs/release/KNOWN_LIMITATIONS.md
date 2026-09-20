# Known limitations

Version: `0.1.0-rc1`

- Windows 10 x64 is the only desktop certification target for this candidate.
  Linux, macOS, ARM64, Jetson, MCU, and multi-host operation are not certified.
- Model-backed tasks require a configured Provider account or a local model.
  APEIR cannot correct an exhausted third-party balance.
- Token limits are enforced before dispatch. If a Provider returns more usage
  than authorized, APEIR records the overrun, rejects the result, and blocks that
  credential reference for the remainder of the UTC day; charges already made by
  the Provider cannot be reversed.
- Cost limits require a reviewed local pricing catalog. Unknown model prices still
  receive Token limits, but preflight monetary estimates are unavailable.
- Untrusted code requires an available Windows Sandbox backend. Trusted in-process
  extension handlers are not an isolation boundary.
- Local file, document, environment, network, simulation, and scientific services
  are Runtime-governed in this candidate and do not yet traverse the Rust Kernel.
  Their receipts must not be interpreted as Kernel execution proofs.
- Windows Defender was unavailable on the current validation host. Installer,
  executable, installed-directory, and post-install scans remain unverified.
- Remote MCP HTTPS support is opt-in and restricted by local permits, TLS
  validation, fixed public addresses, redirect denial, and response-size limits.
- Existing `nous_runtime`, `nous`, `NOUS_*`, and `nous.*.v1` identifiers remain
  for compatibility and will not be renamed without a versioned migration.
- Release-candidate APIs and persisted Distribution formats may change before 1.0.

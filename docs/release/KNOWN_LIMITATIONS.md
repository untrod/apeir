# Known limitations

Version: `0.1.0-rc1`

- Windows 10 x64 is the only desktop certification target for this candidate.
  Linux, macOS, ARM64, Jetson, MCU, and multi-host operation are not certified.
- M2 production-boundary contracts and local mechanisms exist on
  `feature/reality-execution-v2`, but x64 Controller to Windows ARM64 real-effect
  acceptance, independent remote observation, reconnect/fault injection, and
  malicious/stale-node matrices remain pending. This is not M2 completion.
- The R6 Work Harness core now has structured assessment and deliberation,
  versioned plans, progress events, steering, durable checkpoints, restart
  recovery, and a CLI entry. ToolCatalog now provides normalized, progressive
  discovery for the existing Workspace runtime and governed Extension/MCP tool
  projections, plus fixed read-only Git and ContentAddressedArtifactStore tools.
  Git tools fail closed and are not advertised when strong process isolation is
  unavailable. SkillRegistry now provides progressive discovery/loading for
  legacy JSON, project/user `SKILL.md`, installed Extension packages, and local
  or HTTPS catalog summaries; installation produces Extension supply-chain
  evidence and a pinned Artifact bundle without executing scripts. Remote Skill
  package download/install and Git URL cloning are not yet supported. File
  patch/move/remove, persistent shell control, live MCP catalog attachment, the
  WebRuntime now exposes governed search/fetch through the existing Network
  Gateway and writes successful responses to content-addressed evidence before
  returning them to Work. The first search implementation still uses the
  existing Bing parser; provider configuration UX and the full cited Research
  vertical remain pending. File patch/move/remove, persistent shell control,
  live MCP catalog attachment, background Desktop execution, context compaction,
  and the Code/Research/Scientific acceptance tasks are still pending. This is
  not R6 completion.
- The first Reality Adapter supports only an administrator-bound loopback HTTP
  service target. It is not an arbitrary remote endpoint or device runtime.
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

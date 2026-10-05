# Release validation matrix

Target: **APEIR Distribution 0.1.0-rc1** on Windows 10 x64.

This file records the release claims and the conditions needed to reproduce
them. Generated logs, databases, and machine-specific evidence are kept outside
the source repository.

| Area | Validation | Status |
| --- | --- | --- |
| Python Runtime | Full `pytest` suite | Required: zero failures |
| Python quality | Ruff checks | Passed |
| Public hygiene | tracked-file secret, path, attribution, and artifact checks | Passed |
| Kernel identity | lock revision, x64 PE identity, and SHA-256 against independent checkout | Passed |
| Native Kernel path | admission, approval, permit, receipt, and MCP sandbox tests | Run with `APEIR_KERNEL_ROOT` pointing to the locked checkout |
| Desktop web layer | install, lint, unit tests, typecheck, production build | Passed |
| Desktop native layer | Cargo check and tests | Passed |
| Packaging | portable ZIP and NSIS installer smoke tests | Passed |
| Lifecycle | launch, port conflict, crash, shutdown, upgrade, uninstall, residual-process audit | Passed |
| Supply chain | sensitive-data scan, licenses, SBOM, and SHA-256 manifests | Passed |
| Antivirus | Windows Defender scans | Not verified: Defender unavailable on this host |
| Signing | maintainer signature and provenance | Required before publication |

## Conditional skips

The two native extension integration tests skip only when a built independent
Kernel checkout is not supplied. Set `APEIR_KERNEL_ROOT` to the checkout pinned
by `runtime-components.lock.json`; the release validation run executes both
tests. This is a test-environment prerequisite, not a supported product fallback.

No skipped result may be reported as a pass. Any additional skip must record the
test name, reason, platform limitation, and release impact before publication.

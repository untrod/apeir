# Release runbook

This runbook creates APEIR Distribution `0.1.0-rc1`. Publication and signing
require the maintainer's credentials and explicit approval.

## 1. Freeze inputs

1. Work from a clean Distribution checkout.
2. Confirm `runtime-components.lock.json` points to a public APEIR Kernel commit.
3. Download or build the exact locked Kernel artifacts and verify their SHA-256.
4. Confirm every version manifest reports `0.1.0-rc1`.

If the original Windows binaries cannot be recovered, the existing **Desktop CI**
manual workflow has an opt-in `rebuild_locked_kernel` diagnostic. It checks out
the frozen Kernel separately, records the Windows/MSVC and Rust toolchains,
builds both components with `cargo build --release --locked`, and independently
compares their SHA-256 and PE architecture with the unchanged Distribution lock.
The diagnostic is off by default, has a 30-minute bound and two Cargo build jobs,
and uploads only logs and a component report for 14 days. It neither stages
executables nor enables packaging, changes the lock, signs, tags or publishes.

```bash
gh workflow run desktop-build.yml --ref <reviewed-distribution-branch> -f rebuild_locked_kernel=true
```

A missing binary, changed Kernel source, wrong revision, invalid PE or hash
mismatch fails the diagnostic with `BLOCKED`; a successful build alone is not
component integrity. Preserve the actual and expected hashes and build inputs.
If the bytes differ, request a separate reviewed rebuild/compatibility/version
and component-lock update; do not replace the historical lock values. Even an
exact `MATCH` leaves NKI runtime and Windows 10 installation acceptance `NOT_RUN`
until exercised below. A Windows CI runner is not a clean Windows 10 install test.

## 2. Verify source

```powershell
python -m ruff check nous_runtime tests scripts integrations sdk
python -m pytest -q
python scripts/security_scan.py
python scripts/markdown_link_check.py .
```

## 3. Verify desktop

```powershell
cd desktop
npm ci
npm run lint
npm test
npm run typecheck
npm run build
cd ..
```

## 4. Build Windows artifacts

```powershell
$env:APEIR_KERNEL_ROOT = (Resolve-Path "..\apeir-kernel").Path
.\scripts\build-windows-x64-launcher.ps1 -KernelRoot $env:APEIR_KERNEL_ROOT
```

Run install, upgrade, launch, shutdown, uninstall, orphan-process, and Windows
Defender checks on Windows 10 x64. Store generated evidence outside the source
tree.

No production version or GitHub release is invented by checkpoint creation.
SDK is beta; formal SemVer publication requires stable public compatibility
and packaging plus all release gates. Release Preflight runs the actual component
hash verifier and must fail when locked bytes are absent. Never substitute the
component-lock contract tests for native verification.

## 5. Produce release metadata

Generate a source manifest, SHA-256 files, CycloneDX SBOM, dependency-license
report, and provenance/attestation where supported, and reproducible build inputs/metadata. Verify all files from a second clean directory.

## 6. Sign and publish

After maintainer approval, sign the installer, executable, checksums, and
provenance with the project's release identity. Create the annotated tag and
GitHub release only after signature verification succeeds.

## Rollback

Do not replace a published artifact in place. Withdraw the affected release,
document the reason, correct the source, and publish a new candidate version.

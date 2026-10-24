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

### Candidate compatibility before lock migration

When bounded recovery of the original bytes has failed, the same diagnostic can
explicitly qualify **unapproved candidates** using `qualify_kernel_candidate`:

```bash
gh workflow run desktop-build.yml --ref <reviewed-distribution-branch> -f rebuild_locked_kernel=true -f qualify_kernel_candidate=true
```

This performs two clean Windows builds with recorded Rust1.99.1, MSVC/SDK,
Cargo.lock, source revision, allowed build variables, signatures and dependencies.
The existing real sidecar smoke tests NKI1/2/3, bad/missing authentication,
unsupported protocol versions, forbidden model credentials before provider spawn,
Runtime startup refusal with a bad NKI session, authenticated HTTP, and fault
restart/query of the original failed workload. The build host's Python only
drives the existing NKI client; native child PATH/Python configuration is scrubbed.
Fault cleanup is not graceful Desktop-exit or Windows10 installation acceptance.

The original-lock comparison retains its nonzero exit on mismatched bytes. Later
candidate-only steps run explicitly to collect compatibility evidence; they do
not turn this failed integrity Gate into PASS. Candidate files are outside the
Distribution's staged binary directory. The two `unapproved-kernel-candidate-*`
artifacts and comparison report expire after14 days; preserve their exact archive
digests and files before expiry for review. Failed smoke remains FAIL in the
candidate manifest. No Runtime databases, session tokens or raw service logs are
uploaded. Neither candidate retention nor matching two builds approves relocking,
packaging, signing or publication. Nonidentical bytes or build environments must
be reported rather than described as fully reproducible.

The first R4 pair (`d4b3f10`, Actions40083548896) built successfully and both
real native smoke runs passed, but the two unchanged Kernel components differed
by20 bytes each. Their recorded environments matched; in-memory forensic
comparison localized the variance to PE timestamp/debug identity metadata. Raw
files and their distinct hashes are retained unchanged. Candidate-only builds
now record `RUSTFLAGS=-C link-arg=/Brepro` to request deterministic linker output;
the regular original-lock diagnostic keeps its original flags. This is a new
source-build profile for review, never post-processing EXEs or trying to recover
old hashes by collision. Its actual second-pair results, including any remaining
variance, belong in the lock-migration PR before approval.

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

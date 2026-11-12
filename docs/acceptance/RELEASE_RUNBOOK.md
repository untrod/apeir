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

### Approved Windows ARM64 input profile — 2026-11-11

The maintainer approved the exact ARM64 entries in the
[ARM64 baseline record](ENGINEERING_REVIEW.md#approved-arm64-component-baseline--2026-11-11)
and internal unsigned builds. Select `--target aarch64-pc-windows-msvc` when
using the existing component verifier/stager; default x64 selection is retained.
The official Windows launcher accepts the same explicit target. Source87fd1b2
and the approved x64 components are unchanged. Candidate archive provenance and
actual target-specific PE/hash checks remain mandatory. Windows11 ARM64 smoke,
Windows10 tablet installation, signing and publication remain separate gates.

Full-mode [ARM64 build43115765924](https://github.com/untrod/apeir/actions/runs/43115765924)
produced the [unsigned internal bundle](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13901748571) from
`16308a6b5bb6f1d3049144f413bc8a9b9541561a`. Actual hosted Windows11 ARM64 silent installation and
installed-sidecar checks passed. Windows10 GUI/lifecycle remains PENDING.
ARM64 is distributed through this reviewed Actions artifact; the existing
Release Preflight draft-staging consumer still targets x64. Do not pass ARM64
files to it or publish them by bypassing its target check. Signing and public
publication retain their separate approvals.

## 2. Verify source

The 2026-10-26 maintainer approval covers the reviewed frozen-source binary
hash migration and internal unsigned builds only. The exact producer, archive
digest, old/new hashes and retained compatibility evidence are recorded in the
[Windows migration record](../operations/deployment/WINDOWS_10_X64_LAUNCHER.md#approved-component-lock-migration--2026-10-26).
Apply normal PR/CI integration; this approval does not replace current native
smoke, Windows10 installation, signing or publication gates.

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

For an approved external bundle, pass `-KernelArtifactDirectory` containing its
locked relative `desktop/src-tauri/binaries/` paths. The existing staging/verifier
checks the full bundle before replacing any staged input and rechecks after copy.
Full delivery runs must not pass `-SkipValidation` or `-SkipSidecarSmoke`.
The existing Desktop CI Windows x64 job now accepts reviewed exact run/artifact
IDs plus the archive digest, binds the producer to this repository and a source
ancestor, and uses this same official script. `native_target=none` is the default;
setting the binary flag alone does not start every native platform. See the
[Windows input and qualification record](../operations/deployment/WINDOWS_10_X64_LAUNCHER.md#approved-github-actions-input).

The native report records the actual build OS rather than hardcoding Windows10.
It explicitly marks installed Desktop acceptance `NOT_RUN`. Build outputs include
a Python build-environment CycloneDX SBOM and original Kernel/Desktop Cargo.lock
files; complete cross-component supply-chain/signature qualification remains a
separate release Gate.

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

### Prepare an unpublished native preview

The existing **Release Preflight** workflow can verify an exact accepted native
run/artifact/outer ZIP digest. Run it from protected `main`; its default is
read-only verification. Set `stage_draft=true` only to stage reviewed unsigned
files in an **unpublished prerelease draft**. The staging job alone receives
`contents: write`; producer/download jobs remain read-only. It rechecks source
ancestry, actual package checksums, locked PE bytes, full-mode validation and
original NKI/Work recovery before uploading. Neither mode signs, publishes or
creates a Git tag. Source is the actual binary producer SHA, not a later docs SHA.

```bash
gh workflow run release.yml --ref main -f native_run_id=<reviewed-native-run> -f native_artifact_id=<exact-artifact-id> -f native_zip_sha256=<reviewed-outer-zip-sha256>
```

Append `-f stage_draft=true` for authorized internal draft staging. A failed
upload leaves an unpublished draft; an identical existing asset is retained only
when its GitHub-reported digest and size match. Missing digests, changed assets,
published releases, existing tags and unrelated drafts fail closed. No asset is
deleted or uploaded with `--clobber`. Resolve an identity/permission failure at
the credential/workflow boundary; do not weaken repository protection or publish
the draft to work around it. Draft assets are not public download links.

This preparation does not satisfy Windows 10 installation, Defender, complete
supply-chain qualification, signing or publication authorization. Keep their
actual pending/blocking states and follow the release gate below.

### Publish after qualification

After maintainer approval, sign the installer, executable, checksums, and
provenance with the project's release identity. Create the annotated tag and
GitHub release only after signature verification succeeds.

## Rollback

Do not replace a published artifact in place. Withdraw the affected release,
document the reason, correct the source, and publish a new candidate version.

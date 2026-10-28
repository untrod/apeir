# Windows 10 X64 Launcher build

APEIR Desktop is the launcher and control surface for the complete local product.
The package contains these layers:

1. `APEIR.exe`: the portable Tauri 2 native launcher with the React/Vite interface embedded.
2. `nous-runtime.exe`: the Python Runtime API sidecar.
3. `nousd.exe`: the authoritative Rust Kernel daemon.
4. `nous-provider-worker.exe`: the out-of-process provider worker.

The launcher does not replace Kernel authority. It starts `nousd` first,
passes a private NKI session to Runtime, then connects the embedded frontend to
the authenticated loopback Runtime API.

An unsigned internal Portable/NSIS test bundle is available. Use the canonical
[Quick Start download and verification steps](../getting-started/QUICK_START.md#native-installation).
Build and native sidecar checks passed on Server2025; current Windows10 installed
GUI and lifecycle acceptance remain PENDING.

## Host requirements

The supported local target is `x86_64-pc-windows-msvc` on Windows 10 X64.
The build requires:

- Rust and the `x86_64-pc-windows-msvc` target;
- Visual Studio 2022 C++ Build Tools;
- MSVC X64 `cl.exe` and `link.exe`;
- a Windows SDK containing X64 `kernel32.lib`;
- Node.js 22/npm dependencies already installed under `desktop`;
- Python with the project `installer-build` extra, including PyInstaller;
- the sibling locked Kernel checkout at the revision in
  `runtime-components.lock.json`, plus the exact locked release bytes already
  staged under `desktop/src-tauri/binaries`.

The build script does not install system software. It fails before writing
sidecars if the native toolchain is incomplete.

## Locked native inputs

The current lock targets Windows x64 and freezes Kernel
`87fd1b2ff28ef14ab1a515a58162592b452fda2e`. Required bytes are:

| File under `desktop/src-tauri/binaries/` | SHA-256 |
| --- | --- |
| `nousd-x86_64-pc-windows-msvc.exe` | `5453D0D78F5076722C8408E16629E656F6DE18526229F9A1E7EC6AE77664716C` |
| `nous-provider-worker-x86_64-pc-windows-msvc.exe` | `7CA450E42C64D25E1F450BB892AF7F21346BC094A1EEF1952A1B933933FAA973` |

Obtain the reviewed exact bundle described below and stage those two files
without changing the lock. `stage-kernel-components.ps1 -SkipBuild`
checks the Kernel checkout revision and invokes the actual PE/hash verifier; it
does not rebuild them. With an explicit `-ArtifactDirectory`, it verifies every
input against the maintained lock before copying any staged component, then
verifies the staged files again. A mismatched/missing component or dirty tracked
Kernel source rejects the entire input before replacing existing files.
Verify before running packaging:

```powershell
python scripts/ci/verify_kernel_components.py --repo-root . --kernel-root ..\kernel
.\scripts\stage-kernel-components.ps1 -KernelRoot ..\kernel -Target x86_64-pc-windows-msvc -SkipBuild
```

The historical 2026-10-10 audit found the original binaries unavailable
([issue #2](https://github.com/untrod/apeir/issues/2)). The separately reviewed
2026-10-26 migration below now supplies approved exact inputs. That historical
blocker is not the current component status. Packaging still verifies every
input before full tests or Runtime sidecar generation; arbitrary rebuilds with
different hashes require their own approval.

### R4 trusted candidate evidence — 2026-10-24

The bounded current inventory found no Kernel or Distribution Releases, zero
Kernel Actions artifacts, and no original release bundle among971 available
Distribution artifacts. The only older native diagnostic retained build logs,
not EXEs. This establishes `ORIGINAL_LOCKED_ARTIFACT_UNAVAILABLE` within the
audited sources; it does not claim a maintainer's private backup was examined.

| Component | Historical 2026-10-18 rebuild SHA-256 | R4 deterministic candidate SHA-256 |
| --- | --- | --- |
| `nousd` | `8F12A0A583AD27523849C1646C6C64F5ABE5E681CFBF2FC5320274224E6A907D` | `5453D0D78F5076722C8408E16629E656F6DE18526229F9A1E7EC6AE77664716C` |
| `nous-provider-worker` | `1DB92D70426F8E601E739E5A0203FC52E11F4FED008E51ECC424F782DCF5752B` | `7CA450E42C64D25E1F450BB892AF7F21346BC094A1EEF1952A1B933933FAA973` |

At that audit the old lock values were unchanged. The first R4 pair reproduced20-byte
timestamp/debug-identity variance with otherwise equal PE contents; both real
smoke runs passed. Candidate-only `RUSTFLAGS=-C link-arg=/Brepro` then produced
identical **unmodified Kernel EXE bytes** in two clean recorded environments:
[actual build/comparison](https://github.com/untrod/apeir/actions/runs/40084421303).
This qualifies that pair, not universal reproducibility or the PyInstaller EXE.

Both real Kernel/Worker/Runtime smoke runs passed NKI1/2/3 health, wrong/missing
NKI credentials, unsupported versions, unauthorized model credentials before
provider spawn, production Runtime refusal with a bad NKI token, HTTP session
denial, protected owner-only token DACL and forced process-fault cleanup/restart.
The original failed Work was queried after restart without another submission.
No real model, untrusted workload, physical effect or installed GUI was claimed.
The build host was **Windows Server2025**, not Windows10: Rust/Cargo1.99.1,
MSVC14.51.36260.0, SDK10.0.26100.0, Kernel Cargo.lock SHA-256
`7FEFFACC76089D5CF6727EA2746C2F11410A391C9FBFACD6A3C2FE886C5A1F54`.
The frozen source actually supports NKI1/2/3; the old lock's1/2 metadata also
needs explicit review, never a silent compatibility rewrite.

The [primary unapproved candidate](https://github.com/untrod/apeir/actions/runs/40084421303/artifacts/12556562701)
contains actual EXEs, dependencies/signature records, hashes and scoped smoke
evidence. ZIP SHA-256 is
`cc98ba7c98c32abdf2132facf4da4283e921aa093840044dfb54cd2e7e808536`.
Artifacts expire after14 days; a maintainer must retain the exact approved bytes
in controlled durable storage before relying on them for ongoing distribution.
Those historical producer records identify unsigned, then-unapproved candidates;
they are preserved unchanged. No NSIS/Portable or Windows10 installation PASS
follows from this source build and compatibility result.

### Approved component-lock migration — 2026-10-26

The maintainer explicitly approved the two exact candidate hashes above for a
reviewed lock migration and **internal unsigned Portable/NSIS builds**. This
approval does not include signing, a formal Release or Windows10 installation
acceptance. Kernel source, component version, paths, lock schema and declared
NKI1/2 support remain unchanged. Historical tags and producer manifests retain
their original values; the original hashes were
`62AFAC19A5315BF9BBE19BBB1A3BE3011C1B4FA47E0653782E19F0BF7CC63E1B`
and `C4B65DB9844E752653C5CE8694105D1820BDF076B633E61F137DA7AC597F52B7`.

The migration changes only the two binary digests in the maintained lock.
The existing verifier independently admitted the actual x64 PE files and full
archive against that lock, including its checksums, producer revision and real
NKI recovery records. This is component integrity, not current installed Desktop
qualification. Normal PR checks and merge remain required before delivery.

Use producer run `40084421303`, artifact `12556562701` and the ZIP digest above.
The exact archive is retained privately for review; its Actions copy expires on
2026-11-07. A controlled durable distribution location still needs qualification;
never substitute a moving download or weaken admission after expiry.
Rollback must use a reviewed lock/source rollback with the corresponding exact
bytes. The unavailable historical EXEs cannot be reconstructed by changing their
hashes, and no previously published artifact is replaced in place.

### Approved GitHub Actions input

Only **after** the lock migration is approved, the exact candidate is retained,
and the maintainer authorizes `APEIR_BINARY_RELEASE_ENABLED=true`, select
`native_target=windows-x64` in the existing Desktop CI workflow. Supply the exact
producer run ID, artifact ID and ZIP digest. The pipeline rejects moving names,
fork/unrelated producer sources, expired archives, missing digests, unsafe ZIPs,
incomplete smoke records and bytes that fail the maintained component lock.
It then uses the official launcher below in full mode to produce Portable and
NSIS together, with checksums, a source manifest, validation report, original
Cargo.lock files and a Python **build-environment** SBOM. That BOM alone is not
complete native release provenance. Other native targets remain independently
gated; default `native_target=none` never opts them in.

```bash
gh workflow run desktop-build.yml --ref <approved-source-revision> -f native_target=windows-x64 -f approved_kernel_run_id=<reviewed-run-id> -f approved_kernel_artifact_id=<reviewed-artifact-id> -f approved_kernel_zip_sha256=<reviewed-zip-sha256>
```

The integration still cannot read repository Actions variables (HTTP403).
The maintainer configured the switch, and actual opt-in native runs now pass
the variable gate and admit the approved component bytes. This observed execution
does not imply direct settings access or installation acceptance. The full-mode
package below passed its own build and smoke; Windows 10 installation remains
PENDING. Required main/PR
CI is a separate gate and can still be blocked by Issue #88.

The actual Kernel import tables include `VCRUNTIME140.dll`. Build-host success
does not prove that a clean Windows10 host has the VC++ runtime. The x64 builder
therefore stages app-local CRT DLLs only from the selected Visual Studio x64
redistributable directory, requires valid Microsoft signatures and records their
versions/source/hashes in `native-dependencies.json`. A generated Tauri resource
overlay includes those same files in NSIS; Portable carries them beside the EXEs.
The component smoke checks the actual loaded CRT path when app-local CRT is
present. Clean Windows 10 installation still needs qualification; the packaging
checks do not alter the reviewed Kernel hashes or remove licensing/install gates.

## Current native command-qualified build

The [verified Portable/NSIS candidate](https://github.com/untrod/apeir/actions/runs/40659887576/artifacts/12806308503)
was built from `69c7e44114a5e6e7690f7cfa865eefcbe62aecd5` in
[full-mode run 40659887576](https://github.com/untrod/apeir/actions/runs/40659887576).
It contains PR #110's Work-submission and Relay corrections, plus the reviewed
model-protocol guards from PR #111. This source is not yet accepted main. The
original five-second HTTP failure in Issue #88 remains
unresolved; one successful native build does not override a failed required CI.

GitHub sign-in is required; this artifact expires on **2026-11-11**.
The outer archive SHA-256 is
`5a50e5f015405d0f3f4076a99fabb726dbaab9970d11df234942a4ac2f20c412`.

| File | SHA-256 |
| --- | --- |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `18AB74C44DB156A1571F63B494337EE9419A221E4FEC5FFEE6049C17397C7347` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `66469F2AEDEDF1F931BE2FAD2D0435AE739919B31AD3F16605336FB1E79A0AB0` |

Independent download checked all 22 checksums, 13 manifest entries, 11 nested
Portable files, actual NSIS payloads and the unchanged approved Kernel bytes.
Full source validation passed 5,933 cases with 95 skips and four warnings. Real
sidecar/authentication/cleanup smoke and the pure Workflow CLI recovery passed
on **Windows Server 2025**; original Run:
`wfr_1eb74c6decf94b0fbaf007e3ee81cee1`. No validation or smoke skip flags were used.

These are unsigned internal test packages. **Windows 10 installation, native GUI,
upgrade/uninstall, Defender, real model inference and signing remain unqualified.**
The manifest's source ID is the build identity; a documentation commit does not
change those bytes. Follow [Quick Start](../getting-started/QUICK_START.md#native-installation)
for download, checksum and first-run instructions.

The earlier accepted-main package `51d7462` and its exact hashes remain in the
[historical verification record](../../acceptance/ENGINEERING_REVIEW.md#historical-native-package-verification--2026-10-27).

## Verified internal native build — 2026-10-27

The original `9f43909` package record is retained in
[Engineering Review](../../acceptance/ENGINEERING_REVIEW.md#earlier-internal-package--source-9f43909).
It predates frozen CLI discovery qualification; use the current build's own
manifest and checksums rather than substituting historical results.

## Build

From the Runtime repository root:

```powershell
.\scripts\build-windows-x64-launcher.ps1
```

Full mode runs the frozen Kernel's unchanged test script in a temporary
stdlib-only Python environment. This prevents an installed Distribution Wheel
from shadowing the Kernel's own namespace fixture. The parent build environment
and production Artifact implementation stay unchanged; real Sidecar smoke later
uses the actual Distribution. This dependency separation is not a workload
security sandbox. See the [reproduced import collision](../../acceptance/ENGINEERING_REVIEW.md#frozen-kernel-test-environment-separation--2026-10-27).

To reuse an already built and independently validated lean Runtime sidecar:

```powershell
.\scripts\build-windows-x64-launcher.ps1 -SkipRuntimeSidecarBuild
```

For an already validated working tree:

```powershell
.\scripts\build-windows-x64-launcher.ps1 -SkipValidation
```

`-SkipValidation` and `-SkipSidecarSmoke` are development shortcuts, not qualified
delivery modes. A deliverable build must run full validation and real Sidecar smoke.

## Outputs

Successful builds write only under `artifacts\windows-x64`:

- `APEIR-Portable\APEIR.exe` plus the three base-named sidecars;
- `APEIR-Portable-0.1.0-rc1-windows-x64.zip`;
- the Tauri-generated `APEIR_0.1.0-rc1_x64-setup.exe`;
- `APEIR-0.1.0-rc1-windows-x64.manifest.json`;
- `release-manifest.json`;
- `native-validation-report.json`;
- `SHA256SUMS.txt` and `SHA256SUMS-x64.txt`.

The sidecar smoke gate verifies PE machine `0x8664`, Kernel-first startup,
private NKI authentication, Runtime bearer authentication, Provider Worker
health, and complete shutdown of both process trees before Tauri packaging.

## Startup failure handling

The Launcher resolves Runtime credentials and log handles before starting
Kernel. If Kernel or Runtime process management fails later, it attempts cleanup
of both managed process trees and revokes the local session token.

Logs are under:

```text
%LOCALAPPDATA%\Nous\logs\nousd.log
%LOCALAPPDATA%\Nous\logs\runtime-api.log
```

## Historical Windows host evidence (2026-08-29)

The following retained evidence describes the older `2.0.0-rc3` package and its
then-available host. It does not certify today's `0.1.0-rc1` bytes or installed
product. Current Windows installation, restart/uninstall, APEIR.exe screenshots,
SBOM, signing, security and supply-chain qualification must follow the
[Release Runbook](../../acceptance/RELEASE_RUNBOOK.md). No Windows host is attached
to the current Cloud audit; no new NSIS/portable artifact or native screenshot
was produced.

The recorded host is Windows 10 19045 X64 and now has the complete official
MSVC build chain: Visual Studio 2022 C++ Build Tools, X64 `cl.exe`/`link.exe`, a
Windows SDK with X64 `kernel32.lib`, Rust/Cargo, Node/npm, Python, PyInstaller,
and the Tauri CLI.

The 2026-08-29 production build completed successfully. The Runtime sidecar was
built in `artifacts\build-env\windows-x64` so optional packages installed in the
developer's global Python environment are not silently included. The final
native validation report passed, and all nine entries in `SHA256SUMS.txt` were
independently recomputed using paths relative to the artifact root.

The portable launcher has been started on this Windows 10 host with `nousd` on
loopback port 8771 and Runtime on loopback port 8770. Authenticated status and
health endpoints reported Runtime 2.0.0-rc3 ready, and forced launcher shutdown
closed both managed process trees and released both ports.

The native fault matrix passed for forced Runtime and Kernel termination,
Desktop restart recovery, token corruption, port conflict, Provider Worker
crash isolation, and temporary checkpoint database corruption. The report is
`artifacts\build-logs\p11-native-fault-matrix-20260829-140047.json`.

The separate Runtime and Kernel restart buttons in the Desktop diagnostics UI
remain unclicked because UI automation is unavailable under the current Windows
ACL sandbox. Real recovery through Desktop restart passed.

The NSIS executable is built but its install/repair/upgrade/uninstall/reinstall
lifecycle has not been executed on this host. That machine-changing test remains
an explicit release gate.

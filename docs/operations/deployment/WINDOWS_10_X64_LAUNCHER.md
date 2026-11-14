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
Windows 10 ARM64, including a dual-boot tablet, is a different target. The x64
bundle below has x64 Runtime, Kernel and Worker components; it is not an ARM64
native package. [ARM64 preparation and qualification](WINDOWS_10_ARM64_LOCAL.md)
uses the same launcher script with an explicitly approved target profile. Some ARM Windows builds provide x64 emulation, but neither that runtime
nor this package on it has been qualified. Record the OS build and test it as a
separate compatibility scope; it cannot replace Windows 10 x64 installation
acceptance. Do not relabel the binaries or alter the component lock. Source/API
development on another host is likewise separate from native package support.

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

Producer run `40084421303`, artifact `12556562701` and the ZIP digest above are
the historical approval input. The exact archive remains retained privately;
its Actions copy expired on 2026-11-07 and now returns 404. Do not use that expired
ID for a new build. The full-mode carrier below retains the same locked EXE
bytes and original source/smoke records; it does not change their approval.
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

After the original candidate artifact expires, explicitly select
`approved_kernel_artifact_format=native-build` to recover the **same locked
components** from a reviewed successful full-mode native package. For the
2026-11-09 retained carrier, producer `42568225590`, artifact `13653822826`, the
outer ZIP SHA-256 is
`cd6592ed6a9117a9b27910d1d8bf45c27f6eaab6bc26f0ee0ad6c89d9bf50929`.
Its source is `dfec8c9c2614a3a80ab6ecb6c91fa6568722f5d5`; its Actions copy expires
2026-11-23. The pipeline still checks accepted source ancestry, exact artifact
identity/digest, complete checksums, Portable contents, dependency/source records,
original NKI denial/recovery and both actual PE hashes against the maintained
lock. A carrier is not a new build or a Windows 10 installation result. Retain
each subsequent qualified carrier before its expiry rather than repeatedly
rebuilding Kernel or changing its hashes.

```bash
gh workflow run desktop-build.yml --ref <approved-source-revision> -f native_target=windows-x64 -f approved_kernel_artifact_format=native-build -f approved_kernel_run_id=42568225590 -f approved_kernel_artifact_id=13653822826 -f approved_kernel_zip_sha256=cd6592ed6a9117a9b27910d1d8bf45c27f6eaab6bc26f0ee0ad6c89d9bf50929
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

The current unsigned Windows x64 package is [full-mode run43549734683](https://github.com/untrod/apeir/actions/runs/43549734683),
source `d94159ea45badf665999dffdafe6786a5e35c085`, preserved through
[PR154](https://github.com/untrod/apeir/pull/154).
[Artifact14097790424](https://github.com/untrod/apeir/actions/runs/43549734683/artifacts/14097790424)
requires GitHub sign-in and expires **2026-11-28**. The matching source pair is in
[Quick Start](../getting-started/QUICK_START.md#download-metadata).

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `8374139b89f070ab6e2982c8930055b3ff2fbf44d278756e32a538362e360a4e` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `95b65c4556e08812d64d5b0b631a9685d5000e0e26c38ecbc419144d8b030168` |
| Outer artifact ZIP | `eafb38ac9bde3bd57575d3de8d299829dc46631e52f81b1ea1ed6c390425f544` |

The official full launcher passed on **Windows Server2025 x64**, Python3.12.10,
Rust1.99.1, MSVC14.51 and SDK26100. Actual Kernel/Worker/Runtime smoke and
desktop Cargo check/tests passed, including10 Rust cases with a real Windows
credential round-trip and queued lifecycle mutation refusal at exit. Neither
validation skip switch was used. The frozen Kernel and approved component
hashes are unchanged.

Independent inspection checked the downloaded bytes, manifests, locked PE files,
Portable contents and NSIS payload. The application has only Tauri's expected
three-byte UNK/NSS bundle stamp difference between Portable and NSIS; all other
application payload bytes match. This build includes the Settings model roster,
saved local key selection and visible save/restart feedback. No real Provider
inference or Windows10 GUI/installation lifecycle is qualified by these checks.
Signing and public publication remain separate gates.

### Previous Studio extension producer — 2026-11-11

The preceding unsigned Windows x64 package is [full-mode run42977022966](https://github.com/untrod/apeir/actions/runs/42977022966),
source `70a5c69b1b2bd9f36f5f6725e7a1e7bdf411fd2d`, preserved through [PR144](https://github.com/untrod/apeir/pull/144).
[Artifact13837634414](https://github.com/untrod/apeir/actions/runs/42977022966/artifacts/13837634414)
requires GitHub sign-in and expires **2026-11-25**. The matching wheel/frontend
links are in [Quick Start](../getting-started/QUICK_START.md#download-metadata).

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `ff3e8a56f14d048aee24367f282617a92e89f2d3397406e008b8bac7008e4b85` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `5896b513211d25dd3518fa7570c1d69bd343bf80babd756f63b5695355f863e3` |
| Outer artifact ZIP | `47e35e52c46d18eab6fe1c22bc6850616911656882d15bd593316234d4f5a33d` |

The official launcher ran full validation without either skip switch on
**Windows Server2025 x64**, Python3.12.10, Rust1.99.1, MSVC14.51 and SDK26100.
Actual Kernel/Worker/Runtime startup, NKI1/2/3 authentication and refusal, original
request recovery, pure Workflow restart and owned-process fault cleanup passed.
Authenticated feature discovery reports `data.workflow.summary` and executable
UI `BLOCKED`; it does not grant plugin access or qualify installation.
No external model call was made. Frozen Kernel source and approved component
hashes are unchanged.

Independent admission checked the downloaded archive, manifests, locked PE bytes,
Portable contents and all eleven NSIS application files. Ten match Portable
exactly; the launcher has only the upstream three-byte Tauri UNK/NSS bundle stamp
difference. Actual hashes were retained, not normalized.

The compact Workflow Monitor 1.0.1 example is installed separately. Its later
manifest, viewport test and documentation changes leave the producer's Runtime,
Desktop, dependencies, component lock and build inputs unchanged.
`installation_acceptance=NOT_RUN`: inspection and Server smoke are not Windows10
GUI installation, upgrade/uninstall or Defender acceptance. These remain
**PENDING**; signing and public publication retain their separate gates.

### Previous model lifecycle producer — 2026-11-10

The preceding unsigned Windows development bundle is [full-mode run42657287823](https://github.com/untrod/apeir/actions/runs/42657287823),
source `c12cb97f13990287b3638e7913aa330d05b4e562`, reviewed in [PR143](https://github.com/untrod/apeir/pull/143).
[Artifact13696179576](https://github.com/untrod/apeir/actions/runs/42657287823/artifacts/13696179576)
expires on **2026-11-23** and requires GitHub sign-in. Subsequent test and
documentation changes do not change this package's production or build inputs.

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `791a3ef42833e98bbd27a816568df8bbf4a87ac20b65a2ae330f9f707d5cbc46` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `bf26ea3002d20f334e21b3a6acdc4aa0aee15cff96fcf56a72cd546c2bdfbbb6` |
| Outer artifact ZIP | `75b7112b4c802c417891fbff1dc0789389e6660053cefd9836d61c9cf973cab7` |

The official launcher completed full validation without SkipValidation or
SkipSidecarSmoke on **Windows Server2025 x64**, Python3.12.10, Rust1.99.1,
MSVC14.51 and Windows SDK26100. Actual Kernel/Worker/Runtime startup, NKI1/2/3
authentication/refusal, original-request recovery, pure Workflow restart and
owned-process fault cleanup passed. Native smoke made zero external model calls.
Independent admission checked the actual archive, manifests, PE architecture,
approved component hashes, Portable contents and all eleven NSIS application
payload files. Ten match Portable exactly; the launcher retains the upstream
Tauri UNK/NSS bundle stamp difference. Actual hashes were not normalized.

This source contains the reviewed model lifecycle/deadline, Conversation
connection ownership and Node status projection fixes. Frozen Kernel source and
approved component hashes are unchanged. Historical Windows timing issues stay
open; a passing build does not establish their universal cause.
`installation_acceptance=NOT_RUN`: NSIS was inspected, not installed. Windows10
GUI, graceful application exit, upgrade/uninstall and Defender remain **PENDING**;
signing, supply-chain review and public release retain their independent Gates.
The qualified Linux Python VM is not a Windows execution sandbox. Read the
[Windows guide](../getting-started/INSTALL_WINDOWS.md) before opening the package.

### Previous Context and backup producer — 2026-11-09

The preceding unsigned Windows development bundle is [full-mode run42568225590](https://github.com/untrod/apeir/actions/runs/42568225590),
source `dfec8c9c2614a3a80ab6ecb6c91fa6568722f5d5`, accepted through [PR139](https://github.com/untrod/apeir/pull/139)
as main `df4fdceabf57a652a381a1ff72267df6f3ff5394` with the same tree.
[Artifact13653822826](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13653822826) expires on **2026-11-23** and requires
GitHub sign-in. A later documentation commit is not a different binary build.

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `16413ffa81a186edfd4aec36ac4ec8828e2b31fcd77a6174b74f2aa139c9dd96` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `942ea3bb2fe838e8d163c113a69e74ce2ae70a5fd79977984778efd36e476aeb` |
| Outer artifact ZIP | `cd6592ed6a9117a9b27910d1d8bf45c27f6eaab6bc26f0ee0ad6c89d9bf50929` |

The official launcher completed full validation without SkipValidation or
SkipSidecarSmoke. Independent admission verified the actual manifest, checksums,
Portable contents and maintained Kernel/Worker hashes. Independent NSIS payload
inspection found the expected eleven application files: ten exact Portable hash
matches and the upstream Tauri bundle-type stamp difference in the launcher.
Actual hashes were retained, not normalized.

Real Kernel/Worker/Runtime startup, NKI1/2/3 authentication and refusal, original
request recovery, pure Workflow CLI/restart and owned-process fault cleanup passed
on **Windows Server2025**. Native smoke made zero external model calls.
`installation_acceptance=NOT_RUN`: the installer was inspected, not installed.
Graceful GUI exit, clean Windows10 installation, upgrade/uninstall and Defender
remain **PENDING**; signing, complete supply-chain review and public release
require their own Gates.

This package includes the Context connection/schema and WAL backup fixes from
PR140, integrated through PR139. Historical Skill/Context HTTP timing issues stay
open; neither this build nor one passing regression establishes a universal cause.
The qualified Linux read-only Python VM is not a Windows execution sandbox.
See the [Windows guide](../getting-started/INSTALL_WINDOWS.md) before opening it.

### Previous governed-test and Relay producer — 2026-11-09

The preceding unsigned Windows development bundle is [full-mode run42534072393](https://github.com/untrod/apeir/actions/runs/42534072393),
source `4817e83c0cabeb879815edc5fba1c9d2f22fd628`, accepted through PR137 as main
`1dd5fc3aa1f17ebd01c5a4511eaca1de02a6d032`. [Artifact13640647666](https://github.com/untrod/apeir/actions/runs/42534072393/artifacts/13640647666) expires
on **2026-11-23** and requires GitHub sign-in. The source manifest
identifies the binary; later documentation does not change its qualification.

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `67d292a6f29f34a023011976d39ba3956c6448c5b59ec1d3c2b766238fdf6fbc` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `79c73802d34104915f40c14353e0c17a1ccc903516eb3eb9482b9811ef9356e3` |
| Outer artifact ZIP | `235b94bff1ad9ce76900afcc48dcc215ebb03a0708d4043db996b20efc577d9c` |

The official launcher ran in full mode, without SkipValidation or SkipSidecarSmoke.
Independent admission verified the actual checksums, manifest, nested Portable,
NSIS payload and locked Kernel/Worker bytes. Real Kernel/Worker/Runtime startup,
NKI authentication/refusal, query-only original-work recovery and cleanup passed
on **Windows Server2025**. No external model call was made by native smoke.
`installation_acceptance=NOT_RUN`: the installer was inspected, not installed.

This source includes the original Work test consumer, failure propagation,
passive evaluation and queued Relay cancellation. The Linux read-only Python VM
has its own scoped acceptance; it is not a Windows sandbox. Historical Windows
Skill/Context timing issues remain open. A green build does not establish their
common cause or qualify every model and plugin.

An unpublished draft can retain verified files for review; no public download
or stable Release is claimed. Windows10 GUI, install/upgrade/uninstall,
Defender, signing and publication authorization remain separate Gates.
Use the [Windows guide](../getting-started/INSTALL_WINDOWS.md) for preparation.

### Previous Relay read-error producer — 2026-11-02

The previous Windows development bundle is [full-mode run41543803229](https://github.com/untrod/apeir/actions/runs/41543803229),
source `2d8a044e51a39b75c2afd9a8eaccba4a72d42952`, accepted through PR132 as main
`edd09f224ad103dbdb3fe6db98958ad8251bd0c2`.
[Artifact13190523439](https://github.com/untrod/apeir/actions/runs/41543803229/artifacts/13190523439) expires on **2026-11-17** and requires GitHub sign-in.
Later documentation commits do not change this binary identity.

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `0571aa01b284701436bf59ecf478143ae5cc9a01a91aa7c51eaa901f88968e88` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `a26741530fbd0ca8c53f8582a10b4782623b7cc99ce26ed18fc37f16b302baa9` |
| Outer artifact ZIP | `879b745b206df9fc0c2205dc858b0d6fdd79e3f870eb5bb5cd701628766c4e44` |

The official full launcher ran without SkipValidation or SkipSidecarSmoke.
Independent inspection verified22 checksum entries,13 manifest entries,11 nested
Portable files, the actual NSIS payload and both approved Kernel PE components.
Real NKI requests1/2/3, Worker/Runtime authentication/refusal, original-work
recovery and process cleanup passed on **Windows Server2025**. External model
calls0; `installation_acceptance=NOT_RUN`. The installer was inspected, not executed.
The component lock continues to declare NKI versions1/2; exercised requests do
not extend that declaration.

This bundle contains the bounded Artifact-lock correction and preserves the
original Windows read error during strict Relay snapshot recovery. Before/after
Windows reproduction and exact-source Core/Desktop/Multi-Arch/Security passed.
Historical Skill HTTP and Context persistence deadlines remain open in
[Issue88](https://github.com/untrod/apeir/issues/88) and
[Issue116](https://github.com/untrod/apeir/issues/116); these fixes do not establish
a common cause for all Windows timing failures. No HTTP/test deadline,
persistence requirement or security assertion was relaxed.

Windows10 installed GUI, upgrade/uninstall, Defender, real-model and signing
qualification remain separate. See [Windows instructions](../getting-started/INSTALL_WINDOWS.md).
An unpublished Release draft stages notes only; no public Release asset is claimed.

### Previous Artifact-lock producer — 2026-11-02

The preceding Windows development bundle is [full-mode run41467950136](https://github.com/untrod/apeir/actions/runs/41467950136),
source `67186696426cad60b55fc3576dfde8b93defbb37`, the main integration of PR130.
[Artifact13157732606](https://github.com/untrod/apeir/actions/runs/41467950136/artifacts/13157732606) expires on **2026-11-16** and requires GitHub sign-in.
It predates PR132's Relay correction; its qualification remains scoped to its own bytes.

| File | SHA-256 |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `0c2a65bcfe1ac31108d7a99b03511bdc1ee9e22230fed55918e03c427bd21e18` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `077fc0ff0bad9621ba7a777a887a1155f13244e3bcb3a512a403eddba0452aa1` |
| Outer artifact ZIP | `90b303ac3222d45b525f96f790d8d3551e5e5c8d0625e7dfae2cb0b89f1ff810` |

The official full launcher ran without SkipValidation or SkipSidecarSmoke.
Independent inspection verified22 checksum entries,13 manifest entries,11 nested
Portable files, the actual NSIS payload and both approved Kernel PE components.
Real NKI1/2/3, Worker/Runtime authentication/refusal, original-work recovery and
process cleanup passed on **Windows Server2025**. External model calls0;
`installation_acceptance=NOT_RUN`. The installer was inspected, not executed.

This bundle includes the bounded Artifact-lock correction. Exact-source
Core/Desktop/Multi-Arch/Security passed; Core needed a failed-job retry. The first
60-second Context/EventStream persistence timeout remains retained in
[Issue116](https://github.com/untrod/apeir/issues/116); its cause is unresolved.
A green retry does not establish a repair for all historical Windows deadlines.
No HTTP/test deadline, persistence requirement or security assertion was relaxed.

Windows10 installed GUI, upgrade/uninstall, Defender, real-model and signing
qualification remain separate. See [Windows instructions](../getting-started/INSTALL_WINDOWS.md).
An unpublished Release draft stages notes only; no public Release asset is claimed.

### Previous Studio entry-point producer — 2026-11-02

[Run41399894606](https://github.com/untrod/apeir/actions/runs/41399894606) produced
source `26bf2c18ff3547eac959bca836dcb5042be5d2bf`; its tree matches PR129's main integration
`30b9860`. [Artifact13123801136](https://github.com/untrod/apeir/actions/runs/41399894606/artifacts/13123801136) expires2026-11-16.
Setup SHA-256 `99dec30c65bb3dc8391c78b008c002a34b71fb1a779fc923083aeaac7fe023f8`;
Portable `dffa4ef6944a34b3d2d1da4e72590a75c22422c161f517c77e3260c6953fcc65`;
outer ZIP `9107f4881abda46717bc7085af7e65c5c4eaedbe86f063f9c15b98c4a50f8132`.
Its full build and component Smoke passed on Server2025, installation NOT_RUN.
It predates PR130's lock correction and is retained as historical evidence,
not offered as the current corrected build.

### Previous main producer — 2026-11-01

The previous reviewed producer is [full-mode run41309010299](https://github.com/untrod/apeir/actions/runs/41309010299),
from main `5bdbadf2a072c222b016b1ccbe8b89ad5e0c25ff` (PR124/125 integration).
It includes Overview 2.0, the approved single-turn model host, original-event
recovery and atomic Evaluation/Experience schema initialization.

In **Artifacts**, select **windows-x64-native-development-build**. GitHub sign-in
is required; this run's native artifact is retained until **2026-11-15**. Use it
only after **Build Windows x86_64** succeeds. A successful frontend or source
preview job does not qualify the Native package.

The artifact is the build record. Keep these files together:

| Record | Check |
| --- | --- |
| `source-manifest.json` | Exact Distribution/Kernel revisions and component-lock digest |
| `release-manifest.json` | Packaged filenames, sizes and SHA-256 |
| `SHA256SUMS.txt` | Hashes of this build's actual Portable, installer and resources |
| `native-validation-report.json` | Actual host, full-validation flag, sidecar Smoke and installation status |
| `reviewed-input-provenance.json` | Reviewed Kernel producer, artifact identity and archive digest |

Require `status=passed` and `full_validation_executed=true` in the native report.
Its `installation_acceptance=NOT_RUN` is deliberately independent. The full-mode
entry does not use SkipValidation or SkipSidecarSmoke. It checks real NKI health,
authentication refusal, Worker/Runtime startup, restart/query of original Work,
app-local CRT and owned-process cleanup. Model-free Smoke is not live inference.

Application/sidecar executables are unsigned x64 PE; the NSIS bootstrapper is x86,
which does not change the architecture of its packaged Runtime. Independent
inspection uses the unchanged component verifier, both checksum lists, release
manifest, nested Portable and extracted NSIS payload. Tauri's documented
three-byte Portable/NSIS bundle stamp is reported separately; actual files and
published hashes are never normalized.

**Windows 10 GUI/install/upgrade/uninstall, graceful Desktop exit, Defender,
real-model inference and signing retain their separate Gates.** A CI host is not
a clean Windows 10 installation. Preserve original timing failures; a successful
build does not establish their common cause.

Use [Quick Start](../getting-started/QUICK_START.md#native-installation) for
download and verification. These are unsigned internal development packages,
not stable Releases. The earlier AACB package's exact hashes and measured
acceptance remain in [Engineering Review](../../acceptance/ENGINEERING_REVIEW.md#native-package-integrity-and-context-http-timing--2026-10-29).
Do not substitute a historical hash or payload merely because filenames match.

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

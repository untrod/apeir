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
| `nousd-x86_64-pc-windows-msvc.exe` | `62AFAC19A5315BF9BBE19BBB1A3BE3011C1B4FA47E0653782E19F0BF7CC63E1B` |
| `nous-provider-worker-x86_64-pc-windows-msvc.exe` | `C4B65DB9844E752653C5CE8694105D1820BDF076B633E61F137DA7AC597F52B7` |

Obtain the original pinned release bundle from the maintainer and stage those
two files without changing the lock. `stage-kernel-components.ps1 -SkipBuild`
checks the Kernel checkout revision and invokes the actual PE/hash verifier; it
does not copy files or rebuild them. Verify before running packaging:

```powershell
python scripts/ci/verify_kernel_components.py --repo-root . --kernel-root ..\kernel
.\scripts\stage-kernel-components.ps1 -KernelRoot ..\kernel -Target x86_64-pc-windows-msvc -SkipBuild
```

The 2026-10-10 product audit found both files absent, no published Kernel Release
assets and zero Kernel Actions artifacts. The original bundle's current public
download location is unavailable: this is [issue #2](https://github.com/untrod/apeir/issues/2),
not a hash-validation PASS. A source rebuild with a different digest requires
separate normalization/re-lock/version review and maintainer approval. Packaging
now verifies these inputs before full tests or Runtime sidecar generation. The
source frontend can be developed independently while this gate is BLOCKED.

## Build

From the Runtime repository root:

```powershell
.\scripts\build-windows-x64-launcher.ps1
```

To reuse an already built and independently validated lean Runtime sidecar:

```powershell
.\scripts\build-windows-x64-launcher.ps1 -SkipRuntimeSidecarBuild
```

For an already validated working tree:

```powershell
.\scripts\build-windows-x64-launcher.ps1 -SkipValidation
```

Do not use `-SkipSidecarSmoke` for a deliverable build.

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

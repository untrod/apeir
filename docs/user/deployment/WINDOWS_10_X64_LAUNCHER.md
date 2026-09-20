# Windows 10 X64 Launcher build

Nous Desktop is the launcher and control surface for the complete local product.
The package contains these layers:

1. `Nous.exe`: the Tauri 2 native launcher with the React/Vite interface embedded.
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
- Node.js/npm dependencies already installed under `desktop`;
- Python with the project `installer-build` extra, including PyInstaller;
- the sibling locked Kernel checkout at the revision in
  `runtime-components.lock.json`.

The build script does not install system software. It fails before writing
sidecars if the native toolchain is incomplete.

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

- `Nous-Portable\Nous.exe` plus the three base-named sidecars;
- `Nous-Portable-2.0.0-rc3-windows-x64.zip`;
- `Nous_2.0.0-rc3_x64-setup.exe`;
- `Nous-2.0.0-rc3-windows-x64.manifest.json`;
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

## Current host status

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
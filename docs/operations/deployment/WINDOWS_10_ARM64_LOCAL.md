# Windows ARM64

<a name="windows-10-arm64-local-development"></a>

Windows on Arm needs the **ARM64** build, including a Xiaomi Pad5 running
Windows 10 ARM64. It does not need a 32-bit APEIR build. Android is a different
platform. Do not rename or substitute an x64 EXE.

[**Download ARM64 Setup + Portable**](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13901748571) ·
[Hashes and source](../getting-started/QUICK_START.md#download-metadata).

The unsigned 0.1.0-rc1 bundle passed the full native build, real NKI/Runtime
smoke and installed-sidecar checks on Windows 11 ARM64. Download requires
GitHub sign-in and expires on **2026-11-25**.
[Quick Start](../getting-started/QUICK_START.md) remains the installation entry.
Windows 10 tablet GUI, drivers, Defender, upgrade and uninstall acceptance are
**PENDING**. The current build host is Windows 11 ARM64, not the tablet.

## First tablet test

Use the ARM64 Portable ZIP from the download above for the first check.
Extract the outer GitHub artifact ZIP first, then verify the Portable ZIP
against the ARM64 hash in Quick Start; stop on a mismatch.
Extract the whole package and open `APEIR-Portable/APEIR.exe`; keep its sidecars
and DLLs together. You can skip model configuration and inspect Files, Workflow
and service status first. An absent model is not a successful inference test.

If this device already has Nous/APEIR data, back up the workspace and
`%LOCALAPPDATA%\Nous` before starting. Portable uses that same per-user state
location; it is not a separate data sandbox. Use a separate Windows test account
for a clean acceptance run, and only an isolated copy for old-data migration.
Never upload credentials or the full application-state directory as diagnostics.

Record the Windows edition/build from `winver`, available RAM, launch result,
Runtime/Kernel status, and whether exit/restart leaves unexpected processes.
If Windows security blocks the unsigned application, retain the exact warning
and stop; do not disable Defender or SmartScreen. Driver, touch, high-DPI and
WebView2 behavior on the Pad5 remain target-device checks.

## Historical host evidence

An earlier Nous 2.0.0-rc3 qualification used a Xiaomi Snapdragon device:

| Item | Reported environment |
| --- | --- |
| Windows | Windows 10 ARM64, build 19045 |
| Python | 3.12.10 ARM64 |
| Node.js | 24.16.0 ARM64 |
| Rust | 1.97.1, ARM64 MSVC target |
| WebView2 | Installed |
| Exercised scope | Runtime/CLI and frontend validation |

These are the original host facts, not a current-version retest or native
installation qualification. Existing `nous` names remain compatible; current
user commands use `apeir`.

## Current source workflow

Install the matching Distribution checkout in an ARM64 Python environment using
[Developer Setup](../getting-started/QUICK_START.md#developer-setup).
From a selected project, model-free startup uses:

```powershell
apeir --no-intelligence runtime-api start
```

Keep that terminal open. In a second activated shell from the same project:

```powershell
apeir runtime-api status --json
```

Connect Studio using the [session instructions](../getting-started/QUICK_START.md#model-free-runtime-api-and-source-interface).
Source UI is a browser surface; it is not an installed Tauri application.

Provider configuration and actual inference have separate requirements.
Follow the [Provider guide](../guides/PROVIDER_GUIDE.md). Store a credential
reference rather than a raw key in configuration. A model-disabled process
cannot infer, and a profile does not replace its required authenticated Kernel.

## Native ARM64 boundary

Native builds use a supported Windows 11 ARM64 builder, CPython 3.13.17 and
MSVC. Users of the completed bundle will not need Python, Rust or MSVC to open
APEIR. WebView2 and operating-system compatibility still require target-host checks.

Two independent builds of frozen Kernel `87fd1b2ff28ef14ab1a515a58162592b452fda2e`
produced matching ARM64 Kernel and Worker bytes. Both real NKI/Runtime sidecar
smokes passed on Windows 11 ARM64. The maintainer approved these exact inputs
and internal unsigned builds on 2026-11-11; see the
[component approval](../../acceptance/ENGINEERING_REVIEW.md#approved-arm64-component-baseline--2026-11-11).
The existing x64 component hashes are unchanged.

The required **Windows ARM64 metadata (not native acceptance)** check is still
a metadata check. Actual Native Smoke and package checks have their own reports;
none alone establishes Windows 10 installation or tablet-driver compatibility.

ARM64 native startup does not qualify local-model GPU acceleration, every
Provider or a strict command sandbox. Test execution stays BLOCKED without its
qualified environment; there is no unrestricted host-Shell fallback.

The available unsigned **x64** test bundle has its own
[build record](WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build).
It is not evidence of ARM64 compatibility; x64 emulation is not native ARM64
acceptance. Do not follow the old RC3 branch-upload/download procedure.

See the [platform support policy](../platform/PLATFORM_SUPPORT_POLICY.md)
and [compatibility matrix](../../development/COMPATIBILITY_MATRIX.md) for scope.

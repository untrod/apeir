# Windows 10 ARM64 local development

Use the [Quick Start](../getting-started/QUICK_START.md) for current source
installation. This page records the ARM64 host boundary; it is not an ARM64
installer download.

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

The native ARM64 Visual Studio 2022 C++ toolchain requires Windows 11 on Arm.
The Windows 10 ARM64 host above did not qualify native Tauri linking.

The repository's **Windows ARM64 metadata (not native acceptance)** check does
not produce or qualify an installed ARM64 application. A native build needs a
supported builder, exact approved target-native components, current full-mode
pipeline and installation evidence. No current ARM64 installer is promised here.

The available unsigned **x64** test bundle has its own
[build record](WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build).
It is not evidence of ARM64 compatibility; x64 emulation is not native ARM64
acceptance. Do not follow the old RC3 branch-upload/download procedure.

See the [platform support policy](../platform/PLATFORM_SUPPORT_POLICY.md)
and [compatibility matrix](../../development/COMPATIBILITY_MATRIX.md) for scope.

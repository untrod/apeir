# Windows ARM64

<a name="windows-10-arm64-local-development"></a>

Use the native **ARM64** build for Windows on Arm. The application includes its
Runtime, Kernel and Worker; Python, Node.js and Rust are not required to open it.

[**Download ARM64 Setup + Portable**](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14097648427) ·
[Install and verify](../getting-started/INSTALL_WINDOWS.md) ·
[Version and hashes](../getting-started/QUICK_START.md#download-metadata)

## Requirements

WebView2 is required. The current 0.1.0-rc1 package is an unsigned Developer
Preview. It has been built and checked on Windows 11 ARM64; Windows 10
installation and device-driver compatibility are still being verified.

<a name="first-tablet-test"></a>

## First launch

1. Download and extract the bundle, then verify its checksums.
2. Use Setup, or extract the included Portable ZIP and open
   `APEIR-Portable/APEIR.exe`. Keep its adjacent files together.
3. Select a project folder. You can skip model setup and use Files or Workflow.
4. Connect a model later through **Settings → Models & credentials**.

Portable uses `%LOCALAPPDATA%\Nous` for application state. Back up that directory
and existing projects before trying an upgrade; use a copy for compatibility
checks. If Windows blocks the unsigned app, retain the warning and stop rather
than disabling system protection.

## Current source workflow

For development, use an ARM64 Python environment and follow
[Developer Setup](../getting-started/QUICK_START.md#developer-setup).
Connect the browser interface using the [Runtime session instructions](../getting-started/QUICK_START.md#model-free-runtime-api-and-source-interface).

## Native ARM64 boundary

The package uses approved ARM64 components from the frozen Kernel source.
Build and installed-sidecar reports are retained with the download; the
[component record](../../acceptance/ENGINEERING_REVIEW.md#approved-arm64-component-baseline--2026-11-11)
describes their provenance. Local model acceleration and project-test isolation
depend on the installed service, hardware and execution environment.

<a name="historical-host-evidence"></a>

Older source-only host results remain in [Engineering Review](../../acceptance/ENGINEERING_REVIEW.md).
See [platform support](../platform/PLATFORM_SUPPORT_POLICY.md) and
[compatibility](../../development/COMPATIBILITY_MATRIX.md) for the maintained support scope.

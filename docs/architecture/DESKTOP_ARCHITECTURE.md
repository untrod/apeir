# Desktop Architecture

## Role

Nous Desktop is a native Tauri 2 control surface for Nous Runtime. It displays
Runtime state and submits governed user actions; it does not own task, model,
approval, provider, or credential state.

The React interface is packaged inside the native executable. Vite is a build
tool, not a separately hosted production website.

## Stack

- Tauri 2 native shell
- React and TypeScript interface
- Vite build pipeline
- Shared API client in `desktop/src/lib/api.ts`
- Runtime entity and event state under `desktop/src/store/`

## Data flow

```text
User action
  -> React component
  -> typed Desktop API client
  -> loopback Runtime API on port 8770
  -> governance and Runtime owner
  -> event or response
  -> Desktop store
  -> rendered view
```

The Control Plane on port 9770 is a separate node-management surface. Desktop
uses the Runtime API on port 8770.

## Local startup

When no authenticated Runtime is available, the native shell starts the embedded
`nous-runtime` sidecar. An unpackaged development checkout may fall back to
`NOUS_CLI_PATH`. The shell starts the process without a command shell, captures
stdout and stderr under `%LOCALAPPDATA%\Nous\logs`, and reads the random local
session token. The token remains session state and is never a Provider
credential.

Startup is idempotent: Desktop probes `/ready` before launching, reuses a healthy
Runtime, and reports a port conflict without rotating the active token. On
Windows, shutdown terminates the complete managed sidecar process tree so a
PyInstaller child cannot remain orphaned. A remote or externally managed Runtime
can still be entered manually.

## Security boundaries

- The default Runtime API binds to `127.0.0.1`.
- Non-public API routes require a random bearer session.
- CORS allows only Tauri and numeric-port loopback origins.
- Tauri exposes only the commands required to show the window and manage the
  local Runtime session; broad filesystem, HTTP, and shell plugins are disabled.
- Provider credentials remain owned by the Runtime credential provider. The
  Desktop setup flow never accepts or persists Provider API keys.
- Desktop state is a cache of authoritative Runtime state.

## Build

Web asset validation:

```powershell
npm --prefix desktop ci
npm --prefix desktop run build
```

Native Windows 10 X64 launcher and installer:

```powershell
.\scripts\build-windows-x64-launcher.ps1
```

This builds the embedded Runtime, the locked Kernel daemon and Provider Worker,
the Tauri/React launcher, a portable bundle, and an NSIS installer. See
[Windows 10 X64 Launcher build](../user/deployment/WINDOWS_10_X64_LAUNCHER.md).

Native Windows ARM64 package:

```powershell
npm --prefix desktop run tauri:build:arm64
```

Native builds require the matching Rust MSVC target, Visual Studio 2022 Build
Tools, and a Windows SDK. See
[Windows 10 ARM64 local deployment](../user/deployment/WINDOWS_10_ARM64_LOCAL.md).

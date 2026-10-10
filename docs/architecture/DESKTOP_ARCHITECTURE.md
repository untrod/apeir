# Desktop Architecture

## Role

APEIR Desktop is a native Tauri 2 control surface for APEIR Runtime. It displays
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

## Operations workbench

The existing Operations Console reads `/api/v1/control/operations`; its resource
navigation, searchable records, open collection tabs, resizable Evidence
inspector and collapsible activity panel all use that same projection. Refresh
updates the selected evidence record or removes it when the record disappears;
failed refresh clears cached state. Node trust and connectivity are separate
fields: an absent fact remains UNKNOWN. The console does not infer trust from
ONLINE or a Device's locator.

Only tab IDs, active view, inspector width, activity expansion and English/Chinese
navigation preference are stored in `apeir.operations.layout.v1`. Runtime
records, evidence and human identity are never layout state. Existing ThemeProvider
owns light/dark mode. Ctrl or Cmd with F focuses record search; arrow, Home and
End keys navigate open tabs; Ctrl or Cmd with backtick toggles activity and
Escape closes details. Narrow
screens stack the inspector and turn resource navigation into a horizontal list.
The workbench's language selector covers navigation and common controls; raw
backend evidence, identifiers, error reasons and compatibility terminology remain
unchanged. Existing authenticated sessions, PKCE, bound nonces and Governance
still own mutations. The simulated Demo entry links to the existing CLI flow;
it grants no execution authority.

Source frontend tests/build are software validation. They do not qualify an
installed Windows executable, NSIS lifecycle, real IdP or physical hardware.

The 2026-10-10 workbench audit reused the existing Console/API, ThemeProvider,
UI-state reset and signed Relay projection. It extended presentation and added
`trust_status=TRUSTED` to Nodes actually present in the canonical trust map;
that field grants no Operation permission. Software checks recorded 60 frontend
tests and 155 Control Plane/Controller/native-entry/lock regressions. Sandboxed
Chromium exercised the actual loopback Runtime API over a fresh persisted
simulated Demo: original mutation COMMITTED, independent MATCH and effect count1.
Desktop-size and 390-pixel mobile navigation were checked with zero page errors;
a stretched mobile navigation defect was corrected. Browser screenshots remain
local validation evidence and are not presented as installed APEIR.exe captures.
Native binary inputs and Windows installation qualification remain BLOCKED.

## Build commands

Web asset validation:

```powershell
npm --prefix desktop ci
npm --prefix desktop run build
```

Native Windows 10 X64 launcher and installer:

```powershell
.\scripts\build-windows-x64-launcher.ps1
```

This builds the embedded Runtime and Tauri/React launcher, packages already
staged locked Kernel/Provider Worker bytes, a portable bundle and an NSIS
installer. The script does not substitute a source rebuild for missing locked
bytes. See
[Windows 10 X64 Launcher build](../operations/deployment/WINDOWS_10_X64_LAUNCHER.md).

Native Windows ARM64 package:

```powershell
npm --prefix desktop run tauri:build:arm64
```

Native builds require the matching Rust MSVC target, Visual Studio 2022 Build
Tools, and a Windows SDK. See
[Windows 10 ARM64 local deployment](../operations/deployment/WINDOWS_10_ARM64_LOCAL.md).

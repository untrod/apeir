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

## APEIR Studio presentation shell

Studio is the same Desktop: use **Studio** in the native sidebar or **APEIR Studio
/ Open workspace** in source Operations. FlexLayout0.11.1 (MIT, React18, Node20+)
is pinned in the existing lockfile. ThemeProvider skins the docking controls;
the shell is lazy-loaded. No second Runtime or installer is introduced.

| Classification | Panels | Existing authority / view |
| --- | --- | --- |
| REUSE | Chat / Context | ChatView, Composer, ContextInspector; Conversation/Gateway/NKI |
| REUSE | Files / Editor / Controlled Commands | DeveloperWorkbench, WorkspaceProposals; Workspace/Governance/ProcessSession; not a PTY |
| REUSE | Models / Usage | DeveloperPlatform / Model Lab; original Usage journal |
| REUSE | Tasks | TaskCenter and existing EntityStore/EventClient |
| REUSE | Environment / Documents / Simulation | Existing Inspector/Workbench and their Runtime services |
| REUSE | Nodes / Devices / Workflow records / Evidence metadata / Governance Activity | One shared transient read of `/api/v1/control/operations`; Controller/Reality/Workflow/DistributedWork metadata and GovernanceStore audit owners |
| REUSE | Operations / detailed Inspector | OperationsConsole and its original human authentication/Governance |
| EXTEND | Docking and preset templates | Bounded versioned presentation JSON, no execution consumer |
| NEW | Frontend panel contribution table and stable portal hosts | Rendering/lifecycle only; not Runtime or authorization state |

Stable tab IDs address React portal hosts. Dragging reparents the existing host,
preserving drafts without remounting or replaying work. Closing/replacing a
protected editor is blocked until drafts and pending actions are resolved.
Closing a panel does not cancel backend Work. Existing editor/Operations
preferences remain intact; only a safe initial preset is derived from old tabs.

`apeir.studio.layout.v1` currently stores the global presentation choice. The
schema distinguishes global/workspace/dashboard/template documents; named
workspace libraries and Dashboard editing are not yet qualified. Import admits
only geometry, display fields and panel type references:96KiB,100 nodes,24
panels,8 levels, finite positive sizes and unique IDs. Unknown types render
Missing Component and load no code. No module URL, callback, resource identity,
token, content or grant is accepted. Popouts and executable third-party UI are
disabled. Layout export is not file draft persistence.

Controller/session changes retire original panel trees/requests before rendering
the new projection. Unsaved editor text is retained only in memory outside the
retired view. It is not shown as the new Controller's file or placed in layouts.
Explicit **Export previous private drafts** downloads private text; it does not
apply a change, create a Proposal or transfer it to another Runtime. Resolve or
explicitly discard archived drafts before leaving Studio. Reload/process exit
can still lose unsaved text. Original Work, approvals and effects remain owned
by Runtime, not a panel or layout.

Task and Chat trace selections reuse the existing DetailDrawer with the original
entity ID, scoped to that Studio session. The Activity projection here is the
Governance audit, not RuntimeEventBus or a durable Run EventStream. Evidence rows
are original Work receipt/verification metadata; rendering them is not CAS byte
integrity verification. Studio also hides the older ResourceDock to avoid a
second bottom workspace and its extra background usage polling.

The existing EntityStore also clears synchronously on a Controller/session
change. Its same IndexedDB record now carries cache-schema2 and a SHA-256 scope
digest bound to endpoint and bearer session; raw bearer material is never saved
there. A legacy/unscoped or mismatched cache cannot populate the current view.
Without WebCrypto, optional offline caching is disabled and current Runtime
reads continue. This is session isolation, not encrypted or authoritative
evidence storage. Runtime remains the history owner. App hydration/poll batches
recheck their captured connection after all requests settle, so one already
fulfilled old response cannot leak across a later connection change.

The Interactive preset currently composes text Chat/Models/Diagnostics only;
ASR/TTS, vision, microphone and Avatar are PENDING. Visual Workflow editing,
Dashboard widgets and an isolated external UI SDK remain PENDING. Workflow
panels display actual existing Workflow records, not a graph executor.

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
- Provider credentials remain owned by the existing credential paths. Native
  Windows setup/settings accept a transient password input through restricted
  Tauri IPC into Windows Credential Manager. Configuration retains environment
  reference names; keys are not stored in browser storage or ordinary Runtime
  API payloads. Browser-only setup uses existing references and cannot store keys.
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

Native session commands bind their returned session to the loopback endpoint
reported by the existing Tauri process manager. Endpoint, readiness and session
availability are checked before publishing that connection; the original
connection version and active view must still agree. Credential changes,
diagnostic recovery and workspace restart require the selected local Runtime.
Only the explicit **Start Local Runtime** action switches from another Controller
to local. Native startup preserves a selected remote Controller and does not
load a local token or create a local workspace for that remote connection.
An uncertain native action is not retried automatically, including session-reset
failure. Closing a view does not prove a dispatched native action was cancelled.

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

The workspace developer panel reuses `DeveloperWorkbench`, the existing workspace
API, `ChatView`/`Composer` and canonical EventStream. It is an Operations view,
not a second editor backend or Agent executor. File writes and fixed-profile runs
keep the existing service requester separate from human approval cookies; decisions
reuse the bound nonce and Governance admission. The same distinction applies to
read-only preview and Chat requests. Controller address/token changes invalidate the original
file reference and pending action instead of retargeting them. The existing
connection epoch also fences same-address identity replacement and A→B→A changes.
Unmounted Workspace views cannot continue approval-to-execution sequences; this
does not cancel an already admitted backend effect.

Workspace tabs retain unsaved drafts in memory during view changes. New panel
preferences contain only font size and collaboration/activity visibility, not
file contents, identity, grants or evidence. Explicit saved-file collaboration
passes a path/hash reference to the existing Chat Runtime with `read_only` enforced
by the send handler. It grants no file access and enables no model writes. Existing
Chat persistence is unchanged. Closing an active Chat panel aborts its request;
an aborted HTTP request does not prove a previously admitted effect was stopped.
There is no operating-system desktop/keystroke recorder or unrestricted container
launcher. See the [Quick Start](../operations/getting-started/QUICK_START.md#workspace-developer-panel)
for the actual user path and qualified scope.

Environment views also bind the existing URL/token/configuration epoch and their
mounted lifetime. Connection changes remount the original panel rather than
reusing approvals or output from another connection. Approval nonce acquisition,
decision and service continuation check the same original view; a late response
cannot start another environment operation or refresh an unmounted panel.
Environment reads, logs and Artifact metadata retain those same connection checks.
Closing a view does not prove an admitted workload stopped; recover its original
Runtime evidence before repeating an operation. Strong isolation remains required.

## Build commands

Manual **Desktop CI** also builds the existing Python Distribution wheel after
frontend validation. Its `apeir-python-source-preview-<commit>` Actions artifact
contains the wheel, measured SHA-256, a source manifest and minimal installed-wheel
validation evidence, retained for seven days. The job installs the built wheel in
an isolated virtual environment and runs the existing simulated lost-response
Demo; its original effect count remains one through recovery. Raw demo state and
generated keys stay outside the uploaded artifact. It contains no native
Desktop/Kernel binaries or Runtime state. The manifest
marks native integrity, installation and release qualification NOT_RUN; this
source package is independent of the gated native build jobs and publishes no
GitHub Release. A successful source-package job cannot satisfy native acceptance.

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

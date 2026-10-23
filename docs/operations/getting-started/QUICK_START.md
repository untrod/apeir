# Source Quick Start

This is the recommended entry point for APEIR Developer Preview. Use Git,
Python 3.10–3.12 and a writable checkout. No model API key, GPU or real device
is needed for source inspection and simulated examples. Current acceptance
and blockers live only in [ROADMAP](../../../ROADMAP.md).

A maintainer's manual **Desktop CI** run can provide the
`apeir-python-source-preview-<commit>` artifact in
[GitHub Actions](https://github.com/untrod/apeir/actions/workflows/desktop-build.yml).
It expires after seven days. The job installs its own wheel and exercises the
existing simulated recovery Demo; `source-preview-validation.json` reports that
scope. Check the source revision and `SHA256SUMS.txt` before
installing the wheel with `python -m pip install path/to/apeir_distribution-0.1.0rc1-py3-none-any.whl`.
This Python source package provides CLI/Runtime libraries, not APEIR.exe or a
Windows installer. Desktop source still needs the checkout below; real model,
Kernel, sandbox and native-release prerequisites remain separate. The manifest
does not claim those Gates passed.

## Install

```bash
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
```

Activate on Linux/macOS:

```bash
source .venv/bin/activate
```

Or on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the source package and check the actual entry points:

```bash
python -m pip install -e .
apeir version
apeir --help
apeir-node --help
apeir-controller --help
```

The package is `apeir-distribution`, currently `0.1.0-rc1` (Python metadata may
normalize it to `0.1.0rc1`). `nous`, `nous_runtime` and `NOUS_*` remain
compatibility names. Do not install obsolete `nous-runtime==0.1.0a0` or use an
unverified one-line installer, container image or Homebrew formula.

## First inspection

```bash
apeir --no-intelligence status
apeir --no-intelligence capability list
apeir --no-intelligence provider list
```

These commands inspect actual local Runtime state. Missing Providers, Kernel
services or optional dependencies are reported; they do not establish execution
or hardware acceptance.

## First verified execution

```bash
apeir demo --workspace ./demo-match --phase prepare --json
apeir demo --workspace ./demo-match --phase resume --approve-once --json
```

Use an empty dedicated directory. The first command persists an AgentSession,
Plan and Work and pauses for approval. The second explicitly approves once as
the local OS user, resumes the original Work through signed Node execution,
observes independently and commits only on MATCH. Without approval no mutation
occurs. [Verified Demo details](../../../examples/hello_runtime/README.md) include
Deny, MISMATCH, UNKNOWN, lost-response reconciliation and process restart commands.
This is simulated Runtime-service execution; Kernel is not traversed and no
physical or remote-human acceptance is claimed. Keep generated private keys and
databases out of Git and public issue attachments.

See the [example gallery](../../../examples/README.md),
[public Developer SDK](../../development/DEVELOPER_PLATFORM.md) and
[canonical architecture](../../architecture/README.md). Models never grant
authority; a Receipt is not an Observation, and UNKNOWN cannot commit an effect.

## Public SDK examples

After the source installation above, install the existing Provider SDK from the
same checkout; no published SDK wheel is assumed:

```bash
python -m pip install -e sdk/provider/python
python examples/hello_provider/run_example.py --workspace ./provider-demo
python examples/hello_skill/run_example.py --workspace ./skill-demo
```

Use separate empty directories. The [Provider example](../../../examples/hello_provider/README.md)
executes an explicitly allowed read-only Work through a signed Node and checks
denied/unknown/approval-required requests. The [Skill example](../../../examples/hello_skill/README.md)
installs, discovers, loads and disables actual instructions with CAS provenance;
it grants no authority and runs no device operation. Both import public SDK
contracts, not internal Runtime modules. Their printed workspaces retain evidence.

## Development and optional components

### Model-free Runtime API and source interface

From the project directory you want to inspect, start the existing authenticated
API in the foreground:

```bash
apeir --no-intelligence runtime-api start
```

This explicit process-wide mode keeps every model disabled, including saved
Providers. It preserves production Governance and sandbox checks; independent
Runtime-service features remain available without claiming a healthy Kernel.
It does not erase Provider configuration. Stop this process before starting the
normal model-enabled mode with its required authenticated Kernel. Do not set
development mode to bypass that requirement.

In another activated shell, check the API and locate its protected local session
file (this prints the path, not the token):

```bash
apeir runtime-api status --json
apeir runtime-api token-path
```

For the source web interface, use the same checkout and Node.js 22:

```bash
cd desktop
npm ci
npm run dev -- --host 127.0.0.1
```

Open the loopback URL printed by Vite. Expand **Controller connection**, set
**API URL** to `http://127.0.0.1:8770`, then enter the token from the owner-only
local file in **Service session token** and select **Connect**. Set the address
before entering the token: editing it clears the draft, and changing Controllers
never reuses the old session automatically. The field clears after submission;
the existing session-only connection state survives page reload. It is not a
Provider API key or human approval identity. Treat it as a credential: do
not include it in logs, screenshots or issue attachments. Existing externally
managed authentication uses its own session instead. The browser cannot launch
native sidecars or store Provider secrets. Keep both foreground processes open;
stop the interface and API when finished. This is source UI/HTTP operation,
not an installed Windows executable. File approvals still require a separately
enrolled authorized human; test execution remains BLOCKED without a qualified
sandbox. An API health response does not establish model inference or execution
qualification.

For repository tests and the numerical reference task:

```bash
python -m pip install -e ".[dev,a2a,mcp,scientific]"
python -m pytest -q tests/repository tests/developer_platform
```

For the existing thermal report reference, run
`python -m scripts.acceptance.scientific_preview_preflight` to inspect actual
prerequisites. Exit 2 / BLOCKED is expected without the existing strong sandbox;
the probe performs no computation or report generation. See the
[scientific gallery](../../../examples/README.md#scientific-computation-and-reports)
for inputs, the independent reference and the qualified native command.

The [contribution guide](../../../CONTRIBUTING.md) defines full validation and
supported process-lifecycle environments. This focused command does not replace
the full merge/release gate. Desktop development needs Node.js 22; follow
[Desktop architecture](../../architecture/DESKTOP_ARCHITECTURE.md).
Install heavy AI, local LLM and installer extras only when specifically needed.

The [Compute Mesh runbook](../compute-mesh/OPERATIONS.md) covers persistent
Controller/Node deployment. [Installation notes](../INSTALLATION.md) explain
optional dependencies and platform boundaries. Native binary release acceptance
requires the separate [Release Runbook](../../acceptance/RELEASE_RUNBOOK.md).

## Troubleshooting and feedback

Run `apeir doctor`, retain the command, platform and exact error, and follow
[troubleshooting](TROUBLESHOOTING.md). Inspect diagnostics before sharing and
remove credentials and private paths. Report reproducible issues through
[GitHub](https://github.com/untrod/apeir/issues); security reports follow
[SECURITY](../../../SECURITY.md).

### Workspace developer panel

In native first-use setup, environment facts come from the selected Runtime.
Choose the workspace and continue only after its actual path is confirmed.
Use **Configure model later** for keyless operation. Provider validation saves no
secret and performs no inference; after saving, **Models → Test** uses the
existing Gateway/NKI and reports original request/usage evidence. Missing Kernel
or credentials remains BLOCKED/UNCONFIGURED. See the
[configuration boundary](../../development/DEVELOPER_PLATFORM.md#first-use-configuration-and-model-tests).

For native local configuration, select the local Runtime before opening
**Settings → Credentials**. Windows credentials use the existing system store;
only reference names are persisted in configuration. The browser cannot store
Provider keys. **Start Local Runtime** connects to the endpoint reported by the
native manager, even if another Controller address is in the connection form.
Credential rotation, session recovery and workspace restart never retarget that
local session to a remote Controller. If the connection changes while an action
is pending, inspect its original local state before retrying. These software
guards do not qualify a Windows installer or a real model account.

Open **workspace / 开发者面板** in the existing Operations Console. The panel
combines the existing bounded workspace file API, diff editor, Chat Runtime and
persisted EventStream. Select a file, edit it, choose **Preview diff**, then
**Save atomically**. An approval-required save pauses before changing the file;
a separately enrolled human can approve the original request once or deny it.
Existing hash checks reject stale edits. Lost responses require inspecting the
original file/events before another write; the panel does not retry automatically.

Open up to 12 files in editor tabs. Each tab keeps its own draft, loaded SHA-256,
diff and save record in memory; selecting an already-open file restores that draft.
Use arrow keys, Home or End on the file tabs to navigate. Closing an unsaved file
requires explicit discard. A pending approval locks file navigation and resumes
only its original path, content and digest. All drafts must be saved or discarded
before execution or leaving for Environment Studio. To reload a file changed
outside APEIR, close its tab (explicitly discard if needed), then reopen it.
Drafts also remain in memory when switching Console tabs; a dirty or pending
workspace tab cannot be closed directly. Browser reload/exit asks before losing
any active or inactive draft where the browser supports that prompt.
Changing the Controller address or service credential resets the Workspace view,
including same-address credential changes and A→B→A switches. Save drafts before
changing that connection. Old views cannot continue an approval/save/run sequence;
an already admitted operation may still have happened. Reopen its original
Controller and inspect persisted evidence before trying another operation.
Editor contents are not stored in layout preferences. Font size, collaboration
visibility and activity visibility are the only new saved preferences; existing
Chat conversation/draft persistence retains its existing behavior.

**Discuss saved file** explicitly selects only its path and SHA-256 reference.
It does not automatically send file contents or call a model. Send uses the existing
Chat Runtime in `read_only` mode; Runtime admission still controls any file read.
A configured model and its existing prerequisites are required. Model file writes
and broader desktop monitoring are not qualified by this panel. Workspace
file context excludes reserved Runtime/Git metadata, including resolved aliases;
inspect authoritative state through the Operations and evidence APIs instead.
This file guard does not replace operating-system isolation or classify arbitrary
user-created secret files. **Workspace
activity** reads actual file-change/execution events, not keystrokes or activity in
other applications. Inspect the persisted run rather than treating a model reply
as effect verification.

**Run in sandbox** uses existing fixed profiles, explicit approval and strict
isolation. **Open environments** opens the existing Environment view. Neither
panel settings nor installation grant execution permission; unavailable isolation
remains BLOCKED. These are source-browser paths, not installed APEIR.exe acceptance.

### Task and Artifact evidence

In the main Desktop source interface, open **Tasks** and select an original
task/Work. Its inspector reads persisted activity and recorded Runtime-service
effect verification. A passing evaluation score stays separate from MATCH;
UNKNOWN and MISMATCH never show a verified effect. An unavailable owner is shown
as an error, rather than an empty successful record. The Operations Console's
**works / evidence** views remain the entry point for distributed Work.

Use global search to find registered Artifact names and open their real metadata
inspector. CAS-backed Artifacts include an actual byte-integrity result;
registration or a digest MATCH does not verify a physical effect. Opening a
record does not perform a new Observation or replay the original Operation.

### Inspect model context

In Chat or the Workbench assistant, submit a request explicitly. Choose
**Inspect model input** below its response, or **Inspect active input** while it
runs. To inspect existing history without invoking a model, open Workspace and
select **Recorded input Run**. Select an iteration to inspect the persisted message/tool manifest and
any file read returned in preceding tool turns. Reopening a conversation uses
the original Run ID; **View trace** remains a separate Trace view.

The panel makes no model call. It distinguishes token estimates from recorded
Provider usage, and successful file reads from failures. Context source chunks
may be partial or omitted. Legacy/missing evidence and unavailable usage are
UNKNOWN; declared tools do not authorize an operation. A metadata-only file
reference is not proof that its contents were sent. See the
[scope and bounds](../../development/DEVELOPER_PLATFORM.md#inspecting-actual-model-input).

Chat file attachment delivery is not available: the picker is disabled and file
drop/paste is refused without clearing the draft. Use a saved Workspace reference
and inspect the admitted read instead. Node targeting, privacy and per-request
budget controls are also disabled in this Chat path; their values must not be
silently ignored. Configure the existing governed model/provider settings before
sending. Model selection and read-only requests retain their existing behavior.

### Environment workbench

The existing Operations Console now opens **environments** alongside Work, Nodes
and Skills. It reads the Environment API for provider status and persistent
records. Configure the existing service authentication for Environment requests
and a separately enrolled human session for Approve Once or Deny; a service token
cannot approve its own request. Review the exact request and Controller before
approval. Source-browser checks are not installed Desktop qualification.
After a confirmed approval, a failed start/run must not keep displaying that
spent decision as pending. The view refreshes persistent state using read-only
queries; a failed or lost response never triggers another execution request.

Environment creation persists a contract; it does not prove a command ran.
Inspect the actual start/run outcome, EventStream and Artifact records. Creation
Artifacts preserve an initial contract snapshot separately from lifecycle state;
verify file bytes against Artifact metadata `sha256`, and the semantic contract
against `environment_contract_sha256`. Old mutable Artifact references are not
rewritten by this fix. Use **Inspect Artifact metadata** in the Environment view
to read actual scoped Registry records; this is not a checksum/effect verification
claim. Missing
strong local isolation fails closed, with no ordinary host fallback. In the
managed Linux qualification, Docker was present but the default OCI engine
control path was blocked by the strict ProcessSandbox. A fixture-only OCI
reference test does not qualify this default API path. Do not change isolation
or inject an unrestricted runner to make the UI report success. Lost responses
need inspection/reconciliation before any new side effect.

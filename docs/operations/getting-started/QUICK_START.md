# Quick Start

Install APEIR, open Studio and run a first task.
先跑通一个工作空间，再配置模型和设备；不必第一天就把机房搬进来。

| Path / 方式 | Requirements | What you get |
| --- | --- | --- |
| [Source Preview](#source-preview) | Python 3.10+ | Downloaded Runtime wheel and built browser Studio; no Node.js or Rust needed |
| [Developer Setup](#developer-setup) | Python 3.10+, Node.js 22.19+ | Editable source and Studio development server |
| [Native Installation](#native-installation) | Windows x64 | Unsigned Portable/NSIS test package; Windows 10 installed lifecycle remains PENDING |

No API key or hardware is needed for model-free browsing and the simulated Demo.
[ROADMAP](../../../ROADMAP.md) records current qualification and remaining work.

## Source Preview

### Download matching packages

Open [Desktop CI](https://github.com/untrod/apeir/actions/workflows/desktop-build.yml)
and choose a successful **main** run with passing Core, Security and Multi-Arch
checks. Download these two Artifacts from the **same commit**:

- `apeir-python-source-preview-<commit>`: wheel, hashes and installation report.
- `apeir-studio-source-frontend-<commit>`: built Studio, hashes and source manifest.

GitHub sign-in is required. Source artifacts expire after seven days. Use a newer
qualified run if one has expired; do not mix revisions. A repository source ZIP
or a frontend-only PR artifact is not this complete pair.

Extract into separate directories. Check that both manifests'
`distribution_revision` values match. From each extracted directory, verify
`SHA256SUMS.txt`:

```bash
python -c "import hashlib,pathlib; r=pathlib.Path('.'); rows=[s.split('  ',1) for s in (r/'SHA256SUMS.txt').read_text().splitlines()]; assert all(hashlib.sha256((r/p).read_bytes()).hexdigest()==h for h,p in rows); print('SHA-256 PASS')"
```

### Install the Runtime

Create a virtual environment, activate it using the platform commands under
[Developer Setup](#developer-setup), then install from the extracted wheel
directory:

```bash
python -m venv .venv
# Activate .venv before the following commands.
python -m pip install ./apeir_distribution-0.1.0rc1-py3-none-any.whl
apeir version
apeir --help
```

Use a separate, empty project directory for Runtime state. In that directory,
start the authenticated API:

```bash
apeir --no-intelligence runtime-api start
```

Keep this terminal open. `--no-intelligence` disables model calls for this
process, including saved Providers; it does not erase their configuration.

### Open Studio

In another activated terminal, from the extracted frontend directory:

```bash
python -m http.server 5186 --bind 127.0.0.1 --directory app
```

Open `http://127.0.0.1:5186`, then follow
[Connect to the Runtime](#model-free-runtime-api-and-source-interface).
Start with **Files**, **Workflow** or the [simulated Demo](#first-verified-execution).
Stop both foreground servers when finished.

Source Preview is a Python service and browser interface, not a Windows EXE.
Model calls and sandboxed tests have separate prerequisites.

## Developer Setup

### Install from the checkout

```bash
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the package and check its public entry points:

```bash
python -m pip install -e .
apeir version
apeir --help
apeir-node --help
apeir-controller --help
```

Start the Runtime from your selected project directory:

```bash
apeir --no-intelligence runtime-api start
```

From a second terminal in the same checkout, start Studio:

```bash
cd desktop
npm ci
npm run dev -- --host 127.0.0.1
```

Open Vite's printed loopback address and connect below. The wheel and editable
installation are alternatives; wheel users do not need `pip install -e .`.

## Development and optional components

### Model-free Runtime API and source interface

**连接 Runtime / Connect:** choose **Workspace → Operations Console**, expand
**Controller connection**, and set **API URL** to `http://127.0.0.1:8770`.
In another activated shell, from the same project directory:

```bash
apeir runtime-api status --json
apeir runtime-api token-path
```

The second command prints the protected session file's path, not its token.
Read that local file privately, enter its token in **Service session token**,
then select **Connect**. Set the URL first: editing it clears the token draft.
The input clears after submission; session-only connection state survives reload.
Never put the token in a screenshot, issue or chat message.

This is a Runtime session token, not a Provider API key or human approval.
Switching Controllers does not reuse the previous identity. The browser cannot
start native sidecars or store Provider secrets.

Current builds open Studio directly. Older previews use
**APEIR Studio / Open workspace**. **Chat**, **Files** and **More / Add panel**
on the left rail reopen panels without deleting a saved layout.

### Configure a model

In **Models**, add the existing supported Provider protocol, endpoint, credential
reference and exact vendor model ID. Save the configuration, select a registered
model, then explicitly **Test** when inference is intended.

A model-disabled Runtime cannot make that call. Stop it before starting normal
model-enabled operation with the required authenticated Kernel. Do not use a
development override or direct SDK fallback.

Browser Studio cannot save raw keys. Native local settings use the existing
system credential store. See [Models and Providers](../../development/DEVELOPER_PLATFORM.md#first-use-configuration-and-model-tests)
for supported protocols, cloud/local coexistence and error states. Saving a
profile is not proof of inference; missing usage is UNKNOWN, not free.

## First inspection

```bash
apeir --no-intelligence status
apeir --no-intelligence capability list
apeir --no-intelligence provider list
```

These inspect local state. An empty list is not a failed installation; it may
mean nothing has been configured.

## First verified execution

From an activated terminal:

```bash
apeir demo --workspace ./demo-match --phase prepare --json
apeir demo --workspace ./demo-match --phase resume --approve-once --json
```

Use an empty dedicated directory. The first command prepares the original Work
and waits for approval. The second explicitly approves once as the local user,
resumes it, reads an independent simulated observation and commits only on MATCH.
Without approval, it does not mutate the simulated device.

[Hello Runtime](../../../examples/hello_runtime/README.md) also covers Deny,
MISMATCH, UNKNOWN, response loss and process restart. This is runtime-service
simulation: no Kernel traversal, physical device or remote-human qualification.
Keep its private state directory out of Git.

## Public SDK examples

From the matching source checkout:

```bash
python -m pip install -e sdk/provider/python
python examples/hello_provider/run_example.py --workspace ./provider-demo
python examples/hello_skill/run_example.py --workspace ./skill-demo
```

Use separate empty directories. [Hello Provider](../../../examples/hello_provider/README.md)
runs a scoped read-only Work and refusal cases.
[Hello Skill](../../../examples/hello_skill/README.md) installs and loads actual
instructions; it grants no device or Shell permission.
For a declarative widget, use [System Monitor](../../../examples/studio_system_monitor/README.md).

## Using the workbench

### Workspace developer panel

Open **Files / Operations → Workspace**. Select files, edit drafts, review the
Diff and request the original approval before applying a change. Changed source
versions are rejected rather than overwritten. See
[Workspace changes](../../development/DEVELOPER_PLATFORM.md#reviewing-workspace-changes)
for multi-file review and [Workbench](../../development/DEVELOPER_PLATFORM.md#professional-workbench)
for draft handling, fixed execution profiles and sandbox requirements.

Drafts are held in memory. Save or export them before reloading or changing
Controller. Closing a panel does not cancel admitted Work. After a lost write
response, inspect the original Proposal, files and evidence before trying again.

### Task and Artifact evidence

Open **Tasks**, select the original Work, then inspect its recorded execution
and evidence. Artifact checksum validation proves byte integrity, not a physical
effect. [Watching a request](../../development/DEVELOPER_PLATFORM.md#watching-a-request)
explains model/tool activity, reconnecting and historical Run inspection.

### Inspect model context

Use **Inspect active input** while a request runs or **Inspect model input** on
its saved response. This reads the original metadata without a model call.
It shows application Gateway input, not proof of the Provider's final payload.
See [context scope](../../development/DEVELOPER_PLATFORM.md#inspecting-actual-model-input)
and [usage and cost](../../development/DEVELOPER_PLATFORM.md#model-usage-and-cost).

### Environment workbench

Open **Operations Console → Environments** to inspect contracts, provider state
and original lifecycle records. Creation is not execution. Missing strict
isolation is BLOCKED; do not fall back to an ordinary host Shell.
Run the scientific reference's prerequisite check from its source checkout:

```bash
python -m scripts.acceptance.scientific_preview_preflight
```

Exit 2/BLOCKED is expected when its qualified sandbox is absent; this command
does not generate a report. See the [scientific examples](../../../examples/README.md#scientific-computation-and-reports).

## Troubleshooting and feedback

| Symptom / 现象 | Check |
| --- | --- |
| Only a Dashboard | Open **Chat**, **Files** or **More / Add panel**; keep your saved layout. |
| Runtime unavailable | Keep its terminal open; check the Controller URL and original session. |
| Chat unavailable | Model-free mode deliberately disables inference. A saved Provider does not enable that process. |
| Approval required | Use the separately authorized human path; a service token cannot approve itself. |
| Test BLOCKED | Inspect permission, toolchain and strict-sandbox requirements. File MATCH is not test PASS. |
| Response lost | Query the original Run/Work; do not automatically resubmit an uncertain effect or billed call. |

Run `apeir doctor` and read [Troubleshooting](TROUBLESHOOTING.md). Report the
version, platform, command and exact error through
[Issues](https://github.com/untrod/apeir/issues), after removing credentials and
private paths. Vulnerabilities follow [SECURITY](../../../SECURITY.md).

## Native Installation

The **unsigned Windows x64 test package** has passed build and native sidecar
smoke on Windows Server 2025. Windows 10 GUI, installation, upgrade, uninstall,
Defender and signing remain unqualified.

1. Sign in to GitHub and download
   [windows-x64-native-development-build](https://github.com/untrod/apeir/actions/runs/40862247626/artifacts/12894812901).
   Retention ends **2026-11-12**. The installer is inside the downloaded artifact ZIP.
2. Extract it. Check its source manifest and `native-validation-report.json`.
   It contains Portable, NSIS, `SHA256SUMS.txt` and dependency/build records.
3. Verify the files in PowerShell:

   ```powershell
   Get-FileHash .\APEIR_0.1.0-rc1_x64-setup.exe -Algorithm SHA256
   Get-FileHash .\APEIR-Portable-0.1.0-rc1-windows-x64.zip -Algorithm SHA256
   ```

   Compare with that same artifact's `SHA256SUMS.txt`.
4. Extract Portable and keep **all** files together beside `APEIR.exe`, or use
   the NSIS current-user installer. WebView2 setup may require network access.
   Do not copy the launcher alone or replace its sidecars.

| File | SHA-256 for this exact build |
| --- | --- |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `78A447DF234E6F56E68EA06E67FE44A75D745CB668DBAD5FDEE9B3602D303D55` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `D07230F3E8903B3CF9D2AD08E112905DE9F62EEEC6132C060DDE1BA5F668A8F8` |

Outer artifact ZIP SHA-256:
`6e0f34a15460ebfb37603d2011119850363c776ee37a954b2a866c89cda4bbaa`.

This package is accepted source `284c1cea37fd96e07cf029c3cc35a70be5c4818c`.
Its Core, Desktop, Multi-Arch and Security checks passed; the full-mode native
producer passed separately. It includes Provider settings, recorded Chat activity
and PR110's Work/Relay/SBOM changes. Later Workflow data-binding changes are not
in this package. Historical Windows timing issues remain open; a passing run does
not establish their complete cause. A documentation update cannot change these
binaries. Use each build's own manifest and hashes even when filenames match.

See the [native build record](../deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build)
for exact inputs and [Release Runbook](../../acceptance/RELEASE_RUNBOOK.md) for
remaining Gates. This package is a development build, not a stable Release.

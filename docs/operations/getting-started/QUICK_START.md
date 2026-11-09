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

## Download metadata

Distribution/Studio version: `0.1.0-rc1` (Python normalizes this to `0.1.0rc1`).
The source and native packages below identify the same reviewed code revision.
Later documentation does not change a package's binary identity. A bundled Quick
Start is a build-time snapshot; its own source manifest and `SHA256SUMS.txt`
identify its actual files.

| Path | Requirements / tested scope | Source and expiry |
| --- | --- | --- |
| Source Preview | Python 3.10+ and a browser. Independently installed and exercised on Linux x64, including original completed Work and project history after restart. Includes governed tests, queued Relay cancellation, Context persistence and WAL-aware backups; native installation is separate. | Source `dfec8c9c2614a3a80ab6ecb6c91fa6568722f5d5`; [Runtime wheel](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13652735998) + [built Studio](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13652233003), run42568225590; expires2026-11-16 |
| Windows Development Build | x64 target, WebView2 prerequisite; Python and Kernel sidecars included. Full build/real component Smoke passed on Windows Server2025. Includes the reviewed RC1 execution, Context and backup fixes; read [known limitations](INSTALL_WINDOWS.md#known-limitations). Windows10 lifecycle/Defender remain PENDING. | Source `dfec8c9c2614a3a80ab6ecb6c91fa6568722f5d5`; [Portable + NSIS bundle](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13653822826), full-mode run42568225590; expires2026-11-23 |
| Developer Setup | Python 3.10+, Git; Node.js22.19+ for Studio development. Rust/platform SDKs are only needed for native packaging. | [Source checkout](#developer-setup); use the Git revision as its identity |
| Future Stable Release | Not available. Installation lifecycle, signing, supply-chain review and publication authorization are incomplete. | No stable download or one-line installer is offered |

GitHub sign-in is required for Actions artifacts. Download matching Runtime and
Studio files from one reviewed run; inspect their manifests and checksums. An
expired artifact requires another qualified build, not a similarly named EXE.

| File inside the indicated artifact | SHA-256 |
| --- | --- |
| `apeir_distribution-0.1.0rc1-py3-none-any.whl` | `9e077c3fb072909683e0e091c5c424ef5ba1bd8063e71c39f8ac28dc68216b4b` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `942ea3bb2fe838e8d163c113a69e74ce2ae70a5fd79977984778efd36e476aeb` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `16413ffa81a186edfd4aec36ac4ec8828e2b31fcd77a6174b74f2aa139c9dd96` |

<details>
<summary>Outer download ZIP hashes</summary>

These apply to the GitHub artifact ZIPs, before extracting. They are not the
hashes of the wheel or installer inside.

| Download | SHA-256 |
| --- | --- |
| Runtime source artifact ZIP | `c963ceb6d9da762d3f83ee6687a9b0a7f2e3a7fceae95df05f875e5bf0b989c8` |
| Studio frontend artifact ZIP | `6e634620f68d953167046f13688d8a62509186e6f8224d5c2d2791ec28454711` |
| Windows native artifact ZIP | `cd6592ed6a9117a9b27910d1d8bf45c27f6eaab6bc26f0ee0ad6c89d9bf50929` |

</details>

## Source Preview

### Download matching packages

Use the reviewed pair linked below. To choose another build, open
[Desktop CI](https://github.com/untrod/apeir/actions/workflows/desktop-build.yml)
and select a successful **main** run with passing Core, Security and Multi-Arch
checks. Download these two Artifacts from the **same commit**:

- `apeir-python-source-preview-<commit>`: wheel, hashes and installation report.
- `apeir-studio-source-frontend-<commit>`: built Studio, hashes and source manifest.

GitHub sign-in is required. Source artifacts expire after seven days. Use a newer
qualified run if one has expired; do not mix revisions. A repository source ZIP
or a frontend-only PR artifact is not this complete pair.

The verified Source Preview is `dfec8c9c2614a3a80ab6ecb6c91fa6568722f5d5`, accepted through
[PR139](https://github.com/untrod/apeir/pull/139) as main `df4fdceabf57a652a381a1ff72267df6f3ff5394`:
[Runtime wheel](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13652735998)
and [built Studio](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13652233003).
The wheel was installed in a new virtual environment outside the checkout.
Its public CLI started the authenticated model-free API; the downloaded Studio
read the actual project and recovered the original completed Work. The simulated
response-loss Demo retained one effect before and after recovery. The documented
typed-result Workflow from the preceding preview was recovered by a new CLI
process with its original Run and outputs. Both foreground services exited
cleanly. This check made no model request or project-file mutation and
does not qualify Windows installation. Downloads expire on **2026-11-16**.
Wheel SHA-256:

`9e077c3fb072909683e0e091c5c424ef5ba1bd8063e71c39f8ac28dc68216b4b`

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

Follow [Workspace changes](../guides/USER_GUIDE.md#reviewing-workspace-changes)
for file reads, drafts, Diff, original human approval and stale-version refusal.
A service token cannot approve itself; closing a panel does not cancel Work.

### Task and Artifact evidence

Open **Tasks** and inspect the original Work. [Watching a request](../guides/USER_GUIDE.md#watching-a-request)
explains activity, reconnecting and history. An Artifact digest is byte integrity,
not independent physical verification.

### Inspect model context

Use the [Context and Usage guide](../guides/CONTEXT_AND_USAGE.md) for original
input metadata, Tokens and cost. Missing usage stays UNKNOWN, not free.

### Environment workbench

See [controlled execution](../guides/USER_GUIDE.md#interactive-project-execution)
and the [scientific prerequisites](../../../examples/README.md#scientific-computation-and-reports).
A created environment is not an executed test. Missing strict isolation remains
BLOCKED; never replace it with an unrestricted host Shell.

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

For Setup, Portable, hash checks and first-launch steps, use
[APEIR on Windows](INSTALL_WINDOWS.md). Both packages are in the same download;
GitHub sign-in is currently required.

Use the **unsigned Windows x64 test package** from the reviewed source-bound build below.
Windows 10 GUI, installation, upgrade, uninstall, Defender and signing remain
unqualified. Read [known limitations](INSTALL_WINDOWS.md#known-limitations). A
successful build or Sidecar Smoke does not complete those Gates.

1. Sign in to GitHub and open the [reviewed Windows build](https://github.com/untrod/apeir/actions/runs/42568225590/artifacts/13653822826).
   Confirm **Build Windows x86_64** succeeded, then select the artifact
   **windows-x64-native-development-build**. Retention ends **2026-11-23**.
   The installer is inside the downloaded artifact ZIP.
2. Extract it. Confirm `source-manifest.json` identifies
   `dfec8c9c2614a3a80ab6ecb6c91fa6568722f5d5`. In `native-validation-report.json`,
   require `status=passed` and `full_validation_executed=true`; installation
   acceptance remains independent. Keep the included build/dependency records.
3. Verify the files in PowerShell:

   ```powershell
   Get-FileHash .\APEIR_0.1.0-rc1_x64-setup.exe -Algorithm SHA256
   Get-FileHash .\APEIR-Portable-0.1.0-rc1-windows-x64.zip -Algorithm SHA256
   ```

   Compare with **that same artifact's** `SHA256SUMS.txt`; its release manifest
   also records file sizes and hashes. An older build may use the same filenames.
4. Extract Portable and keep **all** files together beside `APEIR.exe`, or use
   the NSIS current-user installer. WebView2 setup may require network access.
   Do not copy the launcher alone or replace its sidecars. Back up existing
   workspaces; first test with a separate empty workspace.

The [native build record](../deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build)
explains provenance, component checks and the actual tested scope. The
[Release Runbook](../../acceptance/RELEASE_RUNBOOK.md) owns publication Gates.
This is a development build, not a stable Release. Cloud/local inference and
historical Windows timing issues retain their independent acceptance records.

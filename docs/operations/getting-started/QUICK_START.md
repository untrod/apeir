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

Current tested product source: `5bdbadf2a072c222b016b1ccbe8b89ad5e0c25ff`.
Distribution/Studio version: `0.1.0-rc1` (Python normalizes this to `0.1.0rc1`).
Later documentation commits do not change the source identity of these files.

| Path | Requirements / tested scope | Source and expiry |
| --- | --- | --- |
| Source Preview | Python 3.10+ and a browser. Independently installed and exercised on Linux x64; platform software CI is recorded separately. No native Desktop installation claim. | [Runtime wheel bundle](https://github.com/untrod/apeir/actions/runs/41308994710/artifacts/13084616985) + [built Studio](https://github.com/untrod/apeir/actions/runs/41308994710/artifacts/13084911108), both from run41308994710; expires2026-11-08 |
| Windows Development Build | x64 target, WebView2 prerequisite; Python and Kernel sidecars included. Full build/real component Smoke passed on Windows Server2025. Windows10 GUI/install/upgrade/uninstall/Defender remain PENDING. | [Portable + NSIS bundle](https://github.com/untrod/apeir/actions/runs/41309010299/artifacts/13085683076), full-mode run41309010299; expires2026-11-15 |
| Developer Setup | Python 3.10+, Git; Node.js22.19+ for Studio development. Rust/platform SDKs are only needed for native packaging. | [Source checkout](#developer-setup); use the Git revision as its identity |
| Future Stable Release | Not available. Installation lifecycle, signing, supply-chain review and publication authorization are incomplete. | No stable download or one-line installer is offered |

GitHub sign-in is required for Actions artifacts. Download matching files from
one reviewed run; inspect the included source manifest and checksums. An expired
artifact requires another qualified build, not a similarly named old EXE.

| File inside the artifact | SHA-256 |
| --- | --- |
| `apeir_distribution-0.1.0rc1-py3-none-any.whl` | `f29024714ed6090ce2012bbe03380589ea1c31dadd9b8cc4920da5b1b7142c6b` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `8595f42722ef602874c340c130f45f3ceaad2d028737dd33d2e9c3fe4d5f331b` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `af7abc5c637772d008fde00b46c4b394334d50883bd1fb1a271c74273a0c57ce` |

<details>
<summary>Outer download ZIP hashes</summary>

These hashes apply to the GitHub artifact ZIPs, before extracting them. They are
not the hashes of the wheel or installer inside.

| Download | SHA-256 |
| --- | --- |
| Runtime source artifact ZIP | `3c2dc49117e41b21cc03859c168abd6223ffbd4e6bd9e0cb638713fb647a59be` |
| Studio frontend artifact ZIP | `a9c8e2b566c7768689d863eb9c7ed602c49cbe08ddd233d97773e58af85c59ae` |
| Windows native artifact ZIP | `9337aa979c9958d1635ead02c415944de1be297958d1516644f5ad6ec53bfa55` |

</details>

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

The verified Source Preview is `5bdbadf` (the main integration of
[PR124](https://github.com/untrod/apeir/pull/124)):
[Runtime wheel](https://github.com/untrod/apeir/actions/runs/41308994710/artifacts/13084616985)
and [built Studio](https://github.com/untrod/apeir/actions/runs/41308994710/artifacts/13084911108).
The wheel was installed in a fresh environment and the downloaded Studio was
exercised against it outside the checkout. Core, Desktop, Multi-Arch and Security
passed for that exact source. These downloads retain their original build
identity when later documentation changes land. Downloads expire on
**2026-11-08**. Its wheel SHA-256 is:

`f29024714ed6090ce2012bbe03380589ea1c31dadd9b8cc4920da5b1b7142c6b`

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

Use the **unsigned Windows x64 test package** from the reviewed main build below.
Windows 10 GUI, installation, upgrade, uninstall, Defender and signing remain
unqualified. A successful build or Sidecar Smoke does not complete those Gates.

1. Sign in to GitHub and open the [reviewed Windows build](https://github.com/untrod/apeir/actions/runs/41309010299/artifacts/13085683076).
   Wait for **Build Windows x86_64** to succeed, then select the artifact
   **windows-x64-native-development-build**. Retention ends **2026-11-15**.
   The installer is inside the downloaded artifact ZIP.
2. Extract it. Confirm `source-manifest.json` identifies
   `5bdbadf2a072c222b016b1ccbe8b89ad5e0c25ff`. In `native-validation-report.json`,
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

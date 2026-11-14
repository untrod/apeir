# Quick Start

Install APEIR, open Studio and run a first task.
先跑通一个工作空间，再配置模型和设备；不必第一天就把机房搬进来。

| Path / 方式 | Requirements | What you get |
| --- | --- | --- |
| [Source Preview](#source-preview) | Python 3.10+ | Downloaded Runtime wheel and built browser Studio; no Node.js or Rust needed |
| [Developer Setup](#developer-setup) | Python 3.10+, Node.js 22.19+ | Editable source and Studio development server |
| [Native Installation](#native-installation) | Windows x64 or ARM64 | Unsigned Portable/NSIS test package; Windows 10 installed lifecycle remains PENDING |

No API key or hardware is needed for model-free browsing and the simulated Demo.
[ROADMAP](../../../ROADMAP.md) records current qualification and remaining work.

## Download metadata

Distribution/Studio version: `0.1.0-rc1` (Python normalizes this to `0.1.0rc1`).
Each package below identifies its exact reviewed code revision. Source Runtime
and browser Studio must come from the same run; platform-specific native builds
may identify a different revision. Later documentation does not change binary
identity. A bundled Quick Start is a build-time snapshot; its own source manifest and `SHA256SUMS.txt`
identify its actual files.

| Path | Requirements / tested scope | Source and expiry |
| --- | --- | --- |
| Source Preview | Python 3.10+ and a browser. Independently installed on Linux with Python 3.10.22: public CLI, authenticated model-free API and simulated response-loss recovery. Matching browser Studio passed real Runtime/Controller checks; native installation is separate. | Source `d94159ea45badf665999dffdafe6786a5e35c085`; [Runtime wheel](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14095499424) + [built Studio](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14095763502), run43549737576; expires2026-11-21 |
| Windows Development Build | x64 target, WebView2 prerequisite; Python and Kernel sidecars included. Full build/real component Smoke passed on Windows Server2025. Includes the Settings model roster, saved-key selection and save/restart feedback; read [known limitations](INSTALL_WINDOWS.md#known-limitations). Windows10 lifecycle/Defender remain PENDING. | Source `d94159ea45badf665999dffdafe6786a5e35c085`; [Portable + NSIS bundle](https://github.com/untrod/apeir/actions/runs/43549734683/artifacts/14097790424), full-mode run43549734683; expires2026-11-28 |
| Windows ARM64 Development Build | Native ARM64 Desktop and all three sidecars; WebView2 required. Full validation, real NKI/Runtime smoke, silent NSIS install and installed-sidecar checks passed on Windows11 ARM64. Windows10 Pad5 GUI, upgrade, Defender and driver acceptance remain PENDING. | Source `d94159ea45badf665999dffdafe6786a5e35c085`; [ARM64 Portable + NSIS](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14097648427), full-mode run43549737576; expires2026-11-28 |
| Developer Setup | Python 3.10+, Git; Node.js22.19+ for Studio development. Rust/platform SDKs are only needed for native packaging. | [Source checkout](#developer-setup); use the Git revision as its identity |
| Future Stable Release | Not available. Installation lifecycle, signing, supply-chain review and publication authorization are incomplete. | No stable download or one-line installer is offered |

GitHub sign-in is required for Actions artifacts. Download matching Runtime and
Studio files from one reviewed run; inspect their manifests and checksums. An
expired artifact requires another qualified build, not a similarly named EXE.

| File inside the indicated artifact | SHA-256 |
| --- | --- |
| `apeir_distribution-0.1.0rc1-py3-none-any.whl` | `91f8d957b7d07f8e0071dca48ed542853f04d6ec72dac5960a2bb75f7d2facb2` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `95b65c4556e08812d64d5b0b631a9685d5000e0e26c38ecbc419144d8b030168` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `8374139b89f070ab6e2982c8930055b3ff2fbf44d278756e32a538362e360a4e` |
| `APEIR-Portable-0.1.0-rc1-windows-arm64.zip` | `feae9bc7a299b51c34680ecbf8920f0ebdd70db8fb2adb42ffb0964c9c947e8d` |
| `APEIR_0.1.0-rc1_arm64-setup.exe` | `a75391060652b2f34ba590830a6ffef5ca889222813e410fd12d4796ba29c8d9` |

<details>
<summary>Outer download ZIP hashes</summary>

These apply to the GitHub artifact ZIPs, before extracting. They are not the
hashes of the wheel or installer inside.

| Download | SHA-256 |
| --- | --- |
| Runtime source artifact ZIP | `5e1f55177a8b9ef234f1b7383dff5cc9e8a6bae619c0f108cf8a846956fd4961` |
| Studio frontend artifact ZIP | `6f6d9474957b7362bd58b373f81d7032275618290454425b55d18e90311731c4` |
| Windows x64 native artifact ZIP | `eafb38ac9bde3bd57575d3de8d299829dc46631e52f81b1ea1ed6c390425f544` |
| Windows ARM64 native artifact ZIP | `bd12c756ede57c30cddaa1b5bde8b8e8c1ffbacf5762cffa620b8ee86f425011` |

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

The verified Source Preview is `d94159ea45badf665999dffdafe6786a5e35c085`,
reviewed in [PR154](https://github.com/untrod/apeir/pull/154):
[Runtime wheel](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14095499424)
and [built Studio](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14095763502).
The producer installed the wheel in a clean Python 3.10.22 environment outside
the checkout. Its public CLI started the authenticated model-free API, refused
unauthenticated access and closed its session and listener on exit. The simulated
response-loss Demo retained one effect before and after recovery, with two
observations and five Artifact integrity checks. The matching Studio passed
all22 model-free Runtime/Controller browser cases in development and production,
including saved model configuration and reload. Downloaded archives, checksums
and source manifests were independently checked. These checks made no model
request and do not qualify Windows installation.
Downloads expire on **2026-11-21**. Studio extension examples are installed
separately; they are not bundled into the Runtime wheel or native application.
Later documentation commits do not change the recorded producer's bytes.
Wheel SHA-256:

`91f8d957b7d07f8e0071dca48ed542853f04d6ec72dac5960a2bb75f7d2facb2`

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
The recorded independent install above ran on Linux; it does not qualify an
ARM64 Python source install or tablet drivers. See the separate
[ARM64 package scope](../deployment/WINDOWS_10_ARM64_LOCAL.md) for that target.
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

Use [APEIR on Windows](INSTALL_WINDOWS.md) for Setup, Portable and first-launch
steps. Each architecture's download contains both packages and its build records;
GitHub sign-in is required. Choose **x64** for Intel/AMD PCs or **ARM64** for
Windows on Arm, including a Windows Pad5. Both artifacts expire2026-11-28.

1. Download the matching architecture from [Download metadata](#download-metadata).
2. Extract the outer GitHub ZIP. Check its `source-manifest.json` against that
   row's source revision, then compare the selected Setup/Portable file's SHA-256
   with the table above and the included `SHA256SUMS.txt`. Stop on a mismatch.
3. Require `status=passed` and `full_validation_executed=true` in
   `native-validation-report.json`. These establish build/sidecar qualification;
   Windows10 GUI, upgrade/uninstall, Defender and signing remain separate.
4. Follow the installation guide, keep all Portable files together and start
   with an empty workspace. Back up existing state before any migration test.

See the [x64 build record](../deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build),
[ARM64 tablet checklist](../deployment/WINDOWS_10_ARM64_LOCAL.md#first-tablet-test)
and [Release Runbook](../../acceptance/RELEASE_RUNBOOK.md). These are unsigned
development builds, not a stable Release. Model inference, strict command
execution and historical Windows timing issues retain their separate limits.

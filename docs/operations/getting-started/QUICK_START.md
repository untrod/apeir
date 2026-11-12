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
| Source Preview | Python 3.10+ and a browser. Independently installed on Linux with Python 3.10.22: public CLI, authenticated model-free API and simulated response-loss recovery. Matching browser Studio passed real Runtime/Controller checks; native installation is separate. | Source `16308a6b5bb6f1d3049144f413bc8a9b9541561a`; [Runtime wheel](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13898312736) + [built Studio](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13898392276), run43115765924; expires2026-11-18 |
| Windows Development Build | x64 target, WebView2 prerequisite; Python and Kernel sidecars included. Full build/real component Smoke passed on Windows Server2025. Includes the reviewed RC1 fixes and Studio extension feature discovery; read [known limitations](INSTALL_WINDOWS.md#known-limitations). Windows10 lifecycle/Defender remain PENDING. | Source `70a5c69b1b2bd9f36f5f6725e7a1e7bdf411fd2d`; [Portable + NSIS bundle](https://github.com/untrod/apeir/actions/runs/42977022966/artifacts/13837634414), full-mode run42977022966; expires2026-11-25 |
| Windows ARM64 Development Build | Native ARM64 Desktop and all three sidecars; WebView2 required. Full validation, real NKI/Runtime smoke, silent NSIS install and installed-sidecar checks passed on Windows11 ARM64. Windows10 Pad5 GUI, upgrade, Defender and driver acceptance remain PENDING. | Source `16308a6b5bb6f1d3049144f413bc8a9b9541561a`; [ARM64 Portable + NSIS](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13901748571), full-mode run43115765924; expires2026-11-25 |
| Developer Setup | Python 3.10+, Git; Node.js22.19+ for Studio development. Rust/platform SDKs are only needed for native packaging. | [Source checkout](#developer-setup); use the Git revision as its identity |
| Future Stable Release | Not available. Installation lifecycle, signing, supply-chain review and publication authorization are incomplete. | No stable download or one-line installer is offered |

GitHub sign-in is required for Actions artifacts. Download matching Runtime and
Studio files from one reviewed run; inspect their manifests and checksums. An
expired artifact requires another qualified build, not a similarly named EXE.

| File inside the indicated artifact | SHA-256 |
| --- | --- |
| `apeir_distribution-0.1.0rc1-py3-none-any.whl` | `24807bb4e7680033cbadf0a5ab75539c15f30f3a1b322181514d4b6b75e018ce` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `5896b513211d25dd3518fa7570c1d69bd343bf80babd756f63b5695355f863e3` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `ff3e8a56f14d048aee24367f282617a92e89f2d3397406e008b8bac7008e4b85` |
| `APEIR-Portable-0.1.0-rc1-windows-arm64.zip` | `243f294d4640c71c2b9437ca7936594919f08e0a9ed1b463d9a46691faef5996` |
| `APEIR_0.1.0-rc1_arm64-setup.exe` | `0f2922faa9336c04ee63657f40c43b2c9a7e050c4d2586612ec98887a5a7b164` |

<details>
<summary>Outer download ZIP hashes</summary>

These apply to the GitHub artifact ZIPs, before extracting. They are not the
hashes of the wheel or installer inside.

| Download | SHA-256 |
| --- | --- |
| Runtime source artifact ZIP | `cd6df42ecb2b9ce8664ab70b21bcbe5b24a004c1b661f01ffd37f9a79af5ce57` |
| Studio frontend artifact ZIP | `3a1c261afbef05ef00699cbfd8c23c2a9952065a60d9bdfbc7542dcc8ff213b8` |
| Windows x64 native artifact ZIP | `47e35e52c46d18eab6fe1c22bc6850616911656882d15bd593316234d4f5a33d` |
| Windows ARM64 native artifact ZIP | `2174890ffcd04577f29d1d49285e9c3219ae977de1651ff6b29606941bf4224d` |

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

The verified Source Preview is `16308a6b5bb6f1d3049144f413bc8a9b9541561a`,
reviewed in [PR147](https://github.com/untrod/apeir/pull/147):
[Runtime wheel](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13898312736)
and [built Studio](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13898392276).
The producer installed the wheel in a clean Python 3.10.22 environment outside
the checkout. Its public CLI started the authenticated model-free API, refused
unauthenticated access and closed its session and listener on exit. The simulated
response-loss Demo retained one effect before and after recovery, with two
observations and five Artifact integrity checks. The matching production Studio
passed real model-free Runtime/Controller browser checks. Downloaded archives,
checksums, manifests and changed Runtime module bytes were independently checked.
These checks made no model request and do not qualify Windows installation.
Downloads expire on **2026-11-18**. The later Workflow Monitor 1.0.1 example
uses a compact table; it is installed separately and is not bundled into the
Runtime wheel or native application. Application and build inputs are unchanged
from the recorded producer. Test and documentation commits do not change its bytes.
Wheel SHA-256:

`24807bb4e7680033cbadf0a5ab75539c15f30f3a1b322181514d4b6b75e018ce`

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
Windows on Arm, including a Windows Pad5. Both artifacts expire2026-11-25.

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

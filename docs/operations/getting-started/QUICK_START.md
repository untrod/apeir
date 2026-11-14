# Quick Start / 快速开始

Choose how you want to run APEIR. No model account is needed to open files,
arrange Studio or try the model-free examples.

| Path | You need | Start here |
| --- | --- | --- |
| Windows app | Windows x64 or ARM64, WebView2 | [Install Setup or use Portable](INSTALL_WINDOWS.md) |
| Source Preview | Python 3.10+ and a browser | [Install the wheel](#source-preview); no Node.js or Rust needed |
| Developer Setup | Git, Python 3.10+, Node.js 22.19+ | [Run from source](#developer-setup) |

Windows 用户直接选择安装版或 Portable；开发者可以安装 Python 包，也可以从源码运行。
模型、扩展和设备按需配置，不影响先打开工作台。

## Native Installation

[Download x64](https://github.com/untrod/apeir/actions/runs/43549734683/artifacts/14097790424) ·
[Download ARM64](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14097648427)

Extract the downloaded bundle, then open its Setup installer. For Portable,
extract the included Portable ZIP and open `APEIR-Portable/APEIR.exe`.
[Installation guide](INSTALL_WINDOWS.md) covers verification, first launch and
updates. The current unsigned Developer Preview requires GitHub sign-in to
download; Windows 10 installation testing is still in progress.

## Source Preview

### Download matching packages

Download both artifacts from the same build and extract them into separate
folders, named `runtime` and `frontend` here:

- [Runtime wheel](https://github.com/untrod/apeir/actions/runs/43622764883/artifacts/14125072122)
- [Built Studio](https://github.com/untrod/apeir/actions/runs/43622764883/artifacts/14124703581)

These packages use source revision `3aafb1b26bf4fb5e223f5120691ca6c8444ea38f`.
GitHub sign-in is required. Check the [download metadata](#download-metadata)
for hashes and retention dates.

Before installing, run this from each extracted folder to check its contents:

```bash
python -c "import hashlib,pathlib,sys; r=pathlib.Path('.'); rows=[s.split('  ',1) for s in (r/'SHA256SUMS.txt').read_text().splitlines()]; bad=[p for h,p in rows if hashlib.sha256((r/p).read_bytes()).hexdigest()!=h]; print('SHA-256 mismatch' if bad else 'SHA-256 OK'); sys.exit(bool(bad))"
```

### Install the Runtime

From the parent folder containing `runtime` and `frontend`:

```bash
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux/macOS, or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```bash
python -m pip install ./runtime/apeir_distribution-0.1.0rc1-py3-none-any.whl
apeir version
mkdir my-project
cd my-project
apeir --no-intelligence runtime-api start
```

Leave the terminal open. `--no-intelligence` starts without model calls;
configuration is preserved, but inference is disabled for this process.

### Open Studio

Open a second terminal in the parent folder and activate the same virtual
environment. Serve the downloaded frontend:

```bash
python -m http.server 5186 --bind 127.0.0.1 --directory frontend/app
```

Open `http://127.0.0.1:5186` and [connect to the Runtime](#model-free-runtime-api-and-source-interface).
Stop both foreground servers with Ctrl+C when finished.

## Developer Setup

```bash
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
```

Activate the environment as above, then install and start the Runtime:

```bash
python -m pip install -e .
apeir version
apeir --no-intelligence runtime-api start
```

In a second terminal, start Studio from the checkout:

```bash
cd desktop
npm ci
npm run dev -- --host 127.0.0.1
```

Open the address Vite prints. Rust and platform SDKs are needed only when
building the native application. For tests and contribution rules, see
[CONTRIBUTING](../../../CONTRIBUTING.md).

<a name="development-and-optional-components"></a>

## Model-free Runtime API and source interface

In browser Studio, open **Workspace → Operations Console → Controller
connection**. Enter `http://127.0.0.1:8770` as the API URL.

From another activated terminal in the same project directory:

```bash
apeir runtime-api status --json
apeir runtime-api token-path
```

The second command prints the protected session file's path. Read the local
file privately, paste its token into **Service session token**, and connect.
Set the URL first; changing it clears the token field. This session token is
for the Runtime connection, not a model API key.

The native app manages its local connection automatically.

### Configure a model

Open **Settings → Models & credentials**. Save a key under **API keys**, then
add a connection under **Models** and select that saved key. Local model
services use their supported endpoint. The browser interface uses credentials
configured on the Controller host.

A model-free process must be restarted in normal mode with its authenticated
Kernel before inference can run. Follow [Models and Providers](../guides/PROVIDER_GUIDE.md)
for supported protocols, cloud/local configuration and connection tests.

## First inspection

```bash
apeir --no-intelligence status
apeir --no-intelligence capability list
apeir --no-intelligence provider list
```

An empty catalog means no entries have been configured yet.

## First verified execution

Try the included simulated-device example in a separate directory:

```bash
apeir demo --workspace ./demo-match --phase prepare --json
apeir demo --workspace ./demo-match --phase resume --approve-once --json
```

The first command waits for approval. The second approves the pending change,
resumes it and checks the result. This example uses a simulated device.
[Hello Runtime](../../../examples/hello_runtime/README.md) also covers refusal
and recovery after a lost response.

## Public SDK examples

From a source checkout:

```bash
python -m pip install -e sdk/provider/python
python examples/hello_provider/run_example.py --workspace ./provider-demo
python examples/hello_skill/run_example.py --workspace ./skill-demo
```

[Hello Provider](../../../examples/hello_provider/README.md) implements a
read-only adapter; [Hello Skill](../../../examples/hello_skill/README.md) installs
and loads instructions. For a Studio widget, start with
[System Monitor](../../../examples/studio_system_monitor/README.md).

<a name="using-the-workbench"></a>
<a name="workspace-developer-panel"></a>
<a name="task-and-artifact-evidence"></a>
<a name="inspect-model-context"></a>
<a name="environment-workbench"></a>

## Using the workbench

[Project files and diffs](../guides/USER_GUIDE.md#reviewing-workspace-changes) ·
[Workflow](../guides/WORKFLOW_GUIDE.md) ·
[Task activity](../guides/USER_GUIDE.md#watching-a-request) ·
[Context and usage](../guides/CONTEXT_AND_USAGE.md) ·
[Controlled tests](../guides/USER_GUIDE.md#professional-workbench)

## Troubleshooting and feedback

If startup fails, run `apeir doctor` and check [Troubleshooting](TROUBLESHOOTING.md).
For a lost response, inspect the original task before submitting it again.
Report the version, command and error in an [Issue](https://github.com/untrod/apeir/issues);
remove credentials and personal paths first. Security reports follow
[SECURITY](../../../SECURITY.md).

## Download metadata

Version **0.1.0-rc1** (`0.1.0rc1` in Python). Windows packages include Setup,
Portable, `SHA256SUMS.txt` and source/build manifests. Source Preview includes
a Runtime wheel, built frontend and their checksums.

| Package | Source revision | Available until (UTC) |
| --- | --- | --- |
| [Runtime wheel](https://github.com/untrod/apeir/actions/runs/43622764883/artifacts/14125072122) and [browser Studio](https://github.com/untrod/apeir/actions/runs/43622764883/artifacts/14124703581) | `3aafb1b26bf4fb5e223f5120691ca6c8444ea38f` | 2026-11-21 |
| [Windows x64](https://github.com/untrod/apeir/actions/runs/43549734683/artifacts/14097790424) | `d94159ea45badf665999dffdafe6786a5e35c085` | 2026-11-28 |
| [Windows ARM64](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14097648427) | `d94159ea45badf665999dffdafe6786a5e35c085` | 2026-11-28 |

The browser Studio includes newer interface changes than these Windows packages.
A documentation or screenshot update does not rebuild an installer. Actions
artifacts expire; there is no public Release download yet.

<details>
<summary>File checksums / SHA-256</summary>

These hashes apply to files **inside** the downloaded artifacts:

| File | SHA-256 |
| --- | --- |
| `apeir_distribution-0.1.0rc1-py3-none-any.whl` | `e1e763ed71b8040b6e0036767a79a80d12ac279c58b06a039df6b78fd252b328` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `8374139b89f070ab6e2982c8930055b3ff2fbf44d278756e32a538362e360a4e` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `95b65c4556e08812d64d5b0b631a9685d5000e0e26c38ecbc419144d8b030168` |
| `APEIR_0.1.0-rc1_arm64-setup.exe` | `a75391060652b2f34ba590830a6ffef5ca889222813e410fd12d4796ba29c8d9` |
| `APEIR-Portable-0.1.0-rc1-windows-arm64.zip` | `feae9bc7a299b51c34680ecbf8920f0ebdd70db8fb2adb42ffb0964c9c947e8d` |

Outer artifact ZIP hashes, before extraction:

| Artifact | SHA-256 |
| --- | --- |
| Runtime | `fc117e5cd8ffe133cba90956e323d00fd23cc27f1e403a5245b12358cf05fe00` |
| Browser Studio | `3f2761a528b4a27f027ead053f5cca26696d17ca35a6523bbf80cb8cd48859fc` |
| Windows x64 | `eafb38ac9bde3bd57575d3de8d299829dc46631e52f81b1ea1ed6c390425f544` |
| Windows ARM64 | `bd12c756ede57c30cddaa1b5bde8b8e8c1ffbacf5762cffa620b8ee86f425011` |

Stop on a checksum mismatch. Build verification and platform test records are
kept in [Engineering Review](../../acceptance/ENGINEERING_REVIEW.md);
[platform support](../platform/PLATFORM_SUPPORT_POLICY.md) describes the tested
operating systems. Windows 10 installation, signing and public release review
are separate from these downloadable development builds.

</details>

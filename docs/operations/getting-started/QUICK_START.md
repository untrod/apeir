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

[Download x64](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14976528487) ·
[Download ARM64](https://github.com/untrod/apeir/actions/runs/45505847685/artifacts/14977666664)

Extract the downloaded bundle, then open its Setup installer. For Portable,
extract the included Portable ZIP and open `APEIR-Portable/APEIR.exe`.
[Installation guide](INSTALL_WINDOWS.md) covers verification, first launch and
updates. The current unsigned Developer Preview requires GitHub sign-in to
download. Windows 10 installation testing is pending on physical hardware.

## Source Preview

### Download matching packages

Download both artifacts from the same build and extract them into separate
folders, named `runtime` and `frontend` here:

- [Runtime wheel](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14973588654)
- [Built Studio](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14973668197)

These packages use source revision `d1832b24504011484476d1ec9d9e6fe851495d24`.
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
| [Runtime wheel](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14973588654) and [browser Studio](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14973668197) | `d1832b24504011484476d1ec9d9e6fe851495d24` | 2026-12-01 23:03 |
| [Windows x64](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14976528487) | `d1832b24504011484476d1ec9d9e6fe851495d24` | 2026-12-08 23:59 |
| [Windows ARM64](https://github.com/untrod/apeir/actions/runs/45505847685/artifacts/14977666664) | `d1832b24504011484476d1ec9d9e6fe851495d24` | 2026-12-09 00:08 |

The Source Preview and both Windows packages use the same software revision.
The table tracks the source embedded in the packages. These are expiring
Actions artifacts. Public GitHub Releases are pending.

<details>
<summary>File checksums / SHA-256</summary>

These hashes apply to files **inside** the downloaded artifacts:

| File | SHA-256 |
| --- | --- |
| `apeir_distribution-0.1.0rc1-py3-none-any.whl` | `73b73f36681943e7ac2b8bf476d16757e36f6ebe8a857e793c6aa0791c58b42e` |
| `APEIR_0.1.0-rc1_x64-setup.exe` | `7cb7697c13df348d15f253cb4aa68e96082ac40817229363321d63a6ee54fcfa` |
| `APEIR-Portable-0.1.0-rc1-windows-x64.zip` | `cb3f43d2f4181bb76820c3d47df874ded262945ca73cc176c627d7869f2a80b0` |
| `APEIR_0.1.0-rc1_arm64-setup.exe` | `b7194ae5c0d710942cdd668bf86648a01e1d04ca97d8d617a1f8762434bd4f54` |
| `APEIR-Portable-0.1.0-rc1-windows-arm64.zip` | `ed1aab1a3093ebc7a6038bfaa07b2a7f0f4615b3566f038103b122ff1e632dc2` |

Outer artifact ZIP hashes, before extraction:

| Artifact | SHA-256 |
| --- | --- |
| Runtime | `32667f17e6d54318edaf83f6e7331a698fcb3aa4fc85f3f35e13026dce0df537` |
| Browser Studio | `df7e0912d98de405f5917d072495ffd1bc1b96e627c576f9d4bc7897729866cb` |
| Windows x64 | `9f6f6fe353635ffff3e53dac0b61a49c37b68b01daa58b2db49a9fca3af68753` |
| Windows ARM64 | `6426b527c2891c014a2f96b3fcbfd98fd8ac42db8e5765538b1210134c39f2f4` |

Stop on a checksum mismatch. Build verification and platform test records are
kept in [Engineering Review](../../acceptance/ENGINEERING_REVIEW.md);
[platform support](../platform/PLATFORM_SUPPORT_POLICY.md) describes the tested
operating systems. Windows 10 installation, signing and public release review
are separate from these downloadable development builds.

</details>

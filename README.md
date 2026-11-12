# APEIR

<!-- Compatibility anchors for existing documentation links. -->
<a name="apeir-studio"></a>
<a name="contributing"></a>
<a name="current-status"></a>
<a name="developer-platform"></a>
<a name="documentation"></a>
<a name="overview"></a>
<a name="quick-start"></a>
<a name="sdk--extensions"></a>
<a name="start-here"></a>
<a name="what-you-can-do"></a>


An open, local-first workspace for project files, workflows and connected
resources—with approvals and execution records you can inspect.

[**⬇ Windows x64**](https://github.com/untrod/apeir/actions/runs/42977022966/artifacts/13837634414) ·
[**Windows ARM64**](https://github.com/untrod/apeir/actions/runs/43115765924/artifacts/13901748571) ·
[**Source Preview**](docs/operations/getting-started/QUICK_START.md#source-preview) ·
[**Quick Start**](docs/operations/getting-started/QUICK_START.md) ·
[**Documentation**](docs/README.md) · [简体中文](README.zh-CN.md)

**Windows:** choose x64 for Intel/AMD PCs, ARM64 for Windows on Arm (including Pad5).
[Install Setup](docs/operations/getting-started/INSTALL_WINDOWS.md#setup) · [Use Portable](docs/operations/getting-started/INSTALL_WINDOWS.md#portable) · [Verify SHA-256](docs/operations/getting-started/QUICK_START.md#download-metadata).
Unsigned development bundle; GitHub sign-in required. Windows 10 installation
acceptance is pending. No stable Release yet—keep your production hat on the hook.

![APEIR Studio showing project files, an editor and Chat](docs/media/studio-workspace-source.png)

*Actual Studio source build in Linux Chromium, with models disabled. The
Windows download has its own build identity; this image is not native-install
or live-model acceptance.*

APEIR Studio puts project, conversation, Workflow, task and evidence panels in
one configurable workspace. APEIR Runtime handles admitted operations and their
history. Models and extensions supply capabilities; they do not approve their
own actions.

## What can I do?

| Task | Start here |
| --- | --- |
| Read a project, review a multi-file Diff and apply an independently approved change | [Studio and project changes](docs/operations/guides/USER_GUIDE.md#reviewing-workspace-changes) |
| Create a supported Workflow, inspect its original Run and recover its history | [Workflow guide](docs/operations/guides/WORKFLOW_GUIDE.md) |
| Add a read-only Studio Widget through the public declarative interface | [System Monitor example](examples/studio_system_monitor/README.md) |

You can also [configure compatible cloud and local models](docs/operations/guides/PROVIDER_GUIDE.md),
inspect Nodes and Devices, and read recorded tool activity. Model calls require
an available supported endpoint and authenticated Kernel. Test commands require
their permission and qualified sandbox. Missing prerequisites stay visible.

## Download and start

Use the [installation guide](docs/operations/getting-started/QUICK_START.md) to
choose your path:

- **Source Preview:** matching Runtime wheel and built browser Studio; Python
  3.10+ required. No Node.js or Rust is needed for the downloaded frontend.
- **Windows Development Build:** unsigned x64 and ARM64 Portable/NSIS packages inside
  the linked GitHub Actions artifact. GitHub sign-in is required.
- **Developer Setup:** clone the source for editable Runtime and Studio development.

[Download metadata](docs/operations/getting-started/QUICK_START.md#download-metadata)
records versions, SHA-256, expiry and tested scope. These are temporary preview
artifacts; no stable Release or one-line installer is available.

## Develop and extend

[Developer Platform](docs/development/DEVELOPER_PLATFORM.md) ·
[Public Provider SDK](docs/development/PROVIDER_DEVELOPMENT.md) ·
[UI Extension SDK](docs/development/STUDIO_UI_EXTENSIONS.md) ·
[Examples](examples/README.md) · [API / CLI reference](docs/development/README.md)

The SDK is beta. Studio UI extensions currently use reviewed data-only manifests;
arbitrary third-party JavaScript is not enabled. The separately maintained
[Kernel](https://github.com/untrod/apeir-kernel) is pinned by the
[component lock](runtime-components.lock.json).

## Contribute

Start with [CONTRIBUTING](CONTRIBUTING.md). Report reproducible problems through
[Issues](https://github.com/untrod/apeir/issues); use [SECURITY](SECURITY.md) for
private vulnerability reports. Architecture and acceptance records are indexed
under [Documentation](docs/README.md). Existing `nous` commands and identifiers
remain compatibility names.

## Developer Preview status

Version **0.1.0-rc1** supports source installation and scoped software workflows.
Unsigned Windows builds pass build/sidecar checks; Windows 10 installed lifecycle
remains pending. Live model accounts, strict command isolation and physical
operations have separate qualification requirements. [ROADMAP](ROADMAP.md) is
the current status record. A file MATCH does not mean tests ran or a device effect
was independently verified.

## License

[Apache-2.0](LICENSE) · [NOTICE](NOTICE) · [Third-party notices](THIRD_PARTY_NOTICES.md)

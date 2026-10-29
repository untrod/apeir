# APEIR Studio

A developer workspace for project files, governed workflows and execution
evidence, powered by APEIR Runtime.

[**Source Preview**](docs/operations/getting-started/QUICK_START.md#source-preview) ·
[**Windows test build**](docs/operations/getting-started/QUICK_START.md#native-installation) ·
[**Quick Start**](docs/operations/getting-started/QUICK_START.md) ·
[**SDK & Extensions**](docs/development/DEVELOPER_PLATFORM.md#declarative-ui-extension-sdk) ·
[**Documentation**](docs/README.md) · [简体中文](README.zh-CN.md)

![APEIR Studio with Chat, project files and a split editor](docs/media/studio-workspace-source.png)

*Actual source-browser interface connected to a local, model-disabled Runtime.
This is a Source Developer Preview, not a Windows installation screenshot.*

## Start here

- **Try the workspace:** download matching Runtime and Studio bundles, then follow
  [Quick Start](docs/operations/getting-started/QUICK_START.md). Python 3.10+ is
  required; the built browser interface needs no Node.js or Rust.
- **Develop APEIR:** use [Developer Setup](docs/operations/getting-started/QUICK_START.md#developer-setup)
  for the editable checkout, UI development server and tests.
- **Extend Studio:** start with the [System Monitor example](examples/studio_system_monitor/README.md)
  or the [Provider example](examples/hello_provider/README.md).

## Overview

APEIR Runtime is an open, local-first runtime for heterogeneous intelligence
and real-world resources.

APEIR Studio is the desktop workspace over APEIR Runtime. Arrange project,
conversation, task, resource and evidence panels while the existing Runtime owns
execution, Governance owns authorization, and durable records support recovery.
Models, Agents and UI extensions cannot authorize themselves.

## What you can do

- Browse projects, review file diffs and submit version-bound changes for approval.
- Configure saved Provider references in Models and run an explicit inference test only when a registered model is available.
- Follow recorded model/tool activity, inspect original requests and reconnect without resubmitting the task.
- Arrange docked panels and read-only Dashboards; save, import and reuse layouts.
- Inspect real Runtime/Kernel status, registered Nodes, Devices, Work and evidence.
- Create Workflow graphs, validate/register canonical definitions and run the bound pure steps through Governance; inspect original Run history in Studio.
- Install reviewed Skill instructions and data-only Studio UI extensions; use the public Provider SDK.
- Run the offline [Verified Execution Demo](examples/hello_runtime/README.md),
  including rejection, UNKNOWN, response-loss reconciliation and restart.

Cloud and local Providers can coexist; compatibility depends on their actual
protocol and model capabilities. Current NKI responses are buffered, so recorded
execution progress is available but token-by-token model output is not.

Model calls require their configured Provider and authenticated Kernel. Commands
require their existing permissions and qualified sandbox. Instruction installation
is not tool authorization; execution success is not independent effect verification.

## Quick Start

Follow the [single installation and first-run guide](docs/operations/getting-started/QUICK_START.md).
It separates downloadable **Source Preview**, **Developer Setup** and
**Native Installation**. Source inspection and the simulated Demo need no API key
or hardware. Downloadable source packages are not Windows installers.

**Windows download:** [Portable ZIP + NSIS installer](https://github.com/untrod/apeir/actions/runs/40835150844/artifacts/12883321870)
are available together in **windows-x64-native-development-build**. Sign in to
GitHub, download the artifact ZIP and verify the included checksums before use.
The unsigned candidate build expires on **2026-11-12**. Its exact source and
qualification limits are in the [build record](docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build);
the package is source `05e061e4`, an older accepted main with a separate Windows
Context timeout still under investigation. Windows 10 installation,
upgrade/uninstall and signing remain unqualified. Follow the
[download and verification steps](docs/operations/getting-started/QUICK_START.md#native-installation).
This is a development build, not a stable Release.

## Developer Platform

The [Studio guide](docs/development/DEVELOPER_PLATFORM.md#apeir-studio) covers
panels, keyboard navigation, layout editing, model configuration and current limits.
Use [Developer Setup](docs/operations/getting-started/QUICK_START.md#developer-setup)
for source changes and browser debugging. Studio is part of this Distribution;
the independently maintained [Kernel](https://github.com/untrod/apeir-kernel)
is pinned by [component lock](runtime-components.lock.json).

## SDK & Extensions

Start with the [public Developer Platform](docs/development/DEVELOPER_PLATFORM.md),
[Provider example](examples/hello_provider/README.md) and
[Skill example](examples/hello_skill/README.md).
The [declarative UI SDK](docs/development/DEVELOPER_PLATFORM.md#declarative-ui-extension-sdk)
adds reviewed panels and widgets without loading arbitrary JavaScript in the
trusted window. Executable third-party Studio UI remains disabled until its
isolation is qualified. Installing a package never grants execution permission.

## Current Status

Distribution `0.1.0-rc1` is a **Source Developer Preview**.
Source installation and scoped software scenarios are qualified; the complete
product remains PARTIAL. Real model accounts, strict execution isolation,
Windows native installation, real IdP and physical Jetson/ESP32 writes have
separate prerequisites. [ROADMAP](ROADMAP.md) is the single status source.

UNKNOWN fails closed. Receipt is not Observation. An uncertain effect is
reconciled instead of blindly executed again.

## Documentation

[Architecture contracts](docs/architecture/README.md) ·
[Operations](docs/operations/README.md) ·
[Compute Mesh](docs/operations/compute-mesh/OPERATIONS.md) ·
[Engineering review](docs/acceptance/ENGINEERING_REVIEW.md) ·
[Release Runbook](docs/acceptance/RELEASE_RUNBOOK.md)

## Contributing

Read [CONTRIBUTING](CONTRIBUTING.md) and [SECURITY](SECURITY.md).
Use [Issues](https://github.com/untrod/apeir/issues) for sanitized reproductions;
report vulnerabilities privately. `nous_runtime`, `nous`, `NOUS_*` and existing
wire identifiers remain compatibility names.

## License

Apache-2.0: [LICENSE](LICENSE), [NOTICE](NOTICE),
[third-party notices](THIRD_PARTY_NOTICES.md).

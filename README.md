# APEIR

An open execution, governance and verification runtime for heterogeneous
intelligence and real-world resources. Local-first, with explicit remote execution boundaries.

[**Source Preview**](docs/operations/getting-started/QUICK_START.md#source-preview) ·
[**Quick Start**](docs/operations/getting-started/QUICK_START.md) ·
[**Documentation**](docs/operations/README.md) · [简体中文](README.zh-CN.md)

![APEIR Studio connected to a model-free Runtime](docs/media/studio-source-overview.png)

*Actual Studio source-browser capture with an owned local Runtime. Missing Kernel,
Node and model data remain unconfigured or unknown. This is not an installed EXE.*

## Overview

APEIR Studio is the desktop workspace over APEIR Runtime. Arrange project,
conversation, task, resource and evidence panels while the existing Runtime owns
execution, Governance owns authorization, and durable records support recovery.
Models, Agents and UI extensions cannot authorize themselves.

## What you can do

- Browse projects, review file diffs and submit version-bound changes for approval.
- Arrange docked panels and read-only Dashboards; save, import and reuse layouts.
- Inspect real Runtime/Kernel status, registered Nodes, Devices, Work and evidence.
- Create Workflow graphs, validate/register canonical definitions and run the bound pure steps through Governance; inspect original Run history in Studio.
- Install reviewed Skill instructions and data-only Studio UI extensions; use the public Provider SDK.
- Run the offline [Verified Execution Demo](examples/hello_runtime/README.md),
  including rejection, UNKNOWN, response-loss reconciliation and restart.

Model calls require their configured Provider and authenticated Kernel. Commands
require their existing permissions and qualified sandbox. Instruction installation
is not tool authorization; execution success is not independent effect verification.

## Quick Start

Follow the [single installation and first-run guide](docs/operations/getting-started/QUICK_START.md).
It separates downloadable **Source Preview**, **Developer Setup** and
**Native Installation**. Source inspection and the simulated Demo need no API key
or hardware. Downloadable source packages are not Windows installers.

**Windows EXE / NSIS: BLOCKED.** Exact locked Kernel binaries are unavailable;
reviewed replacement candidates await maintainer approval and Windows10 lifecycle
qualification. See the [native delivery evidence](docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md#r4-trusted-candidate-evidence--2026-10-24).
No qualified installer or formal Release is currently advertised.

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
Executable third-party Studio UI is not enabled. Visual Workflow editing,
declarative UI contributions and their qualification are tracked in ROADMAP;
an installed package never grants execution permission.

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

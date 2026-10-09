# Installation notes

Start with the [source Quick Start](getting-started/QUICK_START.md). It owns
the recommended clone, virtual environment, install and first-run commands.
This page supplements that flow; it does not describe a published binary release.

## Requirements and optional dependencies

- Python 3.10–3.12, Git and a writable checkout/temporary directory.
- Base install: `python -m pip install -e .` from the checkout.
- Development: `python -m pip install -e ".[dev,a2a,mcp,scientific]"`.
- Serial host contracts: `python -m pip install -e ".[reality]"`; this does not
  qualify real firmware writes or physical recovery.
- Terminal colour: `python -m pip install -e ".[ui]"`.
- Heavy model packages: `ai-full` or `local-llm`, only for supported platforms
  with sufficient resources. They are unnecessary for the source preview.

`apeir-distribution` is the current package; legacy Python/wire/CLI identifiers
are preserved. Read the [platform policy](platform/PLATFORM_SUPPORT_POLICY.md)
and [supported environment](../development/DEVELOPER_PLATFORM.md#supported-development-environment)
before running process lifecycle tests.

## Desktop and deployment

Node.js 22 supports the web frontend. Rust, platform SDKs and exact locked
Kernel artifacts are additional native packaging requirements; see
[Desktop architecture](../architecture/DESKTOP_ARCHITECTURE.md).
Persistent Controller/Node services use the
[Compute Mesh runbook](compute-mesh/OPERATIONS.md).

The root Dockerfile belongs to historical `remote_terminal`; it is not a
qualified Developer Preview image. There is no verified Homebrew formula or
`install.nous.ai` installer here. Never put credentials in source, manifests
or Git. Binary publication requires the
[Release Runbook](../acceptance/RELEASE_RUNBOOK.md).

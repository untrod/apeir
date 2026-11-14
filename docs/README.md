# Documentation / 文档

<!-- Compatibility anchors for existing documentation links. -->
<a name="apeir-documentation--文档"></a>


Install APEIR, work in Studio, or build an extension. Choose a guide below.
先找到要做的事；接口、架构和工程记录分别收在后面的参考入口。

## Getting Started

- [Windows installation](operations/getting-started/INSTALL_WINDOWS.md): Setup,
  Portable and first launch.
- [Quick Start](operations/getting-started/QUICK_START.md): Python packages,
  source setup and a first model-free task.
- [Download metadata](operations/getting-started/QUICK_START.md#download-metadata):
  versions, checksums and retention dates.
- [Troubleshooting](operations/getting-started/TROUBLESHOOTING.md) and [FAQ](operations/FAQ.md).

## Guides

| Task / 要做什么 | Guide |
| --- | --- |
| Open a project, arrange panels and review changes / 使用工作台 | [Studio](operations/guides/USER_GUIDE.md) |
| Configure an API or local model / 连接模型 | [Models and Providers](operations/guides/PROVIDER_GUIDE.md) |
| Build and run supported steps / 编排工作流 | [Workflow](operations/guides/WORKFLOW_GUIDE.md) |
| Inspect selected files, Tokens and cost / 查看上下文与用量 | [Context and Usage](operations/guides/CONTEXT_AND_USAGE.md) |
| Develop a read-only Widget / 开发界面扩展 | [UI Extension SDK](development/STUDIO_UI_EXTENSIONS.md) |
| Connect and operate Nodes / 节点运维 | [Compute Mesh](operations/compute-mesh/OPERATIONS.md) |

[Examples](../examples/README.md) lists runnable starting points and their
prerequisites. [Operations](operations/README.md) indexes deployment and recovery.

## Reference

[API](development/API_REFERENCE.md) · [CLI](development/CLI_REFERENCE.md) ·
[Provider SDK](development/PROVIDER_DEVELOPMENT.md) ·
[MCP integration](development/MCP_INTEGRATION.md) ·
[Extension schemas](../spec/extensions/v1/README.md) ·
[Compatibility](development/COMPATIBILITY_MATRIX.md) ·
[Code entry points](development/RUNTIME_MODULE_MAP.md#current-code-entry-points)

The [Developer Platform](development/DEVELOPER_PLATFORM.md) connects these public
interfaces. [Development](development/README.md) covers contributor setup and
integration policy. SDK interfaces are beta.

## Architecture

[Start with the canonical contracts](architecture/README.md): authority,
execution, state ownership, security and Provider boundaries. Read them before
changing execution or permission behavior. [RFCs](rfc/README.md) record design proposals.

## Engineering

[Acceptance index](acceptance/README.md) ·
[Engineering Review](acceptance/ENGINEERING_REVIEW.md) ·
[Known limitations](acceptance/KNOWN_LIMITATIONS.md) ·
[Release Runbook](acceptance/RELEASE_RUNBOOK.md) ·
[ROADMAP](../ROADMAP.md)

ROADMAP tracks current status. Acceptance records retain build provenance,
test environments, results and known failures.

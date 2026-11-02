# Documentation / 文档

<!-- Compatibility anchors for existing documentation links. -->
<a name="apeir-documentation--文档"></a>


Choose a task first. Architecture and dated test records remain available when
you need their detail; opening a project does not require reading every contract.

## Getting Started

- [Quick Start](operations/getting-started/QUICK_START.md): Source Preview,
  Windows development builds, source setup and the first model-free task.
- [Download metadata](operations/getting-started/QUICK_START.md#download-metadata):
  exact versions, hashes, expiry and qualification.
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
[Extension schemas](../spec/extensions/v1/README.md) ·
[Compatibility](development/COMPATIBILITY_MATRIX.md) ·
[Code entry points](development/RUNTIME_MODULE_MAP.md#current-code-entry-points)

The [Developer Platform](development/DEVELOPER_PLATFORM.md) connects these public
interfaces. [Development](development/README.md) covers contributor setup and
integration policy. SDK interfaces are beta; legacy names do not imply a second
Runtime or a stable package release.

## Architecture

[Start with the canonical contracts](architecture/README.md): authority,
execution, state ownership, security and Provider boundaries. Read them before
changing execution or permission behavior. [RFCs](rfc/README.md) record proposals;
a proposal is not a shipped capability.

## Engineering

[Acceptance index](acceptance/README.md) ·
[Engineering Review](acceptance/ENGINEERING_REVIEW.md) ·
[Known limitations](acceptance/KNOWN_LIMITATIONS.md) ·
[Release Runbook](acceptance/RELEASE_RUNBOOK.md) ·
[ROADMAP](../ROADMAP.md)

ROADMAP owns current status. Acceptance records describe their exact revision,
environment and tested scope; historical evidence is retained rather than
relabelled as a current PASS. Historical tags and Git history remain unchanged.

使用指南回答“怎样完成这件事”，参考资料解释接口，工程记录说明“实际测过什么”。
发现过时说明时，请附页面链接、软件版本与可复现步骤；不要公开凭据或私有 Runtime 状态。

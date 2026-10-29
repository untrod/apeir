# APEIR documentation / 文档

Start with the task at hand. You do not need to read the architecture to open
a project.

| Task / 要做什么 | Guide |
| --- | --- |
| Install and launch / 安装启动 | [Quick Start](operations/getting-started/QUICK_START.md) |
| Use Chat, panels and dashboards / 使用工作台 | [Studio](development/DEVELOPER_PLATFORM.md#apeir-studio) |
| Connect a cloud or local model / 连接模型 | [Models and Providers](operations/guides/PROVIDER_GUIDE.md) |
| Review and apply file changes / 审查文件修改 | [Workspace changes](development/DEVELOPER_PLATFORM.md#reviewing-workspace-changes) |
| Create and run a supported workflow / 编排工作流 | [Workflow Builder](development/DEVELOPER_PLATFORM.md#visual-workflow-builder) |
| Develop an extension / 开发扩展 | [System Monitor example](../examples/studio_system_monitor/README.md) |
| Recover or diagnose / 恢复与排障 | [Troubleshooting](operations/getting-started/TROUBLESHOOTING.md) |

## Reference

| Section | Contents |
| --- | --- |
| [Architecture](architecture/README.md) | Authority, execution, state ownership, security and Provider contracts |
| [Operations](operations/README.md) | Configuration, Nodes, Devices, deployment and recovery |
| [Development](development/README.md) | SDK, API, examples, compatibility and contributor interfaces |
| [Acceptance](acceptance/README.md) | Dated tests, limitations and release evidence |
| [RFCs](rfc/README.md) | Proposed contracts and design decisions |

[ROADMAP](../ROADMAP.md) is the single current status source. Dated acceptance
records describe their own revision and environment; they are not blanket
claims about later builds. Historical tags and Git history remain intact.

涉及执行或权限变更时，先读[架构边界](architecture/DISTRIBUTION.md)。
使用说明回答“怎么用”，验收记录回答“测过什么”；二者各管一件事。

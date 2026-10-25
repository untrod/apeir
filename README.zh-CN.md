# APEIR

面向异构智能与现实资源的开放执行、治理和验证运行时。本地优先，远程执行边界明确。

[**源码预览下载**](docs/operations/getting-started/QUICK_START.md#source-preview) ·
[**快速开始**](docs/operations/getting-started/QUICK_START.md) ·
[**文档**](docs/operations/README.md) · [English](README.md)

![连接无模型 Runtime 的 APEIR Studio 源码界面](docs/media/studio-source-overview.png)

*真实源码浏览器截图，连接独立本地 Runtime。缺失的 Kernel、节点与模型数据仍显示未配置或未知；此图不是已安装的 EXE。*

## 概览

APEIR Studio 是 APEIR Runtime 的桌面工作空间。用户可以组合项目、对话、任务、
资源和证据面板；Runtime 负责执行，Governance 负责授权，持久记录支持恢复。
模型、Agent 和 UI 扩展不能自行授权。

## 可以完成什么

- 浏览工程、审查文件 Diff，提交绑定原始版本的修改并请求审批。
- 组合 Docking 面板与只读 Dashboard，保存、导入及复用布局。
- 查看真实 Runtime/Kernel 状态、已登记 Node、Device、Work 与证据。
- 可视化编辑 Workflow，验证、注册原始定义，通过 Governance 运行已绑定的纯节点，并查看原始运行历史。
- 安装经过审查的 Skill 指令与声明式 Studio 界面扩展，使用公开 Provider SDK。
- 运行离线 [Verified Execution Demo](examples/hello_runtime/README.md)，
  包含拒绝、UNKNOWN、响应丢失对账和重启恢复。

模型调用需要已配置的 Provider 与通过认证的 Kernel；命令执行需要现有权限和合格沙箱。
安装指令不等于获得工具权限，执行成功不等于独立效果验证通过。

## 快速开始

请使用[唯一安装与首次运行入口](docs/operations/getting-started/QUICK_START.md)。
它明确区分 **Source Preview**、**Developer Setup** 和 **Native Installation**。
源码检查和模拟 Demo 不需要 API Key 或硬件。可下载的源码包不是 Windows 安装程序。

**Windows EXE / NSIS：BLOCKED。** 旧锁要求的 Kernel 二进制缺失，经过验证的
重建候选仍需维护者批准及 Windows10 安装生命周期验收。
查看[原生交付证据](docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md#r4-trusted-candidate-evidence--2026-10-24)。
当前不提供宣称已通过验收的安装包或正式 Release。

## 开发者平台

[Studio 使用指南](docs/development/DEVELOPER_PLATFORM.md#apeir-studio)介绍面板、
键盘操作、布局编辑、模型配置和当前限制。
修改源码与调试界面请使用 [Developer Setup](docs/operations/getting-started/QUICK_START.md#developer-setup)。
Studio 属于同一个 Distribution；独立的 [Kernel](https://github.com/untrod/apeir-kernel)
由[组件锁](runtime-components.lock.json)固定。

## SDK 与扩展

从[公开开发者平台](docs/development/DEVELOPER_PLATFORM.md)、
[Provider 示例](examples/hello_provider/README.md)和
[Skill 示例](examples/hello_skill/README.md)开始。
当前不开放第三方可执行 Studio UI。可视 Workflow、声明式 UI Contribution
及其验收状态以 ROADMAP 为准；安装包不会自动获得执行权限。

## 当前状态

Distribution `0.1.0-rc1` 是 **Source Developer Preview**。
源码安装及明确范围的软件场景已经验收，完整产品仍为 PARTIAL。
真实模型账号、严格执行隔离、Windows 原生安装、真实 IdP 和 Jetson/ESP32 物理写入
分别有独立前置条件。[ROADMAP](ROADMAP.md)是唯一里程碑状态来源。

UNKNOWN 失败关闭；Receipt 不等于 Observation；不确定的效果必须对账，不能盲目重放。

## 文档

[架构契约](docs/architecture/README.md) · [运维](docs/operations/README.md) ·
[Compute Mesh](docs/operations/compute-mesh/OPERATIONS.md) ·
[工程验收](docs/acceptance/ENGINEERING_REVIEW.md) ·
[发行 Runbook](docs/acceptance/RELEASE_RUNBOOK.md)

## 参与贡献

请先阅读 [CONTRIBUTING](CONTRIBUTING.md) 和 [SECURITY](SECURITY.md)。
[Issues](https://github.com/untrod/apeir/issues)用于脱敏复现，漏洞通过私密渠道报告。
`nous_runtime`、`nous`、`NOUS_*` 和既有协议标识为兼容保留。

## 许可证

Apache-2.0：[LICENSE](LICENSE)、[NOTICE](NOTICE)、[第三方声明](THIRD_PARTY_NOTICES.md)。

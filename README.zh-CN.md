# APEIR Studio

由 APEIR Runtime 驱动的开发工作空间：编辑工程文件、运行受治理的工作流、检查执行证据。

[**源码预览下载**](docs/operations/getting-started/QUICK_START.md#source-preview) ·
[**Windows 测试包**](docs/operations/getting-started/QUICK_START.md#native-installation) ·
[**快速开始**](docs/operations/getting-started/QUICK_START.md) ·
[**SDK 与扩展**](docs/development/DEVELOPER_PLATFORM.md#declarative-ui-extension-sdk) ·
[**文档**](docs/README.md) · [English](README.md)

![APEIR Studio 的对话、项目文件与分屏编辑器](docs/media/studio-workspace-source.png)

*真实源码浏览器界面，连接本地无模型 Runtime。这是 Source Developer Preview，不是 Windows 安装截图。*

## 从这里开始

- **体验工作台：**下载同一提交的 Runtime 与 Studio 预览包，按
  [快速开始](docs/operations/getting-started/QUICK_START.md)启动。
  需要 Python 3.10+；编译后的浏览器界面不需要 Node.js 或 Rust。
- **参与开发：**通过 [Developer Setup](docs/operations/getting-started/QUICK_START.md#developer-setup)
  安装可编辑源码，启动界面开发服务器并运行测试。
- **开发扩展：**从 [System Monitor 示例](examples/studio_system_monitor/README.md)
  或 [Provider 示例](examples/hello_provider/README.md)开始。

## 概览

APEIR Runtime 是面向异构智能与现实资源的开放运行时，本地优先，远程执行边界明确。

APEIR Studio 是 APEIR Runtime 的桌面工作空间。用户可以组合项目、对话、任务、
资源和证据面板；Runtime 负责执行，Governance 负责授权，持久记录支持恢复。
模型、Agent 和 UI 扩展不能自行授权。

## 可以完成什么

- 浏览工程、审查文件 Diff，提交绑定原始版本的修改并请求审批。
- 在 Models 中配置 Provider 引用；只有模型已经注册时，才由用户显式发起推理测试。
- 跟踪已记录的模型与工具活动，检查原始请求；事件重连不会重新提交任务。
- 组合 Docking 面板与只读 Dashboard，保存、导入及复用布局。
- 查看真实 Runtime/Kernel 状态、已登记 Node、Device、Work 与证据。
- 可视化编辑 Workflow，验证、注册原始定义，通过 Governance 运行已绑定的纯节点，并查看原始运行历史。
- 安装经过审查的 Skill 指令与声明式 Studio 界面扩展，使用公开 Provider SDK。
- 运行离线 [Verified Execution Demo](examples/hello_runtime/README.md)，
  包含拒绝、UNKNOWN、响应丢失对账和重启恢复。

本地模型与云端 Provider 可以并存，实际兼容性取决于协议和模型能力。
当前 NKI 返回完整响应：可以查看执行进度，暂不支持逐 Token 的模型文本输出。

模型调用需要已配置的 Provider 与通过认证的 Kernel；命令执行需要现有权限和合格沙箱。
安装指令不等于获得工具权限，执行成功不等于独立效果验证通过。

## 快速开始

请使用[唯一安装与首次运行入口](docs/operations/getting-started/QUICK_START.md)。
它明确区分 **Source Preview**、**Developer Setup** 和 **Native Installation**。
源码检查和模拟 Demo 不需要 API Key 或硬件。可下载的源码包不是 Windows 安装程序。

**Windows 下载：**[Portable 便携包 + NSIS 安装程序](https://github.com/untrod/apeir/actions/runs/40835150844/artifacts/12883321870)
已打包在 **windows-x64-native-development-build** 中。登录 GitHub 后下载工件 ZIP，
解压并校验哈希，再选择便携包或安装程序。工件保留至 **2026-11-12**。
这是未签名的候选预览，源码为较早的 main `05e061e4`，另有 Windows Context
超时尚在调查；准确版本和验收范围见
[构建记录](docs/operations/deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build)。
Windows 10 安装、升级、卸载及签名尚未验收，不能当作稳定版。
具体步骤见[下载与校验](docs/operations/getting-started/QUICK_START.md#native-installation)。

第一次体验可以先打开工程或运行无模型 Demo，不必一次配置完全部组件。
API Key 请留在凭据库，别让它客串截图主角。

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
[声明式 UI SDK](docs/development/DEVELOPER_PLATFORM.md#declarative-ui-extension-sdk)
支持经过审查的面板和 Widget，无需向可信主窗口注入任意 JavaScript。
第三方可执行 UI 在隔离验收前保持禁用；安装包不会自动获得执行权限。

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

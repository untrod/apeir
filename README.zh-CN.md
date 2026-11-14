# APEIR

<!-- Compatibility anchors for existing documentation links. -->
<a name="apeir-studio"></a>
<a name="sdk-与扩展"></a>
<a name="从这里开始"></a>
<a name="可以完成什么"></a>
<a name="开发者平台"></a>
<a name="当前状态"></a>
<a name="快速开始"></a>
<a name="文档"></a>
<a name="概览"></a>


开放、以本地工作为起点的工程工作台：组织文件、工作流和连接资源，修改先审查，操作有审批，结果有记录。

[**⬇ Windows x64**](https://github.com/untrod/apeir/actions/runs/43549734683/artifacts/14097790424) ·
[**Windows ARM64（平板等设备）**](https://github.com/untrod/apeir/actions/runs/43549737576/artifacts/14097648427) ·
[**Source Preview**](docs/operations/getting-started/QUICK_START.md#source-preview) ·
[**快速开始**](docs/operations/getting-started/QUICK_START.md) ·
[**文档**](docs/README.md) · [English](README.md)

**Windows：**Intel/AMD 电脑选 x64；小米平板 5 等 Windows on Arm 设备选 ARM64，不是 32 位。
[安装版](docs/operations/getting-started/INSTALL_WINDOWS.md#setup) · [Portable 用法](docs/operations/getting-started/INSTALL_WINDOWS.md#portable) · [SHA-256 校验](docs/operations/getting-started/QUICK_START.md#download-metadata)。
当前是未签名开发包，不是稳定版；下载需要登录 GitHub，Windows 10 安装仍待实机验收。
正式版还没出炉，生产环境先别急着端上桌。

![APEIR Studio 中的工程文件、编辑器与 Chat](docs/media/studio-workspace-source.png)

*Studio 源码界面的真实截图（Linux 浏览器，模型已禁用）。
下载的 Windows 包有独立构建版本；此图不代表 Windows 安装或真实模型验收。*

APEIR Studio 可以组合工程、对话、Workflow、任务和证据面板，保存自己的工作布局。
APEIR Runtime 负责已获准的操作与原始记录。模型和扩展提供能力，不负责批准自己的请求。

## 可以先做什么？

| 场景 | 使用入口 |
| --- | --- |
| 读取工程、审查多文件 Diff，再应用经过独立审批的修改 | [Studio 与工程修改](docs/operations/guides/USER_GUIDE.md#reviewing-workspace-changes) |
| 创建受支持的 Workflow，查看原始 Run，并恢复历史记录 | [Workflow 指南](docs/operations/guides/WORKFLOW_GUIDE.md) |
| 通过公开的声明式接口添加一个只读 Studio Widget | [System Monitor 示例](examples/studio_system_monitor/README.md) |

也可以[配置兼容的云端与本地模型](docs/operations/guides/PROVIDER_GUIDE.md)，
查看 Node、Device 和已经记录的工具活动。模型调用需要实际可用的端点及通过认证的
Kernel；测试命令还需要对应权限和合格沙箱。条件不足时会显示原因，不会装作已经执行。

## 下载与启动

[安装指南](docs/operations/getting-started/QUICK_START.md)提供三条路径：

- **Source Preview：**下载同源 Runtime wheel 与已构建的浏览器 Studio，需要 Python
  3.10+；使用这份前端不需要安装 Node.js 或 Rust。
- **Windows Development Build：**GitHub Actions 工件分别提供未签名的 x64、ARM64 Portable
  和 NSIS 安装程序，下载需要登录 GitHub。
- **Developer Setup：**从源码开发 Runtime、调试 Studio，适合参与项目或修改代码。

[下载信息](docs/operations/getting-started/QUICK_START.md#download-metadata)列出版本、
SHA-256、保留期限和验收范围。目前提供的是临时预览工件，没有稳定正式版或一键安装脚本。

## 开发与扩展

[开发者入口](docs/development/DEVELOPER_PLATFORM.md) ·
[公开 Provider SDK](docs/development/PROVIDER_DEVELOPMENT.md) ·
[UI Extension SDK](docs/development/STUDIO_UI_EXTENSIONS.md) ·
[示例](examples/README.md) · [API / CLI 参考](docs/development/README.md)

SDK 仍处于 beta。Studio UI 扩展目前使用经过审查的数据型 Manifest，
尚未开放任意第三方 JavaScript。独立维护的 [Kernel](https://github.com/untrod/apeir-kernel)
由[组件锁](runtime-components.lock.json)固定。

## 参与贡献

从 [CONTRIBUTING](CONTRIBUTING.md) 开始。可复现的问题通过
[Issues](https://github.com/untrod/apeir/issues)报告，安全漏洞按
[SECURITY](SECURITY.md)私下提交。架构与验收资料见[文档导航](docs/README.md)。
已有的 `nous` 命令和标识保留兼容用途。

## Developer Preview 状态

当前版本为 **0.1.0-rc1**，源码安装及部分完整软件流程已经验收。
未签名 Windows 包通过了构建和 Sidecar 检查，Windows 10 安装生命周期仍待验收。
真实模型账户、严格命令隔离和物理设备操作分别需要对应条件。
[ROADMAP](ROADMAP.md)是当前状态的唯一记录入口。
文件 MATCH 不代表测试已经运行，更不代表设备效果已经独立验证。

## 许可证

[Apache-2.0](LICENSE) · [NOTICE](NOTICE) · [第三方声明](THIRD_PARTY_NOTICES.md)

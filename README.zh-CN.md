# APEIR（无限）

APEIR 是一个本地优先的开放发行版，用于治理模型、软件工具、计算节点和设备
适配器上的执行。它由原生桌面应用、无界面 Runtime API、Provider 与扩展
适配器、节点及部署服务组成，并依赖独立发布的
[APEIR Kernel](https://github.com/untrod/apeir-kernel)。

APEIR Kernel 对经 NKI 准入的工作负载拥有最终权威，包括准入、Permit、资源
租约、调度、Kernel 持久状态、受治理副作用和执行证明。本仓库负责产品体验、
集成与有限的本地服务，不包含第二套 Rust Kernel。

[English](README.md) · [架构](docs/architecture/FOUNDATION_1_0.md) ·
[安全](SECURITY.md) · [贡献指南](CONTRIBUTING.md)

## 发布状态

当前版本为 **APEIR Distribution 0.1.0-rc1**，用于 Windows 10 x64 上的开发
与评估，尚不是正式稳定版。远程多机、Linux、Jetson、MCU 和真实设备仍需
单独认证；本地测试或模拟测试不会被描述成真实硬件验证。

## 组成

- **Desktop**：基于 Tauri 的原生桌面入口，提供配置、聊天、任务、文档、
  开发工具、环境、模拟、节点和诊断界面。
- **Runtime API**：仅监听本机、要求认证的产品编排服务。
- **Kernel Client**：Kernel 管理请求进入 NKI 的唯一生产路径。
- **Provider**：模型、MCP、Skill、文档、科学计算和设备适配器。
- **Node 服务**：身份、Relay、Artifact 传输、部署、健康、取消与恢复。
- **成本控制**：请求上限、每日预算、重试预算、统一 Usage Receipt，以及
  按任务、模型和凭据引用统计的用量。

## 执行边界

```text
Kernel 管理的工作负载
  Desktop / CLI / API / 扩展
    → Runtime 策略与成本预检
    → NKI 身份认证与版本验证
    → Kernel 准入 → Permit → Lease → 执行 → Receipt
    → Runtime 状态投影与用户结果

有限的本地服务
  Desktop / CLI / API
    → Runtime 授权与可选的一次性审批
    → 本地文档 / 环境 / 网络 / 模拟服务
    → Runtime 事件与 Artifact 证据
```

生产构造在 Kernel 不可用或 NKI 版本不兼容时会安全拒绝，不会自动改走
Provider 直连。直连仅保留为显式的兼容与隔离测试模式。

本候选版中的文件、文档、环境、网络、模拟和科学计算服务由 Runtime 授权层
治理，并明确返回 `execution_scope=runtime-service` 与
`kernel_traversed=false`，不会被描述为已经过 Kernel 执行。

## 开发环境

- Windows 10 x64
- Python 3.10–3.12
- Desktop 开发需要 Node.js 20 与 Rust stable
- 原生构建需要 Visual Studio 2022 C++ Build Tools 和 Windows SDK
- 独立的 APEIR Kernel 源码目录，其版本必须与
  [`runtime-components.lock.json`](runtime-components.lock.json) 一致

```powershell
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check nous_runtime tests scripts integrations sdk
python scripts/security_scan.py
```

桌面验证：

```powershell
cd desktop
npm ci
npm run lint
npm test
npm run typecheck
npm run build
```

Windows x64 安装包和便携包：

```powershell
$env:APEIR_KERNEL_ROOT = (Resolve-Path "..\apeir-kernel").Path
.\scripts\build-windows-x64-launcher.ps1 -KernelRoot $env:APEIR_KERNEL_ROOT
```

构建脚本会拒绝与锁文件提交不一致的 Kernel。Sidecar、安装包、数据库、
日志、凭据和验证证据不会进入公开源码树。

## 成本控制

APEIR 在模型请求进入 Kernel 前执行 Token 与费用预检。默认值可通过
`APEIR_MAX_INPUT_TOKENS`、`APEIR_MAX_OUTPUT_TOKENS`、
`APEIR_MAX_REQUEST_TOKENS`、`APEIR_MAX_DAILY_TOKENS`、
`APEIR_MAX_DAILY_COST_USD`、`APEIR_MAX_MODEL_ATTEMPTS`、
`APEIR_MAX_RETRY_TOKENS` 和 `APEIR_MAX_RETRY_COST_USD` 调整。

模型价格属于可更新配置，不写死在发行版代码中。将
`APEIR_MODEL_PRICING_FILE` 指向审核过的
[`config/model-pricing.example.json`](config/model-pricing.example.json)。未配置
价格的模型仍受 Token 上限约束，但费用估算保持为零。真实 API Key 不会写入
用量数据库，统计只保存凭据引用的哈希。

## 兼容性

公开品牌、桌面标题、包名和新命令采用 APEIR。`nous_runtime` Python 导入、
`nous` 命令别名、`NOUS_*` 环境变量和 `nous.*.v1` 协议标识在迁移期继续
保留。协议身份不会因为品牌变化而被原地替换。

## 安全

Runtime API 和 NKI 默认仅监听本机。Provider 密钥保存在操作系统凭据库，
或通过环境变量引用，不进入声明式源码配置。产生副作用的操作必须具有明确
授权并生成证据；不支持或未验证的路径会安全拒绝。

安全问题请通过
[GitHub Security Advisories](https://github.com/untrod/apeir/security/advisories/new)
私下报告，不要在公开 Issue 中提交密钥、私有提示、运行状态或漏洞细节。

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 和每个发行包
生成的第三方依赖声明。

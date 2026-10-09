# APEIR

APEIR 是面向异构智能与现实资源的开放执行、治理和验证运行时。
智能可以来自模型、外部 Agent、算法或人类；APEIR 负责 Work 生命周期、
授权、执行证据、独立观察、效果验证及恢复。

[English](README.md) · [唯一推荐快速开始](docs/operations/getting-started/QUICK_START.md) ·
[五份权威架构契约](docs/architecture/README.md) · [里程碑状态](ROADMAP.md) ·
[公开 SDK](docs/development/DEVELOPER_PLATFORM.md) · [贡献](CONTRIBUTING.md) · [安全](SECURITY.md)

## 开发预览

[Verified Execution Demo](examples/hello_runtime/README.md) 不需要 API Key 或真实硬件。
用户提交模拟固件更新，既有 AgentSession/Plan/Workflow 创建原始 Work，
Governance 暂停并等待明确的本地用户 Approve Once，随后通过签名 Node 执行。
Runtime 保留回执，再以单独的只读 Work 观察实际设备状态，只有 MATCH 才提交效果。

示例包含成功、拒绝、MISMATCH、UNKNOWN、响应丢失后核对证据且不重复副作用、
以及跨进程持久化恢复。输出来自真实 Runtime 数据，不是预设成功 JSON。
[Provider 示例](examples/hello_provider/README.md) 和
[Skill 示例](examples/hello_skill/README.md) 使用公开 SDK；
Skill 安装或声明能力不代表权限，加载指令也不代表设备执行。
[演示脚本](examples/hello_runtime/README.md#five-minute-video-script) 给出可复现的展示顺序。

现有 [科学报告链](docs/architecture/GOVERNED_SCIENTIFIC_RUNTIME.md) 复用模拟、
独立数值参考、Claim/Evidence 与 DOCX/PDF Runtime。当前 Cloud 环境缺少既有强隔离后端，
本次报告生成明确 BLOCKED，不采用普通宿主执行代替。数值比较和符号表达式不是数学定理证明。

## 架构与限制

```text
Goal → AgentSession / Plan → Workflow → Governance / Approval
     → Distributed Work → Node → Provider / Device → Receipt / Artifact
     → 独立 Observation → EffectVerification → MATCH 才能 COMMIT
```

Model、Planner、Scheduler 都不是授权方。UNKNOWN 失败关闭；Receipt 不等于 Observation，
可能已发生的效果必须核对证据，不能盲目重试。Node 不等于 Device，发现不等于信任，
能力不等于权限。

Distribution 保持 `0.1.0-rc1`；这是源码开发预览，不是 Production Release。
准确的软件验收、集成范围和阻塞以 ROADMAP 为唯一状态来源。
M3.3-C、M5 物理写入/掉电和第二类真实设备仍 PENDING，真实 IdP 部署未 qualification，
原生二进制实际哈希验证仍 BLOCKED；M6/M7 未验收。
模拟设备和 ESP32 主机合同不能代替物理证据。

Kernel 固定为 `87fd1b2ff28ef14ab1a515a58162592b452fda2e`；
`nous_runtime`、`nous`、`NOUS_*` 和协议标识为兼容保留。
从唯一 Quick Start 安装并使用独立空工作区；不要公开私钥、凭据或 Runtime 数据库。
问题反馈请附平台、命令、复现步骤和脱敏证据：
[GitHub Issues](https://github.com/untrod/apeir/issues)，漏洞按 SECURITY 私密报告。

Apache-2.0：[LICENSE](LICENSE)、[NOTICE](NOTICE)、[第三方声明](THIRD_PARTY_NOTICES.md)。

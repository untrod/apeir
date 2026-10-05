# APEIR

APEIR 是面向异构智能与现实资源的开放执行、治理和验证运行时。
智能可以来自模型、外部 Agent、算法或人类；APEIR 负责 Work 生命周期、
授权、执行证据、独立观察、效果验证及恢复。模型与调度器不是授权方，
UNKNOWN 失败关闭，可能已经发生的效果必须核对证据，不能盲目重试。

[English / 快速开始](README.md) · [架构](docs/architecture/README.md) ·
[里程碑状态](ROADMAP.md) · [开发](CONTRIBUTING.md) · [安全](SECURITY.md)

当前版本为 `0.1.0-rc1`，用于开发与评估。已验收的软件范围、未完成的集成、
硬件和原生二进制阻塞均以 ROADMAP 为准。模拟设备及只读 ESP32 主机合同不代表
物理验收；M3.3-C、M5 物理写入/掉电和第二类真实设备仍为 PENDING，M6/M7 未验收。
Kernel 保持独立并固定在组件锁记录的版本。`nous_runtime` 等历史标识为兼容保留。

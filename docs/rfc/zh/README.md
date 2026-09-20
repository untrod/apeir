# Nous AI Kernel — 中文架构文档

本目录包含 Nous AI Kernel 项目的中文架构文档。

## RFC 文档

| RFC | 标题 | 状态 |
|-----|------|------|
| RFC-0001 | [内核边界](RFC-0001-内核边界.md) | 草案 |
| RFC-0002 | 内核对象模型 | 待翻译 |
| RFC-0003 | Workload IR | 待翻译 |
| RFC-0004 | NKI v1 | 待翻译 |
| RFC-0005 | Engine ABI | 待翻译 |
| RFC-0006 | Device ABI | 待翻译 |
| RFC-0007 | Memory Fabric | 待翻译 |
| RFC-0008 | 资源模型 | 待翻译 |
| RFC-0009 | 调度器 | 待翻译 |
| RFC-0010 | 安全 | 待翻译 |
| RFC-0011 | 状态与恢复 | 待翻译 |
| RFC-0012 | Model Package | 待翻译 |
| RFC-0013 | Agent Program | 待翻译 |
| RFC-0014 | Conformance | 待翻译 |

## 架构概览

Nous AI Kernel 是一个 AI 系统内核，统一管理模型、推理引擎、Agent 程序、工具、内存、KV Cache、硬件设备、节点、任务、质量、安全、状态与恢复。

内核不替代 Linux 的 CPU、虚拟内存、文件系统、网络和驱动能力，而是在其上建立 AI 特有的系统语义。

### 核心创新

> 把模型、推理阶段、Agent 程序、工具、硬件、内存、质量、安全和长期状态统一为一套 AI 内核对象，并通过稳定 ABI 让不同企业和开发者在其上构建产品。

### 目标架构

```
Applications / Enterprise Products
            │
     NKI (稳定 ABI)
            │
┌───────────┴──────────────┐
│     Nous AI Kernel        │
│  - 对象模型               │
│  - 资源准入               │
│  - 多层调度               │
│  - Memory Fabric          │
│  - 安全与治理             │
│  - 状态日志与恢复         │
└──────┬──────────┬─────────┘
       │          │
  Engine ABI  Device ABI
```

### 仓库结构

```
kernel/          — Rust 内核实现
spec/            — Protobuf IDL（单一事实来源）
docs/rfc/        — 英文 RFC
docs/rfc/zh/     — 中文 RFC
compat/          — Python 兼容层
benchmarks/      — 基准测试套件
```

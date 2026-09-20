# RFC-0003: Workload IR

- **状态:** 草案 | **日期:** 2026-08-04

## 问题

当前没有统一的"工作内容"表示。Chat、Completion、Agent、Workflow、Tool 各自使用不同的请求格式。

## WorkloadSpec

统一的 Workload IR 包含：身份、Principal、Namespace、目标、WorkloadType（19 种）、ExecutionGraph、模型需求、能力需求、设备需求、质量需求、安全需求、资源需求、延迟 SLO、截止时间、能源预算、成本预算、检查点策略、取消策略、重试策略、回退策略、输出契约。

## 17 状态生命周期

CREATED→VALIDATING→VALIDATED→REJECTED|ADMITTED→PLACED→PREPARING→RUNNING→QUIESCING→CHECKPOINTING→CHECKPOINTED→RECOVERING→SUCCEEDED|FAILED|CANCELLED|LOST|QUARANTINED

## Phase Graph

每个 Workload 编译为阶段图：Receive→Validate→Authenticate→Resolve→Retrieve→Plan→Admit→Place→Prepare→Tokenize→Encode→Prefill→Decode→ToolExecute→Observe→Verify→Replan→Finalize→Commit。

每个 Phase 声明：输入/输出、依赖、设备、引擎、资源需求、幂等性、可取消性、副作用、补偿动作、超时。

## 编译要求

所有产品输入必须先编译为 Workload IR 才能进入内核。禁止产品层绕过 Workload IR 直接调用 Provider。

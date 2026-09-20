# Nous OpenTelemetry Semantic Conventions — v1beta1

> Version: 1.0.0-beta1
> Status: v1beta1
> Base: OpenTelemetry Semantic Conventions 1.43.0

## Design Principle

Nous extends OpenTelemetry conventions — does NOT replace them. Standard HTTP,
RPC, and system attributes apply as normal. Nous-specific attributes are prefixed
with `nous.` and apply to AI workload execution, scheduling, and resource management.

## Trace Spans

### Core Workload Trace

```
Submit ──► Validate ──► Admit ──► Schedule ──► Claim ──► Bind
                                                              │
                                                              ▼
                    ┌── Prefill ──► Decode ──► Tool ──► Verify
                    │                                         │
                    └──────────────◄─────────────────────────┘
                                                              │
                                                              ▼
                                              Commit ──► Observe
```

### Span Attributes

| Span | Attribute | Type | Description |
|------|-----------|------|-------------|
| `Submit` | `nous.workload.id` | string | Short workload ID (not full UUID for high-cardinality) |
| | `nous.workload.type` | string | CHAT, COMPLETION, AGENT_PROGRAM, WORKFLOW, etc. |
| | `nous.principal.id` | string | Short principal ID |
| `Validate` | `nous.validation.errors` | int | Number of validation errors |
| | `nous.validation.warnings` | int | Number of validation warnings |
| `Admit` | `nous.admission.decision` | string | Admitted, Rejected, Infeasible |
| | `nous.admission.reason` | string | Rejection reason (if applicable) |
| `Schedule` | `nous.scheduler.policy` | string | Policy name (weighted-sum, pareto, etc.) |
| | `nous.scheduler.candidates` | int | Number of placement candidates |
| | `nous.scheduler.selected_node` | string | Node ID of placement |
| | `nous.scheduler.selected_device` | string | Device ID of placement |
| `Claim` | `nous.lease.id` | string | Short lease ID |
| | `nous.lease.duration_us` | int64 | Lease duration in microseconds |
| `Bind` | `nous.engine.id` | string | Engine ID |
| | `nous.model.family` | string | Model family name |
| | `nous.model.revision` | string | Model revision/hash |
| `Prefill` | `nous.prefill.tokens` | int | Number of prefill tokens |
| | `nous.prefill.duration_us` | int64 | Prefill duration |
| `Decode` | `nous.decode.tokens` | int | Number of decode tokens |
| | `nous.decode.tokens_per_second` | double | Throughput |
| `Tool` | `nous.tool.name` | string | Tool name |
| | `nous.tool.duration_us` | int64 | Tool execution duration |
| `Verify` | `nous.verify.quality_score` | double | Quality score (0.0–1.0) |
| | `nous.verify.passed` | bool | Did verification pass? |
| `Commit` | `nous.workload.phase` | string | Final phase (SUCCEEDED, FAILED, etc.) |
| | `nous.workload.total_tokens` | int | Total tokens consumed |
| | `nous.workload.total_cost_usd` | double | Total cost in USD |
| `Recover` | `nous.recovery.from_phase` | string | Phase before failure |
| | `nous.recovery.action` | string | Resume, Restart, MarkLost, MarkFailed |

## Metrics

### Workload Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.workload.count` | Counter | Total workloads submitted |
| `nous.workload.duration_us` | Histogram | Workload end-to-end duration |
| `nous.workload.active` | Gauge | Currently active workloads |
| `nous.workload.queue_depth` | Gauge | Workloads waiting in queue |

### Model Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.model.inference.count` | Counter | Total inference requests |
| `nous.model.tokens.total` | Counter | Total tokens processed |
| `nous.model.tokens_per_second` | Gauge | Current throughput |
| `nous.model.ttft_us` | Histogram | Time to first token |
| `nous.model.tpot_us` | Histogram | Time per output token |

### Engine Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.engine.loaded_models` | Gauge | Number of loaded models |
| `nous.engine.active_requests` | Gauge | Currently active requests |
| `nous.engine.health` | Gauge | 1=healthy, 0=unhealthy |

### Device Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.device.utilization` | Gauge | GPU/utilization percent |
| `nous.device.memory_used_bytes` | Gauge | Used device memory |
| `nous.device.memory_total_bytes` | Gauge | Total device memory |
| `nous.device.temperature_celsius` | Gauge | Device temperature |
| `nous.device.power_milliwatts` | Gauge | Power consumption |

### Scheduler Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.scheduler.placements` | Counter | Total placement decisions |
| `nous.scheduler.rejections` | Counter | Total rejections |
| `nous.scheduler.candidates_evaluated` | Histogram | Candidates per decision |

### Lease Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.lease.active` | Gauge | Currently active leases |
| `nous.lease.expired` | Counter | Expired leases |
| `nous.lease.renewed` | Counter | Renewed leases |

### Memory Metrics

| Name | Type | Description |
|------|------|-------------|
| `nous.memory.hbm_used_bytes` | Gauge | HBM/VRAM used |
| `nous.memory.ram_used_bytes` | Gauge | RAM used |
| `nous.memory.kv_cache_used_bytes` | Gauge | KV cache used |
| `nous.memory.pressure` | Gauge | Memory pressure (0.0–1.0) |

## Cardinality Rules

- **DO NOT** put user text, prompts, or full UUIDs in metric labels
- **DO** put high-cardinality identifiers in trace span attributes
- Short IDs (first 12 chars of UUID) are acceptable in traces
- Metric label values must have bounded cardinality (<100 unique values)

## Resource Attributes

| Attribute | Description |
|-----------|-------------|
| `nous.kernel.version` | Kernel version string |
| `nous.node.id` | Node identifier |
| `nous.node.arch` | CPU architecture |
| `nous.node.os` | Operating system |
| `nous.distribution.name` | Distribution name (if applicable) |
| `nous.distribution.version` | Distribution version |

# Agent Process — v1alpha

> Status: v1alpha (experimental)
> Target: RC8
> Does NOT modify: NKI v1beta1, Engine ABI v1beta1, Device ABI v1beta1

## AgentProcess

```
AgentProcess {
    // Identity
    process_id: UUIDv7,
    parent_process_id: UUIDv7 | null,
    process_group_id: UUIDv7,
    namespace: string,
    principal: PrincipalRef,

    // Program
    program_revision: string,        // Hash of program definition
    program_counter: uint64,         // Current execution position
    continuation: Continuation,      // Serializable execution state

    // Communication
    mailbox: ProcessSignal[],        // Queued signals

    // Memory
    context_address_space: ContextAddressSpace,

    // Security
    capability_set: CapabilitySet,   // Inherited + granted (can only shrink)

    // Resources
    resource_domain: ResourceDomain,
    quality_budget: float,           // 0.0–1.0 minimum quality
    latency_budget_us: uint64,
    cost_budget_microcents: uint64,
    energy_budget_millijoules: uint64,

    // Durability
    checkpoint: CheckpointRef | null,
    effect_log: EffectReceipt[],     // Immutable append-only

    // Status
    status: AgentProcessStatus,
}
```

## AgentProcessStatus (14 states)

```
CREATED           → READY
READY             → RUNNING | CANCELLED
RUNNING           → WAITING_MODEL | WAITING_TOOL | WAITING_IO |
                    WAITING_APPROVAL | SUSPENDED | CHECKPOINTING |
                    COMPLETED | FAILED | CANCELLED
WAITING_MODEL     → RUNNING | FAILED | CANCELLED
WAITING_TOOL      → RUNNING | FAILED | CANCELLED
WAITING_IO        → RUNNING | FAILED | CANCELLED
WAITING_APPROVAL  → RUNNING | FAILED | CANCELLED
SUSPENDED         → RUNNING | CANCELLED
CHECKPOINTING     → RUNNING | FAILED | CANCELLED
MIGRATING         → RUNNING | FAILED
RECOVERING        → RUNNING | FAILED
COMPLETED         (terminal)
FAILED            → RECOVERING | QUARANTINED
CANCELLED         (terminal)
QUARANTINED       (terminal)
```

## Process Signals (11)

| Signal | Direction | Effect |
|--------|-----------|--------|
| PAUSE | Kernel → Process | Suspend execution, preserve state |
| RESUME | Kernel → Process | Resume from suspension |
| CANCEL | Kernel → Process | Graceful termination |
| CHECKPOINT | Kernel → Process | Take a snapshot now |
| REPLAN | Kernel → Process | Current plan invalid, regenerate |
| ESCALATE_MODEL | Kernel → Process | Switch to stronger model |
| REDUCE_BUDGET | Kernel → Process | Tighten cost/latency budget |
| MIGRATE | Kernel → Process | Move to different node/device |
| VERIFY | Kernel → Process | Enter verification phase |
| QUARANTINE | Kernel → Process | Isolate, stop all side effects |
| TERMINATE | Kernel → Process | Force kill (no cleanup) |

## Continuation

```
Continuation {
    stack: Frame[],            // Call stack
    heap: Map<string, Value>,  // Program variables
    pc: uint64,                // Program counter
    env: Map<string, string>,  // Environment bindings
}
```

## Parent-Child Process Model

```
Parent capabilities:
- wait_all(): block until all children complete
- wait_any(): block until any child completes
- cancel_group(): cancel entire process group
- budget_total(): enforce aggregate budget
- aggregate_results(): collect child outputs
- handle_partial_failure(): decide retry/fallback
- spawn_child(program, caps): create child with equal-or-fewer capabilities
```

## Capability Inheritance

```
Child capability_set ⊆ Parent capability_set
(MUST be subset — can never expand)
```

## NKI Extensions (new methods, additive)

```
SubmitProcess(AgentProcessSpec) → AgentProcess
GetProcess(process_id) → AgentProcess
ListProcesses(namespace) → AgentProcess[]
SignalProcess(process_id, signal) → AgentProcess
CheckpointProcess(process_id) → Checkpoint
RestoreProcess(checkpoint_id) → AgentProcess
MigrateProcess(process_id, target_node) → AgentProcess
GetProcessCertificate(process_id) → WorkloadCertificate
```

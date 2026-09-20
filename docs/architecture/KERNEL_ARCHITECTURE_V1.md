# Kernel Architecture v1.0

## Nine Subsystems

```
┌─────────────────────────────────────────────────────┐
│                   Nous Runtime                       │
├─────────────────────────────────────────────────────┤
│ 01 Runtime Core     │ Boot, lifecycle, config       │
│ 02 Object Model     │ ID, version, status, metadata │
│ 03 Capability       │ What can be done              │
│ 04 Provider         │ Who/how executes              │
│ 05 Planner/Exec     │ Goal->Plan->Task->Execute        │
│ 06 State/Memory     │ State, memory, knowledge      │
│ 07 Security/Policy  │ Auth, permission, audit       │
│ 08 Protocol/Fed     │ Transport, discovery, message  │
│ 09 Observability    │ Events, logs, metrics, trace  │
└─────────────────────────────────────────────────────┘
```

## Subsystem Contracts

### 01 Runtime Core
- **Responsibility**: Process lifecycle
- **States**: BOOT -> INITIALIZING -> READY -> RUNNING -> DEGRADED -> RECOVERING -> STOPPING -> TERMINATED
- **Entry points**: `Runtime.start()`, `Runtime.stop()`, `Runtime.status()`
- **Must NOT**: contain domain knowledge, user data, or model-specific logic

### 02 Object Model
- **Responsibility**: Unified identity for all runtime objects
- **Objects**: Goal, Plan, Task, Job, Capability, Provider, Pack, Node, Policy, Resource
- **Required fields**: id, kind, api_version, name, created_at, updated_at, generation
- **Status fields**: phase, health, conditions[]

### 03 Capability
- **Responsibility**: Declare what can be done
- **Required**: id, version, input_schema, output_schema, permissions, dependencies
- **Lifecycle**: REGISTER -> VALIDATE -> ENABLE -> READY -> EXECUTE -> DISABLE -> DEPRECATE -> UNREGISTER
- **Must NOT**: know who executes it (that's Provider's job)

### 04 Provider
- **Responsibility**: Execute capabilities
- **Required**: identity, version, capabilities[], health(), cost_estimate()
- **Lifecycle**: DISCOVER -> CONNECT -> AUTHENTICATE -> ADVERTISE -> HEALTH_CHECK -> READY -> EXECUTE
- **Types**: Model, Software, Device, Service, Storage, Node

### 05 Planner & Execution
- **Responsibility**: Turn goals into executed tasks
- **Pipeline**: Goal -> Plan -> Task Graph -> Schedule -> Dispatch -> Execute -> Evaluate
- **Must NOT**: hardcode LLM as the only planner

### 06 State, Memory & Experience
- **Responsibility**: Manage all forms of system state
- **Taxonomy**: Runtime State | Durable State | Memory | Knowledge Reference | Experience
- **Must NOT**: store user's personal knowledge as Runtime state

### 07 Security, Trust & Policy
- **Responsibility**: Protect the Runtime
- **Pipeline**: Identity -> AuthN -> AuthZ -> Permission -> Policy -> Risk -> Admission -> Execution -> Audit
- **Decisions**: ALLOW | DENY | REQUIRE_APPROVAL | SANDBOX_ONLY

### 08 Protocol & Federation
- **Responsibility**: Inter-node communication
- **Core**: Unified Envelope (protocol, version, msg_type, source, target, payload)
- **Transports**: HTTP, WebSocket, MQTT (pluggable)

### 09 Observability, Reliability & Recovery
- **Responsibility**: Make everything observable
- **Pillars**: Events, Logs, Metrics, Traces, Health, Diagnostics
- **Error Model**: Unified error codes (NOUS_OK, NOUS_TIMEOUT, etc.)

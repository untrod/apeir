# RFC-0002: Nous Kernel Object Model

- **Status:** Draft
- **Date:** 2026-08-04
- **Author:** Nous Kernel Architecture
- **Depends on:** RFC-0001 (Kernel Boundary)

---

## 1. Problem

The current Nous codebase has no unified object model:

1. **Three Task models**: `kernel.Task` (22-phase), `task.Task` (7-status), `events.RunState` (11-state) — semantically the same entity, modeled three ways with no mapping.
2. **22+ registry classes**: Each has its own ID scheme, persistence, indexing, and lifecycle management. `RegistryBase` exists but is only used by `NousServer`.
3. **No Spec/Status distinction**: Configuration, desired state, and observed state are mixed in flat dictionaries.
4. **No resource versioning**: Concurrent modifications have no CAS protection (except `kernel.StateMachine` which is unused by most stores).
5. **Inconsistent identity**: Some objects use UUID, some use incrementing integers, some use name-based keys.
6. **Orchestration prototypes**: `orchestration/` defines `TaskGraph`, `WriteLease`, etc. — duplicating kernel concepts without reference.

---

## 2. Constraints

1. Must be expressible in Rust (primary) and Python (compatibility)
2. Must support Protobuf serialization for NKI
3. Must support JSON serialization for debugging and migration
4. Must be backwards-compatible with existing Python data models
5. Every object must have exactly one authoritative owner (per RFC-0001)

---

## 3. Core Object Model

### 3.1 Object Identity

Every kernel object MUST have:

```protobuf
message ObjectMeta {
  // Globally unique identifier (UUID v7 — time-ordered)
  string uid = 1;

  // Schema version for this object type
  uint32 schema_version = 2;

  // Human-readable name (unique within namespace)
  string name = 3;

  // Namespace for multi-tenancy
  string namespace = 4;

  // Principal who owns this object
  string owner_principal = 5;

  // Creation timestamp (Unix microseconds)
  int64 created_at_us = 6;

  // Last modification timestamp
  int64 updated_at_us = 7;

  // Monotonically increasing generation (for CAS)
  uint64 generation = 8;

  // Opaque resource version (for optimistic concurrency)
  string resource_version = 9;

  // Labels for indexing and selection
  map<string, string> labels = 10;

  // Annotations for non-identifying metadata
  map<string, string> annotations = 11;

  // Current lifecycle phase
  string phase = 12;

  // Human-readable reason for current phase
  string phase_reason = 13;

  // Health status
  HealthStatus health = 14;

  // Conditions (array of typed conditions)
  repeated Condition conditions = 15;

  // Distributed trace ID (W3C TraceContext)
  string trace_id = 16;

  // Audit metadata
  AuditMetadata audit = 17;
}
```

### 3.2 Spec/Status Pattern

All kernel objects follow the Kubernetes-inspired Spec/Status pattern:

```rust
/// Every kernel object splits into:
/// - Spec: the user's or system's desired state (immutable after creation)
/// - Status: the kernel's observed actual state (mutable, updated by kernel)
pub trait KernelObject {
    type Spec;
    type Status;

    fn meta(&self) -> &ObjectMeta;
    fn spec(&self) -> &Self::Spec;
    fn status(&self) -> &Self::Status;
}
```

**Rules:**
- Spec is set at creation time and is immutable thereafter (except by explicit update with generation check)
- Status is updated ONLY by the kernel (never by external clients)
- Status updates go through the state machine and journal
- Clients update Spec by submitting a new Workload or an UpdateObject request
- Spec and Status are never stored in the same flat dictionary

### 3.3 Lifecycle Phase

Every object has a lifecycle phase:

```
         CREATED
            │
      ┌─────┴─────┐
      ▼           ▼
  VALIDATING   REJECTED
      │
      ▼
  PROVISIONING ──────► FAILED
      │
      ▼
  AVAILABLE
      │
  ┌───┴────┐
  ▼        ▼
ACTIVE   QUIESCING
  │        │
  ▼        ▼
DRAINING  DRAINED
  │
  ▼
TERMINATING
  │
  ▼
TERMINATED
```

Not all objects use all phases, but the naming and semantics are consistent across object types.

### 3.4 Conditions

```protobuf
message Condition {
  // Unique condition type (e.g., "Ready", "MemoryPressure", "LeaseExpired")
  string type = 1;

  // Status of the condition: True, False, Unknown
  ConditionStatus status = 2;

  // Machine-readable reason for the condition's last transition
  string reason = 3;

  // Human-readable message
  string message = 4;

  // Last time the condition transitioned
  int64 last_transition_us = 5;

  // Last time the condition was observed
  int64 observed_us = 6;
}

enum ConditionStatus {
  CONDITION_TRUE = 0;
  CONDITION_FALSE = 1;
  CONDITION_UNKNOWN = 2;
}
```

---

## 4. Core Kernel Objects

### 4.1 Principal

```protobuf
message Principal {
  ObjectMeta meta = 1;
  PrincipalSpec spec = 2;
  PrincipalStatus status = 3;
}

message PrincipalSpec {
  PrincipalType type = 1;       // User, Service, Node, System
  string display_name = 2;
  bytes public_key = 3;         // Ed25519 public key
  repeated string roles = 4;
}

message PrincipalStatus {
  bool authenticated = 1;
  int64 last_seen_us = 2;
  repeated string active_leases = 3;
}
```

### 4.2 Namespace

```protobuf
message Namespace {
  ObjectMeta meta = 1;
  NamespaceSpec spec = 2;
  NamespaceStatus status = 3;
}

message NamespaceSpec {
  repeated string owners = 1;
  ResourceQuota quota = 2;
  repeated string allowed_principals = 3;
}

message NamespaceStatus {
  ResourceVector used = 1;
  uint32 active_workloads = 2;
}
```

### 4.3 Workload

```protobuf
message Workload {
  ObjectMeta meta = 1;
  WorkloadSpec spec = 2;       // See RFC-0003
  WorkloadStatus status = 3;
}

message WorkloadStatus {
  WorkloadPhase phase = 1;     // Full 17-state lifecycle
  uint32 current_phase_index = 2;
  string node_id = 3;          // Assigned node
  string engine_id = 4;        // Assigned engine
  string model_revision = 5;   // Assigned model revision
  ResourceLease lease = 6;
  repeated Run runs = 7;       // Execution history
  CheckpointRef latest_checkpoint = 8;
  repeated Condition conditions = 9;
  int64 started_at_us = 10;
  int64 completed_at_us = 11;
  PerformanceMetrics metrics = 12;
  repeated AuditRecord audit = 13;
  ErrorInfo error = 14;        // Non-null if failed
}
```

### 4.4 Run

```protobuf
message Run {
  // Unique run identifier (UUID v7)
  string run_id = 1;

  // Parent workload UID
  string workload_id = 2;

  // Monotonic run number within workload
  uint32 run_number = 3;

  // Run phase
  RunPhase phase = 4;

  // The phase graph being executed
  repeated PhaseExecution phases = 5;

  // Resources consumed
  ResourceVector consumed = 6;

  // Start/end timestamps
  int64 started_at_us = 7;
  int64 ended_at_us = 8;

  // Outcome
  RunOutcome outcome = 9;
}
```

### 4.5 ModelPackage

```protobuf
message ModelPackage {
  ObjectMeta meta = 1;
  ModelPackageSpec spec = 2;   // See RFC-0007
  ModelPackageStatus status = 3;
}

message ModelPackageSpec {
  string family = 1;
  string architecture = 2;
  uint64 total_parameters = 3;
  uint64 activated_parameters = 4;
  uint32 layer_count = 5;
  uint32 hidden_size = 6;
  string attention_type = 7;
  uint32 attention_heads = 8;
  uint32 kv_heads = 9;
  uint32 head_dimension = 10;
  uint32 expert_count = 11;
  uint32 active_experts = 12;
  uint32 context_length = 13;
  string tokenizer = 14;
  repeated string modalities = 15;
  string weight_format = 16;
  string weight_precision = 17;
  string activation_precision = 18;
  string quantization = 19;
  repeated string supported_engines = 20;
  repeated string supported_devices = 21;
  repeated string required_operators = 22;
  ResourceVector memory_requirements = 23;
  string license = 24;
  string source = 25;
  bytes sha256 = 26;
  bytes signature = 27;
  string sbom = 28;
  BenchmarkProfile benchmark_profiles = 29;
}
```

### 4.6 Engine

```protobuf
message Engine {
  ObjectMeta meta = 1;
  EngineSpec spec = 2;
  EngineStatus status = 3;
}

message EngineSpec {
  string engine_type = 1;           // "llama.cpp", "vLLM", "SGLang", "ONNX", etc.
  string version = 2;
  repeated string capabilities = 3; // "chat", "completion", "embedding", "vision", etc.
  repeated string supported_architectures = 4;
  repeated string supported_quantizations = 5;
  bool supports_streaming = 6;
  bool supports_batching = 7;
  bool supports_pause = 8;
  bool supports_snapshot = 9;
  DeviceRequirements device_requirements = 10;
}

message EngineStatus {
  EnginePhase phase = 1;
  string process_id = 2;
  repeated string loaded_models = 3;
  ResourceVector allocated = 4;
  PerformanceMetrics metrics = 5;
  int64 last_health_check_us = 6;
}
```

### 4.7 Device

```protobuf
message Device {
  ObjectMeta meta = 1;
  DeviceSpec spec = 2;
  DeviceStatus status = 3;
}

message DeviceSpec {
  DeviceType device_type = 1;  // CPU, CUDA, ROCm, Vulkan, OpenVINO
  string vendor = 2;
  string model = 3;
  string driver_version = 4;
  ResourceVector total_resources = 5;
  repeated string capabilities = 6;
}

message DeviceStatus {
  DevicePhase phase = 1;
  ResourceVector available = 2;
  double temperature_celsius = 3;
  uint32 power_watts = 4;
  double utilization_percent = 5;
  repeated string active_engines = 6;
  TopologyLink topology = 7;
  int64 last_health_check_us = 8;
}
```

### 4.8 Node

```protobuf
message Node {
  ObjectMeta meta = 1;
  NodeSpec spec = 2;
  NodeStatus status = 3;
}

message NodeSpec {
  string hostname = 1;
  string arch = 2;               // x86_64, aarch64, armv7
  string os = 3;                 // linux, windows, macos, android
  ResourceVector capacity = 4;
  repeated string roles = 5;     // "primary", "worker", "edge"
}

message NodeStatus {
  NodePhase phase = 1;
  ResourceVector allocatable = 2;
  repeated string devices = 3;
  repeated string engines = 4;
  repeated string active_workloads = 5;
  int64 last_heartbeat_us = 6;
  string kernel_version = 7;
}
```

### 4.9 ResourceLease

```protobuf
message ResourceLease {
  string lease_id = 1;
  string workload_id = 2;
  string principal_id = 3;
  ResourceVector reserved = 4;
  string node_id = 5;
  string device_id = 6;
  int64 granted_at_us = 7;
  int64 expires_at_us = 8;
  uint64 generation = 9;
  bool renewable = 10;
}
```

### 4.10 Checkpoint

```protobuf
message Checkpoint {
  string checkpoint_id = 1;
  string workload_id = 2;
  uint64 sequence = 3;           // Monotonic within workload
  bytes state_snapshot = 4;      // Opaque state blob
  string node_id = 5;
  int64 created_at_us = 6;
  bytes sha256 = 7;
}
```

### 4.11 Event

```protobuf
message Event {
  string event_id = 1;
  string workload_id = 2;
  uint64 sequence = 3;           // Monotonic within workload
  string event_type = 4;         // "<domain>.<action>"
  int64 timestamp_us = 5;
  string actor = 6;              // Principal UID
  bytes payload = 7;             // Type-specific protobuf
  string phase = 8;              // Phase during which event occurred
  string trace_id = 9;
}
```

### 4.12 AuditRecord

```protobuf
message AuditRecord {
  string audit_id = 1;
  string workload_id = 2;
  string principal_id = 3;
  string action = 4;
  string decision = 5;           // ALLOW, DENY, DEFER
  string reason = 6;
  bytes context = 7;             // Decision context
  int64 timestamp_us = 8;
}
```

### 4.13 CapabilityGrant

```protobuf
message CapabilityGrant {
  string grant_id = 1;
  string principal_id = 2;
  string capability = 3;         // e.g., "shell.execute", "file.write"
  repeated string paths = 4;     // Scope: allowed paths
  repeated string hosts = 5;     // Scope: allowed network destinations
  ResourceLimits limits = 6;
  bool requires_approval = 7;
  string data_classification = 8;
  int64 granted_at_us = 9;
  int64 expires_at_us = 10;
}
```

---

## 5. Registry Unification

### 5.1 Generic Registry Interface

```rust
/// Every kernel object type gets a typed registry.
/// All registries share the same underlying storage and semantics.
pub trait ObjectRegistry<T: KernelObject> {
    async fn create(&self, obj: T) -> Result<T, RegistryError>;
    async fn get(&self, uid: &str) -> Result<Option<T>, RegistryError>;
    async fn update(&self, uid: &str, generation: u64, spec: T::Spec) -> Result<T, RegistryError>;
    async fn delete(&self, uid: &str, generation: u64) -> Result<(), RegistryError>;
    async fn list(&self, namespace: &str, filters: &[LabelSelector]) -> Result<Vec<T>, RegistryError>;
    async fn watch(&self, namespace: &str) -> Result<WatchStream<T>, RegistryError>;
    async fn update_status(&self, uid: &str, status: T::Status) -> Result<T, RegistryError>;
}
```

### 5.2 Key Design Decisions

1. **UUID v7 for all objects**: Time-ordered, globally unique, no central ID allocator.
2. **Generation for CAS**: Every update must pass the current generation. Mismatch = conflict.
3. **ResourceVersion for watches**: Opaque string that changes on every write; clients use it for efficient watch resumption.
4. **Namespace isolation**: All objects belong to a namespace. Cross-namespace access requires explicit grant.
5. **Labels for selection**: `key=value` pairs for filtering. Annotations for non-queryable metadata.
6. **Status updates are kernel-only**: External clients can only update Spec. Status is derived by the kernel.

---

## 6. Transition from Current State

### 6.1 Mapping Current to Target

| Current | Target |
|---------|--------|
| `kernel.Task` | `Workload` |
| `task.Task` | `Workload` (compat mapping) |
| `events.RunState` | `WorkloadStatus.phase` |
| `events.RunEvent` | `Event` |
| `checkpoint.Checkpoint` | `Checkpoint` |
| `kernel.state_machine.Lease` | `ResourceLease` |
| `kernel.Node` | `Node` |
| `model_runtime.ModelDescriptor` | `ModelPackage` |
| `model_runtime.ModelInstance` | `Engine` status (loaded model) |
| `kernel.identity.NodeIdentity` | `Principal` + `Node` |
| `kernel.identity.CapabilityGrant` | `CapabilityGrant` |
| `governance.*` | `AuditRecord` |
| `kernel.session.Session` | System service (not kernel object) |
| `kernel.session.Conversation` | System service (not kernel object) |

### 6.2 Migration Strategy

1. New objects defined in Protobuf IDL (single source of truth)
2. Rust types generated from IDL
3. Python types generated from IDL (via protobuf)
4. Compatibility mappers: old Python dict → new protobuf → old Python dict
5. Journal stores new-format objects; old EventStream reads via compat layer
6. Gradually switch writers to new format, then remove old format

---

## 7. Validation

### 7.1 Schema Tests

- Every object type has a valid protobuf definition
- Protobuf compiles for Rust and Python
- JSON round-trip: object → JSON → object preserves all fields
- Binary round-trip: object → protobuf → object preserves all fields

### 7.2 Registry Tests

- Create → Get returns same object
- Update with wrong generation → conflict error
- Delete → Get returns None
- List returns only objects in namespace
- Watch receives create/update/delete events

### 7.3 Spec/Status Tests

- External client cannot write Status directly
- Status update goes through state machine validation
- Spec update increments generation
- Status update does NOT increment generation (separate resourceVersion)

### 7.4 Migration Tests

- Old `kernel.Task` → `Workload` → old `kernel.Task` preserves semantics
- Old `events.RunRecord` → `WorkloadStatus` with runs preserves history
- Old checkpoint → new Checkpoint preserves state

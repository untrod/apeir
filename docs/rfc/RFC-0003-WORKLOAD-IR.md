# RFC-0003: Workload IR

- **Status:** Draft
- **Date:** 2026-08-04
- **Author:** Nous Kernel Architecture
- **Depends on:** RFC-0001, RFC-0002

---

## 1. Problem

The current Nous Runtime has no unified representation of "what work to do":

1. **Multiple request formats**: `RuntimeRequest` (chat/interaction), `model_runtime.ModelRequest` (raw inference), capability invocation, workflow definitions — each with different fields, different validation, different routing.
2. **Product layers bypass scheduling**: Desktop, CLI, and HTTP API route requests directly to Providers, tools, or models without going through any unified admission or scheduling layer.
3. **No workload-level resource estimation**: Resources are estimated per-model-call, not per complete workload (which may span multiple models, tools, and verification steps).
4. **No workload-level SLO**: Latency, quality, cost, and energy budgets cannot be expressed for a complete unit of work.
5. **No workload-level recovery**: If a workflow or agent program fails mid-execution, there's no unified checkpoint/restore mechanism.

---

## 2. Constraints

1. Must represent ALL current workload types: chat, completion, embedding, agent, workflow, tool execution, retrieval, evaluation, benchmark, model import, device operation
2. Must support both simple (single model call) and complex (multi-step agent program) workloads
3. Must be serializable (protobuf) for NKI transport
4. Must include enough information for admission control, scheduling, and resource reservation
5. Must not require the kernel to understand specific AI model architectures

---

## 3. Workload IR Definition

### 3.1 WorkloadSpec

```protobuf
message WorkloadSpec {
  // ── Identity ──
  string workload_id = 1;              // Client-assigned UUID v7
  string idempotency_key = 2;          // For safe retry
  uint32 schema_version = 3;           // WorkloadSpec schema version

  // ── Principal & Namespace ──
  string principal_id = 4;
  string namespace = 5;

  // ── Goal ──
  string goal = 6;                     // Human-readable goal (for debugging/audit)
  WorkloadType workload_type = 7;

  // ── Execution ──
  ExecutionGraph execution_graph = 8;  // The actual work to do

  // ── Requirements ──
  ModelRequirements model_requirements = 9;
  CapabilityRequirements capability_requirements = 10;
  DeviceRequirements device_requirements = 11;
  QualityRequirements quality_requirements = 12;
  SecurityRequirements security_requirements = 13;
  ResourceRequirements resource_requirements = 14;

  // ── Budgets ──
  LatencySLO latency_slo = 15;
  int64 deadline_us = 16;              // Absolute deadline (Unix microseconds)
  EnergyBudget energy_budget = 17;
  CostBudget cost_budget = 18;

  // ── Policies ──
  CheckpointPolicy checkpoint_policy = 19;
  CancellationPolicy cancellation_policy = 20;
  RetryPolicy retry_policy = 21;
  FallbackPolicy fallback_policy = 22;

  // ── Output ──
  OutputContract output_contract = 23;
}
```

### 3.2 WorkloadType

```protobuf
enum WorkloadType {
  WORKLOAD_TYPE_UNSPECIFIED = 0;
  CHAT = 1;                    // Multi-turn conversation turn
  COMPLETION = 2;              // Single text completion
  STRUCTURED_OUTPUT = 3;       // JSON/typed output generation
  EMBEDDING = 4;               // Text/image embedding
  RERANK = 5;                  // Document reranking
  VISION = 6;                  // Image/video understanding
  SPEECH = 7;                  // Speech-to-text or text-to-speech
  MODEL_INFERENCE = 8;         // Raw model inference
  AGENT_PROGRAM = 9;           // Multi-step agent execution
  WORKFLOW = 10;               // DAG-based workflow
  TOOL_EXECUTION = 11;         // Single tool call
  RETRIEVAL = 12;              // Knowledge retrieval
  EVALUATION = 13;             // Model/judge evaluation
  BATCH = 14;                  // Batch inference
  DEVICE_OPERATION = 15;       // Hardware device operation
  MODEL_IMPORT = 16;           // Import/convert a model
  MODEL_COMPILE = 17;          // Compile/optimize a model
  BENCHMARK = 18;              // Benchmark execution
  KERNEL_COMMAND = 19;         // Kernel administrative command
}
```

### 3.3 ExecutionGraph

```protobuf
message ExecutionGraph {
  repeated PhaseNode nodes = 1;
  repeated PhaseEdge edges = 2;
  string entry_node_id = 3;
}

message PhaseNode {
  string node_id = 1;
  PhaseType phase_type = 2;
  PhaseConfig config = 3;          // Type-specific configuration
  string description = 4;          // Human-readable
}

message PhaseEdge {
  string from_node_id = 1;
  string to_node_id = 2;
  EdgeCondition condition = 3;     // When to follow this edge
}

enum PhaseType {
  PHASE_TYPE_UNSPECIFIED = 0;
  RECEIVE = 1;           // Receive input
  VALIDATE = 2;          // Validate input
  AUTHENTICATE = 3;      // Verify principal
  RESOLVE_CONTEXT = 4;   // Resolve references, retrieve context
  RETRIEVE = 5;          // Retrieve knowledge
  PLAN = 6;              // Create execution plan
  ADMIT = 7;             // Resource admission check
  PLACE = 8;             // Select node/device/engine
  PREPARE = 9;           // Load model, allocate resources
  TOKENIZE = 10;         // Tokenize input
  ENCODE = 11;           // Encode into representation
  PREFILL = 12;          // Prefill KV cache
  DECODE = 13;           // Generate tokens
  TOOL_EXECUTE = 14;     // Execute a tool
  OBSERVE = 15;          // Collect observation
  VERIFY = 16;           // Verify output quality
  REPLAN = 17;           // Revise plan based on observation
  FINALIZE = 18;         // Assemble final output
  COMMIT = 19;           // Commit side effects
  COMPENSATE = 20;       // Rollback side effects
  CHECKPOINT = 21;       // Save state snapshot
}
```

### 3.4 Edge Conditions

```protobuf
message EdgeCondition {
  oneof condition {
    AlwaysCondition always = 1;
    OnSuccessCondition on_success = 2;
    OnFailureCondition on_failure = 3;
    OnOutputMatch on_output = 4;     // Regex or JSON path match
    OnQualityThreshold quality = 5;  // Quality score threshold
    OnApprovalRequired approval = 6; // Human approval required
    OnRetryExhausted retry_exhausted = 7;
  }
}
```

### 3.5 ModelRequirements

```protobuf
message ModelRequirements {
  // Which models are acceptable
  repeated string allowed_model_families = 1;    // e.g., ["claude", "deepseek"]
  repeated string allowed_architectures = 2;     // e.g., ["dense", "moe"]
  repeated string excluded_models = 3;           // Blacklist specific revisions
  string preferred_model = 4;                    // Preferred but not required

  // Resource bounds per model call
  uint64 max_tokens_per_request = 5;
  uint64 min_context_length = 6;
  uint64 max_context_length = 7;

  // Quality thresholds
  double min_quality_score = 8;                  // 0.0–1.0
  bool thinking_required = 9;                    // Extended reasoning
  uint32 min_thinking_budget = 10;               // Minimum thinking tokens

  // Modality
  repeated Modality input_modalities = 11;
  repeated Modality output_modalities = 12;

  // Quantization tolerance
  QuantizationTolerance quantization = 13;
  double max_acceptable_perplexity_increase = 14;

  // Routing hint
  RoutingPreference routing = 15;
}
```

### 3.6 QualityRequirements

```protobuf
message QualityRequirements {
  double minimum_quality = 1;              // 0.0–1.0
  double uncertainty_limit = 2;            // Max acceptable uncertainty
  bool verification_required = 3;          // Must run verifier
  string verifier_model = 4;              // Specific model for verification
  bool evidence_required = 5;             // Must provide evidence for claims
  bool human_review_required = 6;         // Must pass human review
  QualityEscalation escalation = 7;
  repeated string required_benchmarks = 8; // Benchmarks to run
}

message QualityEscalation {
  bool enabled = 1;
  uint32 max_retries = 2;                  // 0 = no retry, N = up to N attempts
  string fallback_model = 3;              // Stronger model if quality insufficient
  string escalation_verifier = 4;         // More rigorous verifier
}
```

### 3.7 ResourceRequirements

```protobuf
message ResourceRequirements {
  // Minimum resources needed
  ResourceVector minimum = 1;

  // Maximum resources allowed
  ResourceVector maximum = 2;

  // Preferred (for scheduling optimization)
  ResourceVector preferred = 3;

  // Priority class
  PriorityClass priority = 4;

  // Preemption policy
  PreemptionPolicy preemption = 5;
}

enum PriorityClass {
  PRIORITY_SYSTEM = 0;       // Kernel operations (highest)
  PRIORITY_INTERACTIVE = 1;  // User-facing requests
  PRIORITY_BATCH = 2;        // Batch jobs
  PRIORITY_BEST_EFFORT = 3;  // Background/experimental
}

enum PreemptionPolicy {
  PREEMPTION_NEVER = 0;
  PREEMPTION_IF_LOWER_PRIORITY = 1;
  PREEMPTION_ALWAYS = 2;
}
```

### 3.8 SecurityRequirements

```protobuf
message SecurityRequirements {
  DataClassification data_classification = 1;
  bool allow_network_access = 2;
  repeated string allowed_hosts = 3;
  bool allow_file_access = 4;
  repeated string allowed_paths = 5;
  bool allow_side_effects = 6;
  bool reversible_side_effects_only = 7;
  bool require_approval = 8;
  string isolation_profile = 9;           // "none", "container", "vm"
  bool audit_all_output = 10;
}
```

---

## 4. Workload Lifecycle (17-State)

```protobuf
enum WorkloadPhase {
  WORKLOAD_CREATED = 0;         // Initial state
  WORKLOAD_VALIDATING = 1;      // Validating WorkloadSpec
  WORKLOAD_VALIDATED = 2;       // Spec is valid
  WORKLOAD_REJECTED = 3;        // Spec is invalid (terminal)
  WORKLOAD_ADMITTED = 4;        // Passed admission control
  WORKLOAD_PLACED = 5;          // Assigned to node/device/engine
  WORKLOAD_PREPARING = 6;       // Loading model, allocating resources
  WORKLOAD_RUNNING = 7;         // Executing phases
  WORKLOAD_QUIESCING = 8;       // Draining, waiting for completion
  WORKLOAD_CHECKPOINTING = 9;   // Saving state snapshot
  WORKLOAD_CHECKPOINTED = 10;   // State saved
  WORKLOAD_RECOVERING = 11;     // Restoring from checkpoint
  WORKLOAD_SUCCEEDED = 12;      // Completed successfully (terminal)
  WORKLOAD_FAILED = 13;         // Failed (terminal)
  WORKLOAD_CANCELLED = 14;      // Cancelled by user (terminal)
  WORKLOAD_LOST = 15;           // Node lost, fate unknown (terminal)
  WORKLOAD_QUARANTINED = 16;    // Suspicious, pending investigation (terminal)
}
```

### 4.1 Valid Transitions

```
CREATED       → VALIDATING, CANCELLED
VALIDATING    → VALIDATED, REJECTED
VALIDATED     → ADMITTED, REJECTED
REJECTED      → (terminal)
ADMITTED      → PLACED, CANCELLED
PLACED        → PREPARING, CANCELLED
PREPARING     → RUNNING, FAILED, CANCELLED
RUNNING       → QUIESCING, CHECKPOINTING, SUCCEEDED, FAILED, CANCELLED, LOST
QUIESCING     → CHECKPOINTING, SUCCEEDED, FAILED, CANCELLED
CHECKPOINTING → CHECKPOINTED, FAILED
CHECKPOINTED  → RUNNING, RECOVERING, CANCELLED
RECOVERING    → RUNNING, FAILED, CANCELLED
SUCCEEDED     → (terminal)
FAILED        → RECOVERING, QUARANTINED (recovery via new workload)
CANCELLED     → (terminal)
LOST          → RECOVERING (recovery via new workload)
QUARANTINED   → (terminal)
```

---

## 5. Policies

### 5.1 CheckpointPolicy

```protobuf
message CheckpointPolicy {
  bool enabled = 1;
  CheckpointStrategy strategy = 2;
  uint32 min_interval_seconds = 3;      // Between checkpoints
  uint32 max_checkpoints = 4;           // 0 = unlimited
  uint32 retention_seconds = 5;         // How long to keep
}

enum CheckpointStrategy {
  CHECKPOINT_NONE = 0;
  CHECKPOINT_BEFORE_RISKY_PHASE = 1;   // Before tool execution, network call
  CHECKPOINT_PERIODIC = 2;             // Every N seconds
  CHECKPOINT_AFTER_EVERY_PHASE = 3;    // Every phase boundary
}
```

### 5.2 CancellationPolicy

```protobuf
message CancellationPolicy {
  bool cancellable = 1;                // Can user cancel?
  bool graceful = 2;                   // Wait for current phase to finish?
  uint32 grace_period_seconds = 3;     // Max time to wait
  repeated string uncancellable_phases = 4; // Phases that must complete
}
```

### 5.3 RetryPolicy

```protobuf
message RetryPolicy {
  uint32 max_retries = 1;
  uint32 initial_backoff_ms = 2;
  uint32 max_backoff_ms = 3;
  double backoff_multiplier = 4;
  repeated string retryable_errors = 5;  // Error codes worth retrying
  bool retry_on_timeout = 6;
}
```

### 5.4 FallbackPolicy

```protobuf
message FallbackPolicy {
  bool enabled = 1;
  repeated FallbackStep steps = 2;
}

message FallbackStep {
  string condition = 1;        // e.g., "quality_below(0.7)", "timeout", "model_unavailable"
  string action = 2;           // e.g., "switch_model", "reduce_context", "skip_verification"
  string target = 3;           // Action-specific parameter
}
```

---

## 6. OutputContract

```protobuf
message OutputContract {
  OutputFormat format = 1;
  string json_schema = 2;              // For STRUCTURED_OUTPUT
  uint32 max_output_tokens = 3;
  bool include_reasoning = 4;          // Include thinking traces
  bool include_evidence = 5;           // Include verification evidence
  bool include_tool_traces = 6;        // Include tool call/results
  bool include_metrics = 7;            // Include performance metrics
  repeated string redact_patterns = 8; // Patterns to redact from output
}
```

---

## 7. Phase Declaration

Each phase in the execution graph MUST declare:

```protobuf
message PhaseConfig {
  // Inputs and outputs
  repeated string input_artifacts = 1;
  repeated string output_artifacts = 2;

  // Where can this phase run?
  repeated string allowed_devices = 3;  // Empty = any
  repeated string allowed_engines = 4;  // Empty = any

  // Resource needs
  ResourceVector estimated_resources = 5;

  // Behavioral properties
  bool is_idempotent = 6;
  bool is_cancellable = 7;
  bool is_retryable = 8;
  bool is_migratable = 9;
  bool is_checkpointable = 10;

  // Side effects
  bool has_side_effects = 11;
  string compensation_phase_id = 12;     // Node to run if rollback needed

  // Timing
  uint32 timeout_seconds = 13;
  uint32 estimated_duration_ms = 14;

  // Quality
  string quality_verifier_phase_id = 15; // Node to run for verification
}
```

---

## 8. Example WorkloadSpecs

### 8.1 Simple Chat

```json
{
  "workload_type": "CHAT",
  "goal": "Answer user question about weather",
  "execution_graph": {
    "nodes": [
      {"node_id": "1", "phase_type": "RECEIVE"},
      {"node_id": "2", "phase_type": "RESOLVE_CONTEXT"},
      {"node_id": "3", "phase_type": "TOKENIZE"},
      {"node_id": "4", "phase_type": "PREFILL"},
      {"node_id": "5", "phase_type": "DECODE"},
      {"node_id": "6", "phase_type": "FINALIZE"}
    ],
    "edges": [
      {"from": "1", "to": "2"},
      {"from": "2", "to": "3"},
      {"from": "3", "to": "4"},
      {"from": "4", "to": "5"},
      {"from": "5", "to": "6"}
    ],
    "entry_node_id": "1"
  },
  "model_requirements": {
    "allowed_model_families": ["claude", "deepseek"],
    "max_tokens_per_request": 4096,
    "min_context_length": 8000
  },
  "quality_requirements": {
    "minimum_quality": 0.7
  },
  "latency_slo": {
    "max_ttft_ms": 500,
    "max_total_ms": 30000
  }
}
```

### 8.2 Agent with Tool and Verification

```json
{
  "workload_type": "AGENT_PROGRAM",
  "goal": "Analyze code repository and generate report",
  "execution_graph": {
    "nodes": [
      {"node_id": "plan", "phase_type": "PLAN"},
      {"node_id": "retrieve", "phase_type": "RETRIEVE"},
      {"node_id": "analyze", "phase_type": "DECODE"},
      {"node_id": "run_tests", "phase_type": "TOOL_EXECUTE", "config": {"has_side_effects": true}},
      {"node_id": "verify", "phase_type": "VERIFY"},
      {"node_id": "replan", "phase_type": "REPLAN"},
      {"node_id": "finalize", "phase_type": "FINALIZE"}
    ],
    "edges": [
      {"from": "plan", "to": "retrieve"},
      {"from": "retrieve", "to": "analyze"},
      {"from": "analyze", "to": "run_tests"},
      {"from": "run_tests", "to": "verify"},
      {"from": "verify", "to": "finalize", "condition": {"on_success": {}}},
      {"from": "verify", "to": "replan", "condition": {"quality": {"threshold": 0.8}}},
      {"from": "replan", "to": "analyze"}
    ],
    "entry_node_id": "plan"
  },
  "checkpoint_policy": {
    "enabled": true,
    "strategy": "CHECKPOINT_BEFORE_RISKY_PHASE"
  },
  "security_requirements": {
    "allow_file_access": true,
    "allowed_paths": ["/workspace/project"],
    "allow_side_effects": true,
    "reversible_side_effects_only": false,
    "require_approval": true
  }
}
```

---

## 9. Workload Compilation

Product layers MUST compile their requests into WorkloadSpec before submitting to the kernel:

```
User Input (desktop/cli/sdk)
    │
    ▼
┌──────────────────────────┐
│  WorkloadCompiler        │  ← Product-layer responsibility
│  - Parse intent          │
│  - Select workload type  │
│  - Build execution graph │
│  - Estimate resources    │
│  - Set quality/SLO       │
└──────────┬───────────────┘
           │ WorkloadSpec
           ▼
┌──────────────────────────┐
│  NKI: SubmitWorkload     │  ← Kernel entry point
│  - Validate              │
│  - Admit                 │
│  - Schedule              │
│  - Execute               │
└──────────────────────────┘
```

---

## 10. Validation

### 10.1 Schema Tests

- Every workload type has at least one valid example WorkloadSpec
- Invalid transitions are rejected by WorkloadSpec validation
- Missing required fields produce clear error messages
- Conflicting requirements (e.g., `allow_side_effects=false` + `TOOL_EXECUTE` phase) are caught

### 10.2 Compilation Tests

- `ChatRequest` → `WorkloadSpec { CHAT }` preserves all parameters
- `AgentProgram` → `WorkloadSpec { AGENT_PROGRAM }` preserves execution graph
- `WorkflowDefinition` → `WorkloadSpec { WORKFLOW }` preserves DAG structure

### 10.3 Execution Tests

- Simple chat workload executes through full lifecycle
- Agent workload with tool approval checkpoints and resumes
- Failed workload with retry policy retries up to max
- Cancelled workload enters CANCELLED phase, not RUNNING

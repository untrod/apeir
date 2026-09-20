# RFC-0004: Nous Kernel Interface (NKI) v1

- **Status:** Draft
- **Date:** 2026-08-04
- **Author:** Nous Kernel Architecture
- **Depends on:** RFC-0001, RFC-0002, RFC-0003

---

## 1. Problem

The current Nous Runtime has no stable, versioned kernel interface:

1. **Ad-hoc HTTP API**: REST endpoints in `api/routes.py` evolved organically; no versioning; no formal contract.
2. **Multiple transport protocols**: HTTP REST, WebSocket, Tauri commands — each with different auth, error handling, and serialization.
3. **No feature negotiation**: Client and server cannot discover each other's capabilities.
4. **No idempotency guarantees**: Retrying a request may cause duplicate side effects.
5. **No formal deprecation policy**: API changes can silently break clients.
6. **Python-only**: No C ABI, no Rust SDK, no cross-language contract.

---

## 2. Constraints

1. Must support local (same-machine) and remote (network) clients
2. Must be versioned from day one (NKI v1)
3. Must support synchronous (request-response) and streaming (events, tokens) patterns
4. Must be language-neutral (protobuf IDL as source of truth)
5. Must support existing Python, TypeScript, and Rust consumers
6. Must coexist with existing HTTP API during migration

---

## 3. NKI Design

### 3.1 Transport Layers

| Transport | Use Case | Protocol |
|-----------|----------|----------|
| Unix Domain Socket | Linux local control plane | Protobuf + length-prefixed frames |
| Windows Named Pipe | Windows local control plane | Protobuf + length-prefixed frames |
| QUIC | Remote node communication | Protobuf + mTLS |
| Shared Memory | Data plane (weights, KV cache) | memfd / DMA-BUF |
| HTTP/2 | Legacy compatibility | Protobuf-JSON + mTLS |

### 3.2 Request Envelope

Every NKI request is wrapped in:

```protobuf
message NKIRequest {
  // Unique request identifier (UUID v7)
  string request_id = 1;

  // Idempotency key — same key = same result, safe to retry
  string idempotency_key = 2;

  // NKI schema version (semver major)
  uint32 nki_version = 3;

  // Authenticated principal
  string principal_id = 4;

  // Target namespace
  string namespace = 5;

  // Absolute deadline for this request (Unix microseconds)
  int64 deadline_us = 6;

  // W3C TraceContext for distributed tracing
  string traceparent = 7;
  string tracestate = 8;

  // Feature flags requested by client
  repeated string feature_flags = 9;

  // The actual method call
  oneof method {
    // Workload management
    SubmitWorkloadRequest submit_workload = 10;
    GetWorkloadRequest get_workload = 11;
    ListWorkloadsRequest list_workloads = 12;
    CancelWorkloadRequest cancel_workload = 13;
    PauseWorkloadRequest pause_workload = 14;
    ResumeWorkloadRequest resume_workload = 15;

    // Admission & resources
    AdmitWorkloadRequest admit_workload = 16;
    ReserveResourcesRequest reserve_resources = 17;
    ReleaseResourcesRequest release_resources = 18;

    // Model management
    RegisterModelRequest register_model = 19;
    ValidateModelRequest validate_model = 20;
    LoadModelRequest load_model = 21;
    UnloadModelRequest unload_model = 22;

    // Engine management
    RegisterEngineRequest register_engine = 23;
    ProbeEngineRequest probe_engine = 24;
    ListEnginesRequest list_engines = 25;

    // Device management
    RegisterDeviceRequest register_device = 26;
    ProbeDeviceRequest probe_device = 27;
    ListDevicesRequest list_devices = 28;

    // State & recovery
    CreateCheckpointRequest create_checkpoint = 29;
    RestoreCheckpointRequest restore_checkpoint = 30;

    // Observability
    WatchEventsRequest watch_events = 31;
    GetTraceRequest get_trace = 32;
    GetMetricsRequest get_metrics = 33;

    // Health
    HealthCheckRequest health_check = 34;
  }
}
```

### 3.3 Response Envelope

```protobuf
message NKIResponse {
  // Echoes the request_id
  string request_id = 1;

  // NKI schema version (server's version)
  uint32 nki_version = 2;

  // Server timestamp
  int64 server_timestamp_us = 3;

  // Trace ID for correlation
  string trace_id = 4;

  // Outcome
  oneof outcome {
    SuccessResult success = 10;
    ErrorResult error = 11;
  }
}

message SuccessResult {
  oneof result {
    // ... type-specific response messages
    SubmitWorkloadResponse submit_workload = 1;
    GetWorkloadResponse get_workload = 2;
    // ...
  }
}

message ErrorResult {
  // Stable error code
  ErrorCode code = 1;

  // Human-readable message
  string message = 2;

  // Which phase failed
  string failed_phase = 3;

  // Original cause (if wrapped)
  string cause = 4;

  // Retry hint
  RetryHint retry = 5;

  // Additional error details (type-specific)
  google.protobuf.Any details = 6;
}
```

### 3.4 Error Codes

```protobuf
enum ErrorCode {
  // Generic
  ERROR_UNKNOWN = 0;
  ERROR_INVALID_REQUEST = 1;
  ERROR_NOT_FOUND = 2;
  ERROR_ALREADY_EXISTS = 3;
  ERROR_PERMISSION_DENIED = 4;
  ERROR_UNAUTHENTICATED = 5;
  ERROR_RESOURCE_EXHAUSTED = 6;
  ERROR_FAILED_PRECONDITION = 7;
  ERROR_ABORTED = 8;
  ERROR_OUT_OF_RANGE = 9;
  ERROR_NOT_IMPLEMENTED = 10;
  ERROR_INTERNAL = 11;
  ERROR_UNAVAILABLE = 12;
  ERROR_DATA_LOSS = 13;
  ERROR_DEADLINE_EXCEEDED = 14;

  // Kernel-specific
  ERROR_WORKLOAD_REJECTED = 20;
  ERROR_WORKLOAD_CANCELLED = 21;
  ERROR_WORKLOAD_LOST = 22;
  ERROR_WORKLOAD_QUARANTINED = 23;
  ERROR_WORKLOAD_CONFLICT = 24;           // Generation mismatch

  ERROR_RESOURCE_INSUFFICIENT = 30;
  ERROR_LEASE_EXPIRED = 31;
  ERROR_LEASE_CONFLICT = 32;

  ERROR_MODEL_NOT_FOUND = 40;
  ERROR_MODEL_INCOMPATIBLE = 41;
  ERROR_MODEL_NOT_LOADED = 42;
  ERROR_MODEL_VALIDATION_FAILED = 43;
  ERROR_MODEL_SECURITY_BLOCKED = 44;

  ERROR_ENGINE_NOT_FOUND = 50;
  ERROR_ENGINE_INCOMPATIBLE = 51;
  ERROR_ENGINE_UNHEALTHY = 52;
  ERROR_ENGINE_TIMEOUT = 53;

  ERROR_DEVICE_NOT_FOUND = 60;
  ERROR_DEVICE_INCOMPATIBLE = 61;
  ERROR_DEVICE_UNHEALTHY = 62;
  ERROR_DEVICE_OUT_OF_MEMORY = 63;

  ERROR_BACKEND_UNAVAILABLE = 70;
  ERROR_BACKEND_INCOMPATIBLE = 71;

  ERROR_NOT_SUPPORTED = 80;

  ERROR_SECURITY_POLICY = 90;
  ERROR_CAPABILITY_DENIED = 91;
  ERROR_ISOLATION_FAILED = 92;
}
```

### 3.5 Retry Hints

```protobuf
message RetryHint {
  bool retryable = 1;
  uint32 recommended_delay_ms = 2;
  uint32 max_retries = 3;
  RetryStrategy strategy = 4;
}

enum RetryStrategy {
  RETRY_IMMEDIATE = 0;       // Safe to retry immediately
  RETRY_BACKOFF = 1;         // Use exponential backoff
  RETRY_AFTER = 2;           // Wait for server-specified duration
  RETRY_NEW_IDEMPOTENCY = 3; // Use a new idempotency key
  RETRY_NEVER = 4;           // Do not retry; request was processed
}
```

---

## 4. Core API Methods

### 4.1 Workload Management

```protobuf
message SubmitWorkloadRequest {
  WorkloadSpec workload = 1;       // As defined in RFC-0003
}

message SubmitWorkloadResponse {
  string workload_id = 1;
  WorkloadPhase phase = 2;
  string resource_version = 3;
}

message GetWorkloadRequest {
  string workload_id = 1;
}

message GetWorkloadResponse {
  Workload workload = 1;
}

message ListWorkloadsRequest {
  string namespace = 1;
  repeated LabelSelector filters = 2;
  uint32 page_size = 3;
  string page_token = 4;
}

message ListWorkloadsResponse {
  repeated Workload workloads = 1;
  string next_page_token = 2;
}

message CancelWorkloadRequest {
  string workload_id = 1;
  string reason = 2;
  bool force = 3;                  // Skip graceful shutdown
}

message CancelWorkloadResponse {
  string workload_id = 1;
  WorkloadPhase phase = 2;
}

message PauseWorkloadRequest {
  string workload_id = 1;
}

message PauseWorkloadResponse {
  string workload_id = 1;
  WorkloadPhase phase = 2;
}

message ResumeWorkloadRequest {
  string workload_id = 1;
}

message ResumeWorkloadResponse {
  string workload_id = 1;
  WorkloadPhase phase = 2;
}
```

### 4.2 Admission & Resources

```protobuf
message AdmitWorkloadRequest {
  string workload_id = 1;
}

message AdmitWorkloadResponse {
  bool admitted = 1;
  string rejection_reason = 2;
  repeated string missing_requirements = 3;
  ResourceVector available = 4;
  ResourceVector required = 5;
}

message ReserveResourcesRequest {
  string workload_id = 1;
  ResourceVector resources = 2;
  string preferred_node_id = 3;
  string preferred_device_id = 4;
}

message ReserveResourcesResponse {
  ResourceLease lease = 1;
}

message ReleaseResourcesRequest {
  string lease_id = 1;
}

message ReleaseResourcesResponse {
  bool released = 1;
}
```

### 4.3 Model Management

```protobuf
message RegisterModelRequest {
  ModelPackageSpec model = 1;
}

message RegisterModelResponse {
  string model_id = 1;
  ModelLifecyclePhase phase = 2;
}

message ValidateModelRequest {
  string model_id = 1;
}

message ValidateModelResponse {
  bool valid = 1;
  repeated string errors = 2;
  repeated string warnings = 3;
}

message LoadModelRequest {
  string model_id = 1;
  string engine_id = 2;
  string device_id = 3;
  LoadOptions options = 4;
}

message LoadModelResponse {
  string instance_id = 1;
  ModelLifecyclePhase phase = 2;
}

message UnloadModelRequest {
  string instance_id = 1;
}

message UnloadModelResponse {
  bool unloaded = 1;
}
```

### 4.4 Engine Management

```protobuf
message RegisterEngineRequest {
  EngineSpec engine = 1;
  string process_id = 2;
}

message RegisterEngineResponse {
  string engine_id = 1;
}

message ProbeEngineRequest {
  string engine_id = 1;
}

message ProbeEngineResponse {
  EngineStatus status = 1;
}

message ListEnginesRequest {
  string namespace = 1;
}

message ListEnginesResponse {
  repeated Engine engines = 1;
}
```

### 4.5 Device Management

```protobuf
message RegisterDeviceRequest {
  DeviceSpec device = 1;
}

message RegisterDeviceResponse {
  string device_id = 1;
}

message ProbeDeviceRequest {
  string device_id = 1;
}

message ProbeDeviceResponse {
  DeviceStatus status = 1;
}

message ListDevicesRequest {
  string namespace = 1;
}

message ListDevicesResponse {
  repeated Device devices = 1;
}
```

### 4.6 State & Recovery

```protobuf
message CreateCheckpointRequest {
  string workload_id = 1;
  string description = 2;
}

message CreateCheckpointResponse {
  Checkpoint checkpoint = 1;
}

message RestoreCheckpointRequest {
  string checkpoint_id = 1;
}

message RestoreCheckpointResponse {
  string workload_id = 1;
  WorkloadPhase phase = 2;
}
```

### 4.7 Observability

```protobuf
message WatchEventsRequest {
  string namespace = 1;
  repeated string event_types = 2;  // Filter by event type
  string from_resource_version = 3; // Resume from this version
  bool follow = 4;                  // Keep streaming new events
}

message WatchEventsResponse {
  repeated Event events = 1;
  string resource_version = 2;
}

message GetTraceRequest {
  string trace_id = 1;
}

message GetTraceResponse {
  ExecutionTimeline timeline = 1;
}

message GetMetricsRequest {
  string namespace = 1;
  string metric_name = 2;
  int64 start_us = 3;
  int64 end_us = 4;
}

message GetMetricsResponse {
  repeated MetricPoint points = 1;
}
```

### 4.8 Health

```protobuf
message HealthCheckRequest {
  bool deep = 1;  // Deep health check includes engine/device connectivity
}

message HealthCheckResponse {
  bool healthy = 1;
  string version = 2;
  int64 uptime_seconds = 3;
  map<string, ComponentHealth> components = 4;
}

message ComponentHealth {
  bool healthy = 1;
  string message = 2;
  int64 last_checked_us = 3;
}
```

---

## 5. Streaming

### 5.1 Token Streaming

Token streaming uses a server-streaming pattern over the same transport:

```
Client → SubmitWorkload (stream = true)
Server → WorkloadEvent { phase: RUNNING }
Server → TokenEvent { token: "Hello" }
Server → TokenEvent { token: " world" }
Server → TokenEvent { token: "!" }
Server → WorkloadEvent { phase: SUCCEEDED }
```

```protobuf
message TokenEvent {
  string workload_id = 1;
  string run_id = 2;
  uint32 token_index = 3;
  string token_text = 4;
  float log_prob = 5;
  bool is_final = 6;
}
```

### 5.2 Event Streaming

```
Client → WatchEvents (follow = true)
Server → WatchEventsResponse { events: [...] }
Server → WatchEventsResponse { events: [...] }
... (continuous)
```

---

## 6. Feature Negotiation

```protobuf
message FeatureFlags {
  bool supports_streaming = 1;
  bool supports_cancellation = 2;
  bool supports_checkpoint = 3;
  bool supports_multi_node = 4;
  bool supports_disaggregated_prefill = 5;
  bool supports_kv_sharing = 6;
  bool supports_model_compilation = 7;
  uint32 max_nki_version = 8;
}
```

Client sends its supported features in `NKIRequest.feature_flags`. Server responds with its capabilities in `NKIResponse` headers. If client requests a feature the server doesn't support, the server ignores the flag (never errors on unsupported features).

---

## 7. Transport Details

### 7.1 Unix Domain Socket (Linux)

- Path: `/run/nous/nousd.sock`
- Framing: 4-byte big-endian length prefix + protobuf message
- Auth: Peer credentials (SO_PEERCRED) + capabilities file at `/run/nous/authorized_principals`

### 7.2 Windows Named Pipe

- Path: `\\.\pipe\nous\nousd`
- Framing: 4-byte little-endian length prefix + protobuf message
- Auth: Named Pipe ACL + principal token in request envelope

### 7.3 Remote QUIC

- Port: 8771 (configurable)
- TLS: mTLS with Ed25519 certificates
- Framing: QUIC stream per request; bidirectional for streaming
- Auth: Certificate principal + request envelope principal

---

## 8. C ABI (for Engine and Device Adapters)

For performance-critical paths (engine inference, device memory transfer), NKI provides a stable C ABI:

```c
// nki_v1.h — Stable C ABI for NKI v1

typedef struct NKIHandle NKIHandle;
typedef struct NKIError NKIError;
typedef struct NKIWorkload NKIWorkload;
typedef struct NKIModel NKIModel;
typedef struct NKIEngine NKIEngine;
typedef struct NKIDevice NKIDevice;
typedef struct NKILease NKILease;

// Connection lifecycle
NKIHandle* nki_connect(const char* endpoint, NKIError* error);
void nki_disconnect(NKIHandle* handle);
int nki_is_healthy(NKIHandle* handle);

// Workload management
NKIWorkload* nki_submit_workload(NKIHandle* h, const uint8_t* spec, size_t spec_len, NKIError* error);
NKIWorkload* nki_get_workload(NKIHandle* h, const char* workload_id, NKIError* error);
int nki_cancel_workload(NKIHandle* h, const char* workload_id, const char* reason, NKIError* error);

// Model management
NKIModel* nki_register_model(NKIHandle* h, const uint8_t* manifest, size_t manifest_len, NKIError* error);
int nki_load_model(NKIHandle* h, const char* model_id, const char* engine_id, NKIError* error);
int nki_unload_model(NKIHandle* h, const char* model_id, NKIError* error);

// Engine management
NKIEngine* nki_register_engine(NKIHandle* h, const uint8_t* spec, size_t spec_len, NKIError* error);
int nki_engine_health(NKIHandle* h, const char* engine_id, NKIError* error);

// Device management
NKIDevice* nki_register_device(NKIHandle* h, const uint8_t* spec, size_t spec_len, NKIError* error);

// Resource management
NKILease* nki_reserve_resources(NKIHandle* h, const uint8_t* request, size_t request_len, NKIError* error);
int nki_release_resources(NKIHandle* h, const char* lease_id, NKIError* error);

// Checkpoint
int nki_create_checkpoint(NKIHandle* h, const char* workload_id, NKIError* error);
NKIWorkload* nki_restore_checkpoint(NKIHandle* h, const char* checkpoint_id, NKIError* error);

// Error handling
const char* nki_error_message(NKIError* error);
int nki_error_code(NKIError* error);
void nki_error_free(NKIError* error);

// Memory management
void nki_workload_free(NKIWorkload* w);
void nki_model_free(NKIModel* m);
void nki_engine_free(NKIEngine* e);
void nki_device_free(NKIDevice* d);
void nki_lease_free(NKILease* l);
```

---

## 9. Python Bindings

Auto-generated from protobuf IDL:

```python
# nous_kernel.nki — Auto-generated Python client for NKI v1

from nous_kernel.nki import NKIClient, NKIError
from nous_kernel.types import WorkloadSpec, Workload, ModelPackage, Engine, Device

async with NKIClient.connect("unix:///run/nous/nousd.sock") as client:
    # Submit a workload
    workload = await client.submit_workload(
        WorkloadSpec(
            workload_type="CHAT",
            goal="Answer user question",
            execution_graph=simple_chat_graph(),
            model_requirements=ModelRequirements(
                allowed_model_families=["claude"],
                max_tokens_per_request=4096,
            ),
        )
    )

    # Stream tokens
    async for event in client.watch_events(workload.uid, follow=True):
        if event.HasField("token"):
            print(event.token.text, end="", flush=True)
        if event.workload_phase == "SUCCEEDED":
            break

    # Get final result
    result = await client.get_workload(workload.uid)
    print(f"\nDone: {result.status.phase}")
```

---

## 10. Validation

### 10.1 Contract Tests

- Every NKI method has a contract test: request → expected response
- Idempotency: same `idempotency_key` → same result (no duplicate workload)
- Generation conflict: update with stale generation → `ERROR_WORKLOAD_CONFLICT`
- Deadline exceeded: request past deadline → `ERROR_DEADLINE_EXCEEDED`

### 10.2 Transport Tests

- Unix Domain Socket: connect, request, response, disconnect
- Named Pipe: connect, request, response, disconnect
- QUIC: mTLS handshake, request, response, stream
- Feature negotiation: client sends flags, server responds with supported

### 10.3 Compatibility Tests

- NKI v1 client → NKI v1 server: full compatibility
- NKI v1 client → NKI v2 server: v1 methods work, v2 methods return NOT_SUPPORTED
- Old HTTP API → NKI adapter → nousd: existing HTTP endpoints still work

### 10.4 C ABI Tests

- C program links against `libnki.so` / `nki.dll`
- Round-trip: C → submit workload → get workload → same data
- Error propagation: invalid request → error code + message via C ABI

### 10.5 Python Binding Tests

- `NKIClient.connect()` works with all transport types
- Auto-generated types match protobuf schema
- Async streaming works (tokens, events)
- Existing Python tests pass when run against NKI (via compatibility layer)

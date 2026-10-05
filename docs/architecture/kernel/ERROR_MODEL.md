# Nous Kernel — Unified Error Model

> RC4 Kernel Closure
> Date: 2026-08-04

## Error Structure

Every error returned by the Nous Kernel follows this structure:

```json
{
  "code": "ERROR_RESOURCE_INSUFFICIENT",
  "category": "RESOURCE",
  "message": "VRAM: need 8589934592 bytes, have 4194304000 bytes",
  "component": "admission_controller",
  "phase": "ADMIT",
  "retryable": false,
  "recoverable": false,
  "user_action": "Free up GPU memory by unloading another model or use a smaller model",
  "cause": "",
  "trace_id": "trace-abc123",
  "workload_id": "wl-def456",
  "details": {
    "required_vram": 8589934592,
    "available_vram": 4194304000
  }
}
```

## Error Codes

### Validation Errors (4xx equivalent)

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_INVALID_REQUEST` | VALIDATION | No | Request is malformed or missing required fields |
| `ERROR_SCHEMA_INCOMPATIBLE` | VALIDATION | No | WorkloadSpec schema version not supported |
| `ERROR_INVALID_ARGUMENT` | VALIDATION | No | Specific field value is invalid |
| `ERROR_ALREADY_EXISTS` | VALIDATION | No | Resource already exists (idempotency key collision) |

### Authentication/Authorization Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_AUTHENTICATION_FAILED` | AUTH | No | Principal credentials invalid or expired |
| `ERROR_PERMISSION_DENIED` | AUTH | No | Principal lacks required permission |
| `ERROR_UNAUTHENTICATED` | AUTH | No | No credentials provided |

### Governance Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_GOVERNANCE_DENIED` | GOVERNANCE | No | Side effect or capability not approved |
| `ERROR_SECURITY_POLICY` | GOVERNANCE | No | Security policy violation |
| `ERROR_WORKLOAD_REJECTED` | GOVERNANCE | No | Workload rejected by admission |

### Resource Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_RESOURCE_INSUFFICIENT` | RESOURCE | Yes (wait) | Not enough resources now, may become available |
| `ERROR_RESOURCE_EXHAUSTED` | RESOURCE | No | System capacity permanently exceeded |
| `ERROR_LEASE_EXPIRED` | RESOURCE | No | Resource lease has expired |
| `ERROR_DEVICE_OUT_OF_MEMORY` | RESOURCE | Yes (wait) | Device memory full, may free up |

### Execution Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_DEADLINE_EXCEEDED` | EXECUTION | No | Workload deadline passed before completion |
| `ERROR_EXECUTION_FAILED` | EXECUTION | Yes | Engine or phase execution failed |
| `ERROR_FAILED_PRECONDITION` | EXECUTION | No | Workload in wrong phase for operation |
| `ERROR_ENGINE_UNAVAILABLE` | EXECUTION | Yes | Engine not reachable or unhealthy |
| `ERROR_MODEL_INCOMPATIBLE` | EXECUTION | No | Model doesn't support required features |
| `ERROR_DEVICE_UNAVAILABLE` | EXECUTION | Yes | Device not reachable |

### State Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_STATE_CONFLICT` | STATE | Yes | CAS failure — state was modified concurrently |
| `ERROR_DATA_CORRUPTION` | STATE | No | Journal checksum mismatch detected |
| `ERROR_LEASE_CONFLICT` | STATE | Yes | Lease generation mismatch |

### Recovery Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_CHECKPOINT_FAILED` | RECOVERY | Yes | Could not create checkpoint |
| `ERROR_RECOVERY_FAILED` | RECOVERY | Yes | Could not recover from journal |

### Capability Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_NOT_SUPPORTED` | CAPABILITY | No | Operation valid but not supported by this engine/device |
| `ERROR_NOT_IMPLEMENTED` | CAPABILITY | No | Operation defined but not yet implemented |

### System Errors

| Code | Category | Retryable | Meaning |
|------|----------|-----------|---------|
| `ERROR_INTERNAL` | SYSTEM | Yes | Unexpected internal error |
| `ERROR_UNAVAILABLE` | SYSTEM | Yes | Service temporarily unavailable |
| `ERROR_NOT_FOUND` | SYSTEM | No | Requested resource not found |

## Error Categories

| Category | Description | Default Behavior |
|----------|-------------|-----------------|
| VALIDATION | Request is invalid | Reject immediately, no retry |
| AUTH | Authentication or authorization failed | Reject immediately |
| GOVERNANCE | Policy or governance denial | Reject immediately |
| RESOURCE | Resource constraints | May retry after waiting |
| EXECUTION | Execution failure | May retry with backoff |
| STATE | State inconsistency | May retry with CAS |
| RECOVERY | Recovery or checkpoint failure | May retry |
| CAPABILITY | Feature not available | Return to caller |
| SYSTEM | Internal system error | Retry with backoff |

## Client Integration

### CLI
```
$ nous run "hello"
Error: [ERROR_RESOURCE_INSUFFICIENT] VRAM: need 8GB, have 4GB
  Action: Free up GPU memory or use a smaller model
  Trace: trace-abc123
```

### HTTP API
```json
{
  "error": {
    "code": "ERROR_RESOURCE_INSUFFICIENT",
    "message": "VRAM: need 8589934592 bytes, have 4194304000 bytes",
    "user_action": "Free up GPU memory by unloading another model",
    "trace_id": "trace-abc123"
  }
}
```

### Desktop
```
┌─────────────────────────────────┐
│ ⚠ Resource Exhausted            │
│                                 │
│ Not enough GPU memory.          │
│ Need: 8.0 GB                    │
│ Have: 3.9 GB                    │
│                                 │
│ [Unload Models] [Try Smaller]   │
│                                 │
│ Trace: trace-abc123             │
└─────────────────────────────────┘
```

## Anti-Patterns (Prohibited)

These error patterns must NOT appear in RC4 or later:

```python
# ❌ Generic catch-all
except Exception:
    pass

# ❌ Unmapped internal errors
raise RuntimeError("something went wrong")

# ❌ Different error shapes per endpoint
{"error": "bad request"}
{"message": "something failed", "code": 500}

# ❌ Stack traces in production errors
{"error": "Traceback (most recent call last):\n  File ..."}

# ❌ Leaking internal state
{"error": "SQLite error: database is locked at journal.rs:207"}
```

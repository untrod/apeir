# Relay Protocol Specification v1.0

> Status: Draft — Phase 0.5
> Defines the wire format for Control Plane <-> Node communication

---

## 1. Protocol Overview

The Relay Protocol is the communication layer between the Control Plane and Nodes. It uses a versioned message envelope carried over TLS WebSocket.

```
┌─────────────────────────────────────┐
│         TLS WebSocket (wss://)       │
├─────────────────────────────────────┤
│     ProtocolEnvelope (JSON)          │
├─────────────────────────────────────┤
│  Payload (JSON, schema-validated)    │
└─────────────────────────────────────┘
```

---

## 2. ProtocolEnvelope

### 2.1 Schema

```json
{
  "schema_version": "1.0",
  "protocol_version": "1.0",
  "message_id": "msg_20260713_a1b2c3d4",
  "message_type": "TASK_ASSIGNMENT",
  "source": "control_plane",
  "target": "node_laptop_01",
  "timestamp": "2026-07-13T10:00:00Z",
  "correlation_id": "corr_20260713_e5f6g7h8",
  "idempotency_key": "idem_20260713_i9j0k1l2",
  "sequence_number": 42,
  "deadline": "2026-07-13T10:05:00Z",
  "payload": {},
  "signature": "hmac_sha256_hex..."
}
```

### 2.2 Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | Yes | Schema version for THIS envelope format ("1.0") |
| `protocol_version` | string | Yes | Protocol version negotiated at session start ("1.0") |
| `message_id` | string | Yes | Globally unique message ID. Format: `msg_{YYYYMMDD}_{8hex}` |
| `message_type` | string | Yes | One of the defined message types (see §3) |
| `source` | string | Yes | Sender identifier (node_id or "control_plane") |
| `target` | string | Yes | Recipient identifier |
| `timestamp` | string | Yes | UTC ISO-8601 with seconds |
| `correlation_id` | string | No | Links related messages (e.g., task submission -> result) |
| `idempotency_key` | string | Conditional | Required for TASK_SUBMISSION. Unique per submission. |
| `sequence_number` | integer | Conditional | Required for session-scoped messages. Monotonically increasing. |
| `deadline` | string | Conditional | Required for TASK_ASSIGNMENT. UTC ISO-8601. |
| `payload` | object | Yes | Message-type-specific payload (schema-validated) |
| `signature` | string | Yes | HMAC-SHA256 signature of the message (see §5) |

### 2.3 Validation Rules

1. `schema_version` must be a supported version
2. `protocol_version` must match the negotiated session version
3. `message_id` must be unique (duplicate detection within replay window)
4. `message_type` must be a known type
5. `source` and `target` must be non-empty
6. `timestamp` must be within ±30s of server time (clock skew tolerance)
7. `sequence_number` (if present) must be > previous sequence_number (gap detection)
8. `deadline` (if present) must be in the future at time of delivery
9. `payload` must validate against the message type's JSON Schema
10. `signature` must verify against the sender's credential

### 2.4 Size Limits

| Limit | Value |
|---|---|
| Envelope (without payload) | 1 KB max |
| Payload | 1 MB max (configurable) |
| Oversized message | Rejected with ProtocolError before full parsing |

---

## 3. Message Types

### 3.1 Session Messages

#### HELLO
```
Direction: Node -> Control Plane
Purpose: Initial connection, version negotiation, identity presentation
Payload: {node_id, supported_protocol_versions, session_resume_id (optional)}
```

#### WELCOME
```
Direction: Control Plane -> Node
Purpose: Session established, protocol version selected
Payload: {session_id, protocol_version, server_time, heartbeat_interval_ms, liveness_timeout_ms}
```

#### HEARTBEAT
```
Direction: Node -> Control Plane
Purpose: Liveness signal
Payload: {sequence_number, node_health: {status, load, capabilities_healthy}}
Frequency: Every heartbeat_interval_ms (default 15000)
```

#### HEARTBEAT_ACK
```
Direction: Control Plane -> Node
Purpose: Heartbeat acknowledged
Payload: {sequence_number, server_time}
```

#### GOODBYE
```
Direction: Either
Purpose: Clean disconnection
Payload: {reason: "shutdown" | "restart" | "protocol_error"}
```

### 3.2 Pairing Messages

#### PAIRING_REQUEST
```
Direction: Node -> Control Plane
Purpose: Submit pairing code + node identity
Payload: {pairing_code, node_identity: NodeIdentity}
```

#### PAIRING_APPROVAL
```
Direction: Control Plane -> Node
Purpose: Pairing approved, credential issued
Payload: {credential: PairingCredential}
```

#### PAIRING_REJECTION
```
Direction: Control Plane -> Node
Purpose: Pairing rejected
Payload: {reason: "code_expired" | "code_invalid" | "code_replayed" | "node_exists" | "not_authorized"}
```

### 3.3 Task Messages

#### TASK_SUBMISSION
```
Direction: Client -> Control Plane (via HTTP API)
Purpose: Submit a task for execution
Payload: {task_id, capability_id, params, target_node, idempotency_key, deadline, risk_level}
```

#### TASK_ASSIGNMENT
```
Direction: Control Plane -> Node
Purpose: Assign a task to a node
Payload: {task_id, capability_id, params, deadline, sequence_number}
```

#### TASK_ACKNOWLEDGEMENT
```
Direction: Node -> Control Plane
Purpose: Node acknowledges task receipt
Payload: {task_id, accepted: bool, reject_reason (if not accepted)}
```

#### TASK_EVENT
```
Direction: Node -> Control Plane
Purpose: Stream task execution events
Payload: {task_id, event_type: "started" | "progress" | "log" | "artifact_ready", data, timestamp}
```

#### TASK_RESULT
```
Direction: Node -> Control Plane
Purpose: Final task result
Payload: {task_id, status: "completed" | "failed", result, error, artifacts, duration_ms}
```

#### TASK_CANCELLATION
```
Direction: Control Plane -> Node
Purpose: Cancel a running task
Payload: {task_id, reason}
```

### 3.4 Error Message

#### PROTOCOL_ERROR
```
Direction: Either
Purpose: Protocol-level error
Payload: {error_code, error_message, original_message_id (if applicable)}
```

### 3.5 Error Codes

| Code | Name | Description |
|---|---|---|
| 0 | OK | Success |
| 1 | AUTH_FAILED | Authentication failed |
| 2 | VERSION_MISMATCH | Unsupported protocol version |
| 3 | INVALID_MESSAGE | Message failed schema validation |
| 4 | MESSAGE_TOO_LARGE | Payload exceeds size limit |
| 5 | SEQUENCE_GAP | Missing sequence number(s) |
| 6 | RATE_LIMITED | Too many requests |
| 7 | NODE_UNKNOWN | Node not registered |
| 8 | CAPABILITY_DENIED | Capability not in node allowlist |
| 9 | TASK_EXPIRED | Task deadline passed |
| 10 | TASK_DUPLICATE | Duplicate task (idempotency key collision) |
| 11 | SESSION_EXPIRED | Session timed out |
| 12 | INTERNAL_ERROR | Internal server error |

---

## 4. Session Lifecycle

### 4.1 Connection
```
1. Node opens wss:// connection to Control Plane
2. TLS handshake (node validates server certificate)
3. Node sends HELLO {node_id, supported_protocol_versions, session_resume_id?}
4. Control Plane verifies node identity:
   a. If session_resume_id valid -> resume session (skip to 6)
   b. If node unknown -> PROTOCOL_ERROR(NODE_UNKNOWN)
   c. If node revoked -> PROTOCOL_ERROR(AUTH_FAILED)
5. Control Plane sends WELCOME {session_id, protocol_version, ...}
6. Session active — heartbeat loop begins
```

### 4.2 Heartbeat
```
1. Node sends HEARTBEAT every heartbeat_interval_ms
2. Control Plane responds HEARTBEAT_ACK
3. If no heartbeat for liveness_timeout_ms:
   a. Control Plane marks node offline
   b. Active tasks for this node marked for recovery
   c. Queued tasks remain queued
```

### 4.3 Disconnection
```
1. Clean: Node sends GOODBYE, closes WebSocket
2. Unclean: TCP connection drops, heartbeat timeout
3. Control Plane marks session inactive
4. Node attempts reconnect with exponential backoff
```

### 4.4 Reconnection
```
1. Node opens new wss:// connection
2. Node sends HELLO with session_resume_id
3. If session is resumable (within grace period):
   a. Control Plane sends WELCOME with resumed session
   b. Control Plane replays unacknowledged tasks
   c. Node acknowledges tasks it already executed (idempotency protection)
   d. Node reports status of in-flight tasks
4. If session is not resumable:
   a. New session created
   b. In-flight tasks marked for recovery
```

---

## 5. Message Signing

### 5.1 Algorithm
- HMAC-SHA256
- Key: node-specific signing key (part of PairingCredential)
- Signed fields: `{message_id}:{message_type}:{source}:{target}:{timestamp}:{payload_json}`
- Payload JSON serialized with sorted keys, no whitespace

### 5.2 Verification
1. Extract `signature` from envelope
2. Reconstruct signing string from envelope fields
3. HMAC-SHA256 with node's signing key
4. Constant-time comparison (`hmac.compare_digest`)
5. Reject if mismatch

---

## 6. HTTP API (Control Plane -> Client)

The Control Plane also serves an HTTPS API for Access Clients (CLI, Web/PWA).

### 6.1 Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/health` | None | Control Plane health |
| POST | `/api/v1/pairing/create` | User | Create pairing code |
| POST | `/api/v1/tasks` | User | Submit task |
| GET | `/api/v1/tasks` | User | List tasks |
| GET | `/api/v1/tasks/{id}` | User | Get task details |
| GET | `/api/v1/tasks/{id}/logs` | User | Get task logs |
| POST | `/api/v1/tasks/{id}/cancel` | User | Cancel task |
| GET | `/api/v1/tasks/{id}/artifacts` | User | List task artifacts |
| GET | `/api/v1/nodes` | User | List paired nodes |
| GET | `/api/v1/nodes/{id}` | User | Get node details |
| POST | `/api/v1/nodes/{id}/revoke` | User | Revoke node |
| GET | `/api/v1/sessions` | User | List active sessions |

### 6.2 Authentication
- Bearer token in Authorization header
- Token obtained via user login (not in Phase 1 scope — use CLI-based auth for initial slice)

---

## 7. Deterministic Serialization

### 7.1 JSON Serialization
- Keys sorted alphabetically
- No whitespace outside string values
- UTF-8 encoding
- DateTime as ISO-8601 with `Z` suffix and seconds precision
- Integers without decimal point
- Floats with `.` decimal separator (never scientific notation)

### 7.2 Deterministic Hashing
- Used for: idempotency keys, integrity verification
- Algorithm: SHA-256 of deterministic JSON bytes
- Redacted fields ({api_key}, {token}, {secret}) replaced with literal `"<REDACTED>"` before hashing for log-safe hashes

### 7.3 Redacted Serialization
- Used for: log output, debug messages, error responses
- Fields matching: `*key*`, `*secret*`, `*token*`, `*password*`, `*credential*` replaced with `"<REDACTED>"`
- Redacted output is NOT parseable back to original object
- Unredacted serialization only used for wire transmission (TLS-encrypted)

---

## 8. Malformed Input Handling

1. Non-JSON input -> PROTOCOL_ERROR(INVALID_MESSAGE)
2. JSON that fails schema validation -> PROTOCOL_ERROR(INVALID_MESSAGE) with validation errors
3. Payload exceeds size limit -> connection closed before full read
4. Unknown message_type -> PROTOCOL_ERROR(INVALID_MESSAGE)
5. Missing required fields -> PROTOCOL_ERROR(INVALID_MESSAGE) with field names
6. Invalid UTF-8 -> connection closed
7. DoS protection: connection closed after N consecutive invalid messages (default 10)

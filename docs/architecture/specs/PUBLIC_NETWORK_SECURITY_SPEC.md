# Public Network Security Specification v1.0

> Status: Draft — Phase 0.5
> Security requirements for public-network exposure

---

## 1. Transport Security

### 1.1 Requirements
- **HTTPS**: All HTTP API endpoints use TLS 1.2+
- **WSS**: All WebSocket connections use TLS
- **Certificate**: Valid certificate from public CA (e.g., Let's Encrypt)
- **HSTS**: `Strict-Transport-Security` header set (production)
- **Cipher**: Modern cipher suites only (no TLS 1.0/1.1, no export ciphers)

### 1.2 Development Exception
- Self-signed certificates allowed in development with `NOUS_DEV_ACCEPT_SELF_SIGNED=1`
- Plain HTTP allowed on `localhost` only in development mode
- Development mode must be explicitly enabled (not default)

### 1.3 Reverse Proxy (Production)
- nginx or Caddy in front of Control Plane
- TLS terminated at reverse proxy
- Internal traffic (proxy -> Control Plane) on localhost
- Proxy handles rate limiting, request size limits, header sanitization

---

## 2. Authentication

### 2.1 Node Authentication
- Per-device Ed25519 key pair (issued during pairing)
- HMAC-SHA256 message signing
- Session token (short-lived, issued on connect)
- See `DEVICE_CREDENTIAL_LIFECYCLE_SPEC.md`

### 2.2 Client Authentication
- Bearer token in Authorization header
- Token obtained via CLI login or Web/PWA login
- Token TTL: 24 hours (configurable)
- Refresh token support (future)

### 2.3 Prohibitions
- No shared tokens across devices
- No permanent tokens
- No hardcoded tokens in source code
- No tokens in URLs (use headers only)

---

## 3. Rate Limiting

| Endpoint | Limit | Window | Block Duration |
|---|---|---|---|
| WebSocket connect | 10 | 60s | 300s |
| Pairing code submission | 5 | 60s | 300s |
| Failed auth (any) | 10 | 60s | 300s |
| Task submission | 60 | 60s | — |
| Heartbeat | 4 | 60s | — |
| API (general) | 120 | 60s | — |

---

## 4. Input Validation

### 4.1 Message Validation
- JSON Schema validation on ALL incoming messages
- Unknown fields rejected (strict mode)
- String length limits on all string fields
- Numeric range limits on all numeric fields
- Enum validation on all enumerated fields

### 4.2 Payload Size
- Envelope: max 1 KB
- Payload: max 1 MB (configurable via `NOUS_MAX_PAYLOAD_BYTES`)
- Oversized: connection closed before full read (DoS protection)

### 4.3 Malformed Input
- Non-JSON -> PROTOCOL_ERROR
- Schema failure -> PROTOCOL_ERROR with validation details
- Repeated malformed (10+) -> connection closed, IP rate-limited

---

## 5. Capability Allowlist

### 5.1 Per-Node Allowlist
- Node declares capabilities in NodeManifest
- Control Plane enforces: only declared capabilities assignable
- Node enforces locally: defense in depth
- Unregistered capability request -> CAPABILITY_DENIED

### 5.2 Risk Gating
| Level | Auto-Execute | Require Confirm | Revocable | Double Audit |
|---|---|---|---|---|
| LOW | Yes | No | No | No |
| MEDIUM | Yes | No | No | No |
| HIGH | No | Yes | No | No |
| CRITICAL | No | Yes | Yes | Yes |

### 5.3 Sandboxing (process.run_sandboxed)
- No `shell=True`
- Environment allowlist
- Workspace-restricted cwd
- Timeout enforced (SIGTERM -> SIGKILL)
- Process-tree termination on cancel
- No elevation
- No network (unless explicitly allowed)

---

## 6. Audit Immutability

- Append-only audit log (SQLite, no DELETE API)
- All security events recorded: auth success/failure, pairing, revocation, task submission, capability execution, approval, cancellation
- Audit entries include: timestamp, actor, action, target, result, sanitized detail, IP
- Retention: 90 days default, configurable
- Audit log access: read-only, authenticated, logged

---

## 7. Emergency Controls

### 7.1 Kill Switch — Node
- `nous node revoke <id>` — immediate, all sessions terminated
- Emergency revoke-all: `nous node revoke --all` (requires confirmation)

### 7.2 Kill Switch — Service
- `nous server stop` — graceful shutdown (complete in-flight tasks)
- `nous server stop --force` — immediate shutdown (in-flight tasks marked failed)

### 7.3 Emergency Credential Rotation
- `nous node rotate --all --force` — rotate all node credentials immediately (no overlap window)

---

## 8. Log Redaction

### 8.1 Redacted Patterns
- API keys: `sk-*`, `sk-*`, `AKIA*`
- Tokens: `Bearer *`, `X-Auth-Token: *`
- Secrets: `*secret*`, `*password*`, `*credential*`, `*private_key*`
- Pairing codes: 8-char alphanumeric
- JWT tokens: `eyJ*`

### 8.2 Redaction Method
- All log output passes through `mask_sensitive()` before write
- Redacted values replaced with `"<REDACTED>"`
- Redaction is one-way (cannot recover original)
- Structured logging uses redacted serialization (see RELAY_PROTOCOL_SPEC.md §7.3)

---

## 9. Explicit Prohibitions

| Prohibition | Enforcement Mechanism |
|---|---|
| Shared permanent device tokens | Schema: no `token` field in PairingCredential |
| Unrestricted shell (`shell=True`) | Process executor: list args only |
| Arbitrary path execution | Workspace guard: path validation |
| Public debug endpoints | Feature flag: `NOUS_DEBUG` (default off) |
| Model-controlled pairing | Design: requires human CLI interaction |
| Model-controlled privilege escalation | Risk gating: hard constraints |
| Automatic production promotion | SelfDevelopmentPipeline: human approval step |
| Plaintext credential storage | Credential store: OS keychain or encrypted file |
| Direct database exposure | SQLite: local process only |

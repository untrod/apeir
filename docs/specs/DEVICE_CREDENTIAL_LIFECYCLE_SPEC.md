# Device Credential Lifecycle Specification v1.0

> Status: Draft — Phase 0.5
> Credential states, rotation, revocation, storage

---

## 1. Credential States

```
  ┌──────────┐  issue (pairing)  ┌──────────┐  rotate   ┌──────────────┐
  │   NONE   │──────────────────►│  ACTIVE  │──────────►│  ROTATING    │
  └──────────┘                   └──────────┘           │ (overlap)    │
        ▲                              │                └──────┬───────┘
        │                              │ revoke                 │
        │                              ▼                        │ complete
        │                        ┌──────────┐                   │
        └────────────────────────│ REVOKED  │◄──────────────────┘
                                 └──────────┘
                                      ▲
                                      │ auto (expires_at reached)
                                 ┌──────────┐
                                 │ EXPIRED   │
                                 └──────────┘
```

---

## 2. Credential Structure

```json
{
  "credential_id": "cred_20260713_a1b2c3d4",
  "node_id": "node_20260713_e5f6g7h8",
  "key_type": "ed25519",
  "public_key": "ed25519:abc123...",
  "signing_key_hash": "sha256:def456...",
  "issued_at": "2026-07-13T10:00:00Z",
  "expires_at": "2027-07-13T10:00:00Z",
  "status": "active",
  "revoked_at": null,
  "revoked_by": null,
  "revoke_reason": null,
  "rotation": null
}
```

---

## 3. Lifecycle Operations

### 3.1 Issue (Pairing)
1. Pairing code validated
2. User confirms pairing
3. Node generates Ed25519 key pair
4. Node sends public key in PAIRING_REQUEST
5. Server creates credential record
6. Server sends PAIRING_APPROVAL with credential (public key + metadata)
7. Node stores private key locally (0600)
8. Pairing code invalidated

### 3.2 Rotate
1. Initiated by: `nous node rotate <id>` or scheduled rotation
2. Server generates rotation request
3. Node generates new Ed25519 key pair
4. Node sends new public key
5. Server creates new credential in ROTATING state
6. Overlap period: old credential remains ACTIVE, new credential ROTATING
7. During overlap: both credentials valid for signing
8. After overlap (default 1 hour): old credential expired, new credential ACTIVE
9. In-flight tasks during rotation: complete with old credential
10. New tasks: use new credential

### 3.3 Revoke
1. Initiated by: `nous node revoke <id>` or security event
2. Immediate effects:
   - Credential status set to REVOKED
   - All active sessions for node terminated
   - Node disconnected (WebSocket close)
   - Queued tasks for node failed with "node_revoked"
   - In-flight tasks marked for recovery
3. Revoked credential retained in audit log for 90 days
4. Future connection attempts with revoked credential rejected

### 3.4 Expire
1. `expires_at` timestamp reached
2. Automatic revocation (same effects as manual revoke)
3. Node must re-pair before `expires_at` if continuous operation needed

---

## 4. Credential Storage

### 4.1 Node (Private Key)
- **Primary**: OS keychain
  - Windows: Credential Manager (wincred)
  - macOS: Keychain
  - Linux: Secret Service API (libsecret) or `~/.nous/key` (fallback)
- **Fallback**: Encrypted file
  - Path: `~/.nous/credentials/node.key`
  - Permissions: 0600 (owner read/write only)
  - Encryption: AES-256-GCM with key derived from machine-specific secret
- **Never**: plaintext config files, environment variables, logs, debug output

### 4.2 Control Plane (Public Keys)
- Stored in SQLite `devices` table
- Public keys only (no private keys on server)
- Signing key hash stored for message verification reference
- Credential history retained for audit (90 days after revocation)

### 4.3 Pairing Code (Server)
- SHA-256 hashed
- Stored in memory only (never persisted)
- TTL: 5 minutes
- Consumed on first use (success or failure)
- Brute force: 5 attempts per code, then invalidated

---

## 5. Credential Security Rules

| Rule | Enforcement |
|---|---|
| No credential in logs | Redacted serialization on all credential objects |
| No shared credentials | One credential per node. Schema enforced. |
| No permanent credentials | `expires_at` required. Max lifetime: 1 year. |
| Rotation supported | Overlap window. Both credentials valid during rotation. |
| Revocation immediate | Next connection/auth attempt detects revocation. |
| Re-pair requires human | New pairing code required. Old credential revoked. |
| Lost private key = re-pair | No recovery path. Node must re-pair. |
| Brute force protection | 5 attempts per pairing code. Rate limiting on failed attempts. |

---

## 6. Credential Verification

### 6.1 Message Signing Verification
1. Receive message with `signature` field
2. Look up node's public key by `source` field
3. Reconstruct signing string from message fields
4. Verify HMAC-SHA256 signature with public key
5. Constant-time comparison
6. Reject on mismatch (log security event)

### 6.2 Credential Status Check
1. On every authenticated message: check credential status
2. If `status == "revoked"` or `"expired"`: reject with AUTH_FAILED
3. If `status == "rotating"`: accept with old or new credential (both valid)
4. If `status != "active"` and `!= "rotating"`: reject

---

## 7. Credential Recovery

### 7.1 Lost Private Key
- Node cannot authenticate
- Must re-pair (full pairing flow)
- Old credential revoked (if still valid)
- New credential issued
- Task history preserved (node_id unchanged)

### 7.2 Compromised Credential
1. User initiates emergency revocation: `nous node revoke <id> --emergency`
2. All sessions terminated immediately
3. All queued/in-flight tasks failed
4. Security event recorded with EMERGENCY flag
5. New credential issued only after security review
6. Previous credential audit trail preserved for investigation

### 7.3 Server Key Compromise
1. All node credentials must be rotated
2. `nous node rotate --all --force` (no overlap, immediate)
3. Each node re-authenticates with new credential
4. Audit log: mass rotation event recorded
5. Previous server key invalidated

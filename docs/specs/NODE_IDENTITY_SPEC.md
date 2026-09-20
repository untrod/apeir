# Node Identity Specification v1.0

> Status: Draft — Phase 0.5
> Defines the node identity model, credential structure, and pairing flow

---

## 1. NodeIdentity

### 1.1 Schema

```json
{
  "node_id": "node_20260713_a1b2c3d4",
  "node_name": "laptop-main",
  "node_role": "personal_node",
  "platform": {
    "os": "windows",
    "os_version": "10.0.19045",
    "arch": "amd64",
    "hostname": "laptop-main"
  },
  "capabilities": [
    "system.echo",
    "system.info",
    "workspace.list",
    "workspace.read",
    "process.run_sandboxed"
  ],
  "public_key": "ed25519:abc123...",
  "created_at": "2026-07-13T10:00:00Z",
  "version": "1.1.0.dev0"
}
```

### 1.2 Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `node_id` | string | Yes | Globally unique node identifier. Format: `node_{YYYYMMDD}_{8hex}` |
| `node_name` | string | Yes | Human-readable name. User-configurable. |
| `node_role` | string | Yes | `personal_node` or `cloud_worker` |
| `platform.os` | string | Yes | Operating system |
| `platform.os_version` | string | Yes | OS version string |
| `platform.arch` | string | Yes | CPU architecture |
| `platform.hostname` | string | Yes | Machine hostname |
| `capabilities` | []string | Yes | Capability IDs this node can execute |
| `public_key` | string | Yes | Node's public key (Ed25519) |
| `created_at` | string | Yes | UTC ISO-8601 |
| `version` | string | Yes | Nous Runtime version on node |

### 1.3 Validation
- `node_id` matches format pattern
- `node_role` is `personal_node` or `cloud_worker`
- `capabilities` contains only valid capability IDs
- `public_key` is a valid Ed25519 public key
- No secrets in NodeIdentity (public information only)

---

## 2. NodeManifest

### 2.1 Schema

```json
{
  "manifest_version": "1.0",
  "node_identity": { ... },
  "workspace": {
    "root_path": "/srv/nous/workspace",
    "allowed_paths": ["/srv/nous/workspace/**"],
    "quota": {
      "max_size_bytes": 1073741824,
      "max_files": 100000
    }
  },
  "agent_runtimes": [
    {
      "agent_id": "generic_cli",
      "agent_version": "1.0.0",
      "capabilities": ["system.echo", "system.info", "process.run_sandboxed"],
      "health": "ok"
    }
  ],
  "network": {
    "outbound_only": true,
    "preferred_relay": null
  },
  "trust_zone": "personal",
  "exported_at": "2026-07-13T10:00:00Z"
}
```

### 2.2 Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `manifest_version` | string | Yes | Schema version for this manifest |
| `node_identity` | NodeIdentity | Yes | Node identity (see §1) |
| `workspace.root_path` | string | Conditional | Required for personal_node. Workspace root directory. |
| `workspace.allowed_paths` | []string | Yes | Glob patterns for allowed file access |
| `workspace.quota` | object | Yes | Size and file count limits |
| `agent_runtimes` | []object | Yes | Installed agent runtimes and their capabilities |
| `network.outbound_only` | bool | Yes | Must be true |
| `trust_zone` | string | Yes | `personal`, `cloud_trusted`, or `cloud_untrusted` |
| `exported_at` | string | Yes | UTC ISO-8601 |

---

## 3. PairingCredential

### 3.1 Schema

```json
{
  "credential_id": "cred_20260713_a1b2c3d4",
  "node_id": "node_20260713_e5f6g7h8",
  "public_key": "ed25519:abc123...",
  "signing_key_hash": "sha256:def456...",
  "issued_at": "2026-07-13T10:00:00Z",
  "expires_at": "2027-07-13T10:00:00Z",
  "status": "active",
  "rotation": null
}
```

### 3.2 Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `credential_id` | string | Yes | Unique credential identifier |
| `node_id` | string | Yes | Node this credential belongs to |
| `public_key` | string | Yes | Node's public key (server-side copy) |
| `signing_key_hash` | string | Yes | SHA-256 hash of the signing key (for verification without storing key) |
| `issued_at` | string | Yes | UTC ISO-8601 |
| `expires_at` | string | Yes | UTC ISO-8601. Maximum 1 year from issued_at. |
| `status` | string | Yes | `active`, `rotating`, `revoked`, `expired` |
| `rotation` | object | No | Present when status is `rotating` |

### 3.3 Rotation Schema

```json
{
  "rotation": {
    "new_credential_id": "cred_20260713_x1y2z3",
    "new_public_key": "ed25519:ghi789...",
    "new_signing_key_hash": "sha256:jkl012...",
    "overlap_start": "2026-07-13T10:00:00Z",
    "overlap_end": "2026-07-13T11:00:00Z"
  }
}
```

---

## 4. Pairing Flow

### 4.1 Sequence

```
Control Plane          Node              User (CLI)
     │                   │                    │
     │                   │  1. nous node pair │
     │◄──────────────────────────────────────│
     │                   │                    │
     │  2. Generate code │                    │
     │  (8 chars, 5min)  │                    │
     │──────────────────────────────────────►│
     │  "Code: A1B2C3D4" │                    │
     │                   │                    │
     │                   │  3. nous node join │
     │                   │     A1B2C3D4       │
     │                   │◄───────────────────│
     │                   │                    │
     │  4. PAIRING_REQUEST                    │
     │  {code, identity} │                    │
     │◄──────────────────│                    │
     │                   │                    │
     │  5. Validate code  │                    │
     │  - TTL check       │                    │
     │  - Replay check    │                    │
     │  - Code hash match │                    │
     │                   │                    │
     │  6. "Confirm node  │                    │
     │  'laptop-main'?"   │                    │
     │──────────────────────────────────────►│
     │                   │                    │
     │                   │  7. "yes"          │
     │◄──────────────────────────────────────│
     │                   │                    │
     │  8. Issue credential                   │
     │  Store public key  │                    │
     │  Invalidate code   │                    │
     │                   │                    │
     │  9. PAIRING_APPROVAL                   │
     │  {credential}      │                    │
     │──────────────────►│                    │
     │                   │                    │
     │                   │ 10. Store          │
     │                   │ credential (0600)  │
     │                   │                    │
     │ 11. "Node paired"  │                    │
     │──────────────────────────────────────►│
```

### 4.2 Pairing Code

- Format: 8 alphanumeric characters (A-Z, 0-9, excluding O/0/I/1 to prevent confusion)
- TTL: 5 minutes from generation
- Storage: SHA-256 hashed in memory. Plaintext never persisted.
- One-time use: consumed on first validation (success or failure)
- Replay detection: code hash checked against used-codes set

### 4.3 Security Invariants

1. Pairing code never appears in logs (redacted)
2. Pairing code never persisted to disk (hashed only)
3. User must explicitly confirm on CLI (step 7)
4. No model can initiate or approve pairing
5. No automatic trust expansion — paired node gets only declared capabilities
6. Failed pairing attempts logged as security events
7. Brute force protection: 5 attempts per code, then code invalidated
8. Multiple failed codes from same IP -> rate limit escalation

---

## 5. Credential Lifecycle

### 5.1 States

```
NONE -> ACTIVE -> ROTATING -> ACTIVE (new credential)
                   │
                   ├──► REVOKED
                   │
                   └──► EXPIRED (auto-revoke)
```

### 5.2 Operations

| Operation | Trigger | Behavior |
|---|---|---|
| Issue | Pairing complete | Generate key pair. Store private on node, public on server. |
| Rotate | `nous node rotate <id>` | Generate new key. Old key valid for overlap period (1h). |
| Revoke | `nous node revoke <id>` | Disconnect node. Invalidate credential. All sessions terminated. |
| Expire | `expires_at` reached | Automatic revocation. |
| Re-pair | Credential lost | Full pairing flow required. Old credential revoked. |

### 5.3 Storage

- **Node (private key)**: OS keychain or encrypted file (0600 on Linux/macOS)
- **Server (public key)**: SQLite `devices` table
- **Pairing code**: Hashed in memory, 5 min TTL
- **Revoked credentials**: Retained in audit log for 90 days

---

## 6. Node Revocation

### 6.1 Immediate Effects
1. Node disconnected (WebSocket closed with PROTOCOL_ERROR)
2. All active sessions for node terminated
3. All queued tasks for node failed with "node_revoked"
4. All in-flight tasks marked for recovery (reassignable to other nodes if compatible)
5. Node added to revocation list (future connections rejected)
6. Audit record created with revocation reason and actor

### 6.2 Re-pairing After Revocation
- Revoked node may re-pair (new pairing flow required)
- New credential issued
- Old credential remains revoked
- Previous task history preserved (node_id unchanged)

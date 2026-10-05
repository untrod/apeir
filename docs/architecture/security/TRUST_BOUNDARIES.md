# Trust Boundaries v1.0

> Date: 2026-07-13
> Defines trust boundaries in the Nous connectivity architecture

---

## 1. Boundary Map

```
┌──────────────────────────────────────────────────────────────┐
│                    UNTRUSTED (Internet)                       │
│                                                               │
│  ┌──────────┐                              ┌──────────┐      │
│  │  Client   │──── TB5 (HTTPS)────────────►│ Control  │      │
│  │ (CLI/Web) │                              │  Plane   │      │
│  └──────────┘                              └────┬─────┘      │
│                                                 │             │
│                    TB1 (WSS + TLS)              │             │
│  ┌──────────────────────────────────────────────┼──────┐     │
│  │                 SEMI-TRUSTED (Node)          │      │     │
│  │                                              │      │     │
│  │  ┌──────────┐  TB2  ┌──────────┐            │      │     │
│  │  │  Node    │◄─────►│ Session  │            │      │     │
│  │  │ Daemon   │       │  State   │            │      │     │
│  │  └────┬─────┘       └──────────┘            │      │     │
│  │       │                                       │      │     │
│  │       │ TB3 (workspace boundary)             │      │     │
│  │  ┌────▼─────┐                                │      │     │
│  │  │ Workspace│                                │      │     │
│  │  │ (sandbox)│                                │      │     │
│  │  └──────────┘                                │      │     │
│  │                                              │      │     │
│  │  TB4 (provider boundary)                     │      │     │
│  │  ┌──────────┐                                │      │     │
│  │  │ External │                                │      │     │
│  │  │Provider  │                                │      │     │
│  │  │(LLM/API) │                                │      │     │
│  │  └──────────┘                                │      │     │
│  └──────────────────────────────────────────────┼──────┘     │
│                                                 │             │
│                    TB6 (data boundary)          │             │
│  ┌──────────────────────────────────────────────┼──────┐     │
│  │                 TRUSTED (Storage)            │      │     │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐   │      │     │
│  │  │ SQLite   │  │ JSONL    │  │ Artifact │   │      │     │
│  │  │ (relational)│ │(append) │  │ Store    │   │      │     │
│  │  └──────────┘  └──────────┘  └──────────┘   │      │     │
│  └──────────────────────────────────────────────┴──────┘     │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Trust Boundary Definitions

### TB1: Internet <-> Control Plane (Public Network Boundary)

| Property | Value |
|---|---|
| **Trust level change** | Untrusted -> Trusted (after auth) |
| **Protocol** | HTTPS, WSS |
| **Authentication** | TLS server certificate + client auth (per-device or Bearer token) |
| **Data flow direction** | Bidirectional (clients push, nodes push/pull) |
| **Security controls** | TLS 1.2+, rate limiting, message size limits, schema validation, replay protection |
| **Compromise impact** | Unauthorized access to Control Plane API |
| **Monitoring** | Failed auth rate, connection rate, message size anomalies |

### TB2: Control Plane <-> Node (Node Connection Boundary)

| Property | Value |
|---|---|
| **Trust level change** | Semi-trusted (node) <-> Trusted (Control Plane) |
| **Protocol** | WSS (WebSocket over TLS) |
| **Authentication** | Per-device Ed25519 key pair + HMAC message signing |
| **Data flow direction** | Bidirectional (task assignment ->, results/events <-) |
| **Security controls** | TLS, per-message HMAC, sequence numbers, capability allowlist, session management |
| **Compromise impact** | Malicious node receives tasks, legitimate node impersonated |
| **Monitoring** | Session creation rate, heartbeat failures, sequence gaps, capability denial rate |

### TB3: Node Daemon <-> Workspace (Workspace Boundary)

| Property | Value |
|---|---|
| **Trust level change** | Trusted (Node daemon) <-> Untrusted (task execution) |
| **Protocol** | Process boundary (subprocess) |
| **Authentication** | N/A (same OS user) |
| **Data flow direction** | Task execution reads/writes within workspace only |
| **Security controls** | Path validation, workspace root enforcement, no shell=True, environment allowlist, timeout, process-tree termination |
| **Compromise impact** | Task reads/writes outside workspace, escalates privileges |
| **Monitoring** | Path validation failures, process resource usage, timeout rate |

### TB4: Node <-> External Provider (Provider Boundary)

| Property | Value |
|---|---|
| **Trust level change** | Semi-trusted (Node) -> Untrusted (external provider) |
| **Protocol** | HTTPS (provider-specific API) |
| **Authentication** | Provider-specific API key |
| **Data flow direction** | Outbound requests, inbound responses |
| **Security controls** | Provider response validation, timeout, retry with circuit breaker, output sanitization, no credential passthrough |
| **Compromise impact** | Malicious provider response, prompt injection, data exfiltration |
| **Monitoring** | Provider response anomalies, circuit state changes, retry rate |

### TB5: Access Client <-> Control Plane (Client Boundary)

| Property | Value |
|---|---|
| **Trust level change** | Untrusted -> Trusted (after auth) |
| **Protocol** | HTTPS |
| **Authentication** | Bearer token (CLI: local config, Web: login) |
| **Data flow direction** | Bidirectional (submit/list tasks, manage nodes, view state) |
| **Security controls** | TLS, token validation, rate limiting, authorization checks (user scopes) |
| **Compromise impact** | Unauthorized task submission, node management |
| **Monitoring** | Auth failure rate, unusual API usage patterns |

### TB6: Control Plane <-> Storage (Data Boundary)

| Property | Value |
|---|---|
| **Trust level change** | Trusted (Control Plane) <-> Trusted (local storage) |
| **Protocol** | Local filesystem, SQLite API |
| **Authentication** | OS file permissions |
| **Data flow direction** | Read/write by Control Plane process only |
| **Security controls** | OS file permissions (0600 for sensitive), SQLite access control, no network exposure, backup encryption |
| **Compromise impact** | Data theft, data modification, credential exposure |
| **Monitoring** | File integrity, unauthorized access attempts, backup verification |

---

## 3. Trust Zone Taxonomy

### Zone: Trusted
- Control Plane process
- Local storage (SQLite, JSONL, filesystem)
- Node daemon (the daemon itself, not tasks it executes)
- **Characteristics**: Full access to own resources. Hardened against external attack.

### Zone: Semi-Trusted
- Node tasks/processes (sandboxed)
- Agent runtimes (constrained by allowlist)
- **Characteristics**: Restricted access. Capability allowlist. Workspace boundaries. May execute attacker-controlled code.

### Zone: Untrusted
- Internet (public network)
- External providers (LLM APIs, web search, git remotes)
- Client devices before authentication
- **Characteristics**: No trust. All input validated. All output sanitized.

---

## 4. Data Classification Across Boundaries

| Data | TB1 | TB2 | TB3 | TB4 | TB5 | TB6 |
|---|---|---|---|---|---|---|
| Node identity (public) | ✓ | ✓ | ✓ | — | ✓ | ✓ |
| Node credential (private) | — | ✓ (encrypted) | — | — | — | ✓ (encrypted) |
| Task payloads | ✓ (TLS) | ✓ (TLS + HMAC) | ✓ (local) | — | ✓ (TLS) | ✓ |
| Task results | ✓ (TLS) | ✓ (TLS + HMAC) | ✓ (local) | — | ✓ (TLS) | ✓ |
| Audit logs | — | — | — | — | ✓ (read-only) | ✓ |
| User auth tokens | ✓ (TLS) | — | — | — | ✓ (TLS) | ✓ (hashed) |
| Pairing codes | — | ✓ (HMAC signed) | — | — | ✓ (TLS) | — (hashed, ephemeral) |

**Key**: ✓ = Allowed, — = Not allowed, TLS = Encrypted in transit, HMAC = Integrity-protected

---

## 5. Boundary Violation Scenarios

### BV1: Task Accesses Node Credential
- **Boundary violated**: TB3 (workspace boundary)
- **How**: Task process reads `~/.nous/credentials/` through path traversal
- **Prevention**: Workspace root enforcement. `~/.nous/` is outside workspace root.
- **Detection**: Path validation failure

### BV2: Node Accepts Inbound Connection
- **Boundary violated**: TB1 (public network boundary)
- **How**: Node has open port, attacker connects directly
- **Prevention**: Node daemon makes outbound connections only. No listening sockets.
- **Detection**: Security scan detects open ports

### BV3: Agent Accesses Another Agent's State
- **Boundary violated**: TB3 (workspace boundary)
- **How**: Agent reads files from another agent's workspace
- **Prevention**: Workspace isolation per task. No shared workspaces between tasks.
- **Detection**: Cross-workspace access pattern detection

### BV4: Provider Response Exfiltrates Data
- **Boundary violated**: TB4 (provider boundary)
- **How**: Provider response includes instructions to send data to external URL
- **Prevention**: No unrestricted network from sandbox. No credential passthrough to providers.
- **Detection**: Outbound network connection from sandbox (if monitored)

### BV5: Client Reads Another User's Tasks
- **Boundary violated**: TB5 (client boundary)
- **How**: Client modifies API request to query another user's tasks
- **Prevention**: User-scoped API. Auth token tied to user identity. Authorization check on every query.
- **Detection**: Cross-user access attempt logged

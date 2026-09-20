# Threat Model v1.0

> Date: 2026-07-13
> Scope: Nous Runtime connectivity and execution system

---

## 1. System Overview

```
                    ┌──────────────┐
    User ──────────►│ Access Client │ (CLI / Web/PWA / Watch)
                    └──────┬───────┘
                           │ HTTPS
                    ┌──────▼───────┐
                    │ Control Plane │ (Gateway + Coordinator)
                    └──────┬───────┘
                           │ WSS
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  Node A   │ │  Node B   │ │  Node C   │
        │ (personal)│ │ (cloud)   │ │ (personal)│
        └──────────┘ └──────────┘ └──────────┘
```

### 1.1 Trust Boundaries
- **TB1**: Internet <-> Control Plane (public network boundary)
- **TB2**: Control Plane <-> Node (node connection boundary)
- **TB3**: Node <-> Node-local resources (workspace boundary)
- **TB4**: Node <-> External services (provider boundary)
- **TB5**: Access Client <-> Control Plane (client boundary)
- **TB6**: Control Plane <-> Storage (data boundary)

See `TRUST_BOUNDARIES.md` for detailed trust boundary definitions.

---

## 2. Threat Actors

### TA1: Unauthenticated Internet Attacker
- **Motivation**: Exploit exposed services, steal data, cause denial of service
- **Capability**: Can reach public IP, scan ports, send crafted requests
- **Entry points**: Public HTTPS/WSS endpoints, reverse proxy

### TA2: Compromised Device
- **Motivation**: Use stolen device to access Nous system
- **Capability**: Has physical or remote access to a paired device
- **Entry points**: Node credential on device, active sessions

### TA3: Stolen Device Credential
- **Motivation**: Impersonate a legitimate node
- **Capability**: Has exfiltrated private key file
- **Entry points**: WebSocket connection with stolen credential

### TA4: Malicious Provider Response
- **Motivation**: Inject malicious content via LLM/API responses
- **Capability**: Controls a provider's API response
- **Entry points**: LLM API, web search API, any external provider

### TA5: Prompt Injection
- **Motivation**: Bypass security controls via crafted input
- **Capability**: Provides input to LLM (directly or via content)
- **Entry points**: User messages, document content, repository content

### TA6: Malicious Repository Content
- **Motivation**: Execute malicious code via repository checkout
- **Capability**: Controls content in a git repository
- **Entry points**: Git clone/checkout in workspace

### TA7: Compromised Agent
- **Motivation**: Execute unauthorized actions via agent runtime
- **Capability**: Controls or manipulates an agent process
- **Entry points**: Agent adapter, subprocess execution

### TA8: Accidental User Approval
- **Motivation**: (None — accidental)
- **Capability**: Legitimate user who approves without understanding
- **Entry points**: Approval confirmation UI

### TA9: Compromised Server Account
- **Motivation**: Full system compromise
- **Capability**: SSH/console access to Control Plane server
- **Entry points**: Server OS, SSH, hosting provider

### TA10: Dependency Compromise
- **Motivation**: Inject malicious code via supply chain
- **Capability**: Publishes malicious package to PyPI/npm
- **Entry points**: pip install, npm install, dependency updates

---

## 3. Threat Analysis

### T1: Unauthorized Node Connection
| Attribute | Detail |
|---|---|
| **Threat actor** | TA1 (Internet attacker), TA2 (Compromised device) |
| **Entry point** | WebSocket endpoint (wss://) |
| **Affected asset** | Control Plane, task execution |
| **Attack path** | 1. Attacker obtains or guesses pairing code. 2. Attacker submits PAIRING_REQUEST. 3. If accepted, attacker's node can receive task assignments. |
| **Prevention** | One-time pairing code (5 min TTL). Human confirmation required. Code hashed, never persisted. Brute force: 5 attempts then invalidated. |
| **Detection** | Failed pairing attempts logged as security events. Rate limit exceeded -> alert. |
| **Response** | Block IP after rate limit exceeded. Investigate repeated attempts. |
| **Remaining risk** | Low. Pairing requires code + human confirmation. |

### T2: Credential Theft from Node
| Attribute | Detail |
|---|---|
| **Threat actor** | TA2 (Compromised device), TA3 (Stolen credential) |
| **Entry point** | Node credential file |
| **Affected asset** | Node identity, task execution capability |
| **Attack path** | 1. Malware on personal device reads `~/.nous/credentials/node.key`. 2. Attacker uses key to authenticate as node. 3. Attacker receives and executes task assignments. |
| **Prevention** | Credential stored with 0600 permissions or OS keychain. Encrypted at rest. Capability allowlist limits what stolen credential can do. |
| **Detection** | Unusual task patterns. Node connecting from unexpected IP. |
| **Response** | Revoke credential. Re-pair node. Investigate compromise. |
| **Remaining risk** | Medium. If malware has same-user access, file permissions don't help. Capability allowlist is the last line of defense. |

### T3: Man-in-the-Middle (Network)
| Attribute | Detail |
|---|---|
| **Threat actor** | TA1 (Internet attacker) |
| **Entry point** | Network path between Node and Control Plane |
| **Affected asset** | Message confidentiality and integrity |
| **Attack path** | 1. Attacker intercepts WebSocket traffic. 2. Without TLS: reads/modifies messages. 3. With compromised TLS: impersonates server. |
| **Prevention** | TLS 1.2+ required. Certificate validation (no accept-all). Message-level HMAC signing (defense in depth). |
| **Detection** | Certificate mismatch detected by client. HMAC verification failure. |
| **Response** | Connection rejected. Security event logged. |
| **Remaining risk** | Low. TLS + HMAC double protection. |

### T4: Malicious Task Injection
| Attribute | Detail |
|---|---|
| **Threat actor** | TA1 (Internet attacker), TA5 (Prompt injection) |
| **Entry point** | Task submission API, LLM-generated tool calls |
| **Affected asset** | Node filesystem, processes |
| **Attack path** | 1. Attacker submits task with malicious capability or params. 2. Task delivered to node. 3. Malicious code executes. |
| **Prevention** | Capability allowlist (node-only declared capabilities). Schema validation on all params. Risk gating (HIGH/CRITICAL require approval). Sandboxing (no shell=True, workspace-restricted, env allowlist). |
| **Detection** | Audit trail of all task submissions. Anomaly detection on task patterns. |
| **Response** | Cancel malicious task. Revoke compromised capability. |
| **Remaining risk** | Medium. Sandboxing limits damage. Allowlist prevents arbitrary capabilities. |

### T5: Workspace Escape
| Attribute | Detail |
|---|---|
| **Threat actor** | TA4 (Malicious provider), TA5 (Prompt injection), TA6 (Malicious repo) |
| **Entry point** | Task execution with file access |
| **Affected asset** | Node filesystem outside workspace |
| **Attack path** | 1. Task uses `../` paths, symlinks, or absolute paths. 2. Reads/writes files outside workspace root. 3. Exfiltrates personal files or modifies system files. |
| **Prevention** | Path validation (resolve + verify). Reject traversal, absolute paths, symlinks outside workspace. Allowed paths explicit closed list. |
| **Detection** | Path validation failure logged. Workspace snapshot diff shows unexpected paths. |
| **Response** | Task failed. Security event logged. |
| **Remaining risk** | Low. Path validation is deterministic. |

### T6: Privilege Escalation via Agent
| Attribute | Detail |
|---|---|
| **Threat actor** | TA7 (Compromised agent) |
| **Entry point** | Agent adapter |
| **Affected asset** | Node system access |
| **Attack path** | 1. Compromised agent attempts to execute capability outside its allowlist. 2. Agent tries to access files outside workspace. 3. Agent tries to escalate to administrator. |
| **Prevention** | Capability allowlist per agent. Workspace boundary per task. No administrator elevation. No `shell=True`. |
| **Detection** | Capability denial logged. Security event on allowlist violation. |
| **Response** | Agent health marked degraded. Repeated violations -> agent disabled. |
| **Remaining risk** | Medium. Agent runs with same OS user as Node daemon. Defense is capability boundary, not OS user boundary. |

### T7: Server Account Compromise
| Attribute | Detail |
|---|---|
| **Threat actor** | TA9 (Compromised server account) |
| **Entry point** | SSH, hosting provider console, OS vulnerability |
| **Affected asset** | Entire Control Plane |
| **Attack path** | 1. Attacker gains shell access to Control Plane server. 2. Reads database, credential store, audit logs. 3. Modifies task queue. 4. Issues node revocations. |
| **Prevention** | SSH key-only auth. Fail2ban. Minimal installed packages. Regular OS updates. |
| **Detection** | Audit log access logged. Unusual admin actions detected. |
| **Response** | Rotate all credentials. Restore from clean backup. Investigate entry vector. |
| **Remaining risk** | High. Server compromise = full system compromise. Mitigation is operational, not architectural. |

### T8: Dependency Supply Chain Attack
| Attribute | Detail |
|---|---|
| **Threat actor** | TA10 (Dependency compromise) |
| **Entry point** | pip install, dependency update |
| **Affected asset** | All Nous processes |
| **Attack path** | 1. Attacker publishes malicious version of a dependency. 2. Dependency is installed during update. 3. Malicious code executes within Nous process (same privileges). |
| **Prevention** | Lock files with hashes. Vendor security scanning. Review dependency changes. |
| **Detection** | Security scan on dependency updates. Behavioral anomaly detection. |
| **Response** | Rollback to known-good dependency set. Investigate compromise. |
| **Remaining risk** | High. Standard supply chain risk, not Nous-specific. |

### T9: Denial of Service
| Attribute | Detail |
|---|---|
| **Threat actor** | TA1 (Internet attacker) |
| **Entry point** | Public HTTPS/WSS endpoints |
| **Affected asset** | Control Plane availability |
| **Attack path** | 1. Attacker floods API with requests. 2. Attacker opens many WebSocket connections. 3. Attacker sends oversized messages. |
| **Prevention** | Rate limiting per IP. Connection limits. Message size limits. Reverse proxy DDoS protection. |
| **Detection** | Rate limit exceeded events. Connection spike alerts. |
| **Response** | Block offending IPs. Scale up if legitimate traffic increase. |
| **Remaining risk** | Medium. Standard DoS mitigations apply. |

### T10: Accidental High-Risk Approval
| Attribute | Detail |
|---|---|
| **Threat actor** | TA8 (Accidental user approval) |
| **Entry point** | Approval confirmation UI |
| **Affected asset** | Task execution |
| **Attack path** | 1. User is presented with HIGH-risk approval request. 2. User approves without reading scope. 3. Dangerous task executes. |
| **Prevention** | Full scope display (what, why, risks, alternatives). Confirmation delay (2s before button active). Revocable period for CRITICAL tasks. |
| **Detection** | HIGH/CRITICAL task execution logged with approval reference. |
| **Response** | Cancel task if within revocable period. |
| **Remaining risk** | Medium. UI mitigations help but cannot prevent determined user from approving. |

---

## 4. Risk Summary

| Threat | Likelihood | Impact | Risk | Priority |
|---|---|---|---|---|
| T7: Server Account Compromise | Low | Critical | **High** | Must mitigate operationally |
| T8: Dependency Supply Chain | Medium | High | **High** | Lock files + scanning |
| T2: Credential Theft from Node | Medium | High | **High** | Encrypted storage + allowlist |
| T4: Malicious Task Injection | Medium | High | **High** | Allowlist + sandboxing |
| T6: Privilege Escalation via Agent | Low | High | **Medium** | Capability boundary |
| T9: Denial of Service | Medium | Medium | **Medium** | Rate limiting |
| T10: Accidental Approval | Medium | Medium | **Medium** | UI mitigations |
| T1: Unauthorized Node Connection | Low | Medium | **Low** | Pairing flow |
| T3: Man-in-the-Middle | Low | Medium | **Low** | TLS + HMAC |
| T5: Workspace Escape | Low | Medium | **Low** | Path validation |

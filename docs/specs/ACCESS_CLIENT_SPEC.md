# Access Client Specification v1.0

> Status: Draft — Phase 0.5
> Client types, capabilities, limitations for accessing the Control Plane

---

## 1. Client Types

| Client | Release | Capability Level | Auth Method |
|---|---|---|---|
| CLI | First release | Full control | API token or local config |
| Web/PWA | First release | Full control (UI-constrained) | Login -> Bearer token |
| Mobile native | Future | Full control (UI-constrained) | Login -> Bearer token |
| Watch | Future | Read-only + limited actions | Device-paired token |

---

## 2. CLI Client

### 2.1 Capabilities
- Project management: create, list, show, pause, resume, cancel
- Task management: submit, list, show, logs, cancel, artifacts
- Node management: pair, list, show, revoke, rotate
- Agent management: list, show, health
- Approvals: list pending, approve, reject
- Inspector: all read-only views
- Server management: start, stop, status

### 2.2 Authentication
- Local config file or environment variable
- API token stored in `~/.nous/client_token` (0600)
- No login flow needed (local CLI assumes authenticated user)

### 2.3 Output Formats
- Default: human-readable table/text
- `--json`: machine-readable JSON
- `--stream`: streaming output for long-running operations

---

## 3. Web/PWA Client

### 3.1 Pages
| Page | Content |
|---|---|
| Dashboard | Project health, active sessions, recent tasks, notifications |
| Projects | List, create, detail view with milestones and work items |
| Tasks | Submit, list, filter, detail with logs and artifacts |
| Nodes | List, detail, pairing flow, revoke |
| Approvals | Pending list, approve/reject with full scope display |
| Inspector | Control Plane health, sessions, task delivery, agent execution |
| Settings | User preferences, API tokens |

### 3.2 Requirements
- All data fetched from Control Plane API (no local state beyond session token)
- Approval page MUST display: what is being approved, risk level, scope, alternatives
- Responsive (desktop-first, mobile-friendly for future)
- Dark mode support

### 3.3 Authentication
- Login page with credentials or API token
- Bearer token stored in sessionStorage (not localStorage — cleared on tab close)
- Token refresh on expiry (if refresh token available)

---

## 4. Mobile Native Client (Future)

### 4.1 Capabilities
- Same as Web/PWA, adapted for mobile screen
- Push notifications for: task completion, approval requests, node offline
- Quick actions: continue project, approve/reject

### 4.2 Limitations
- No code editing
- No complex configuration
- Reduced Inspector views (summary only)

---

## 5. Watch Client (Future)

### 5.1 Allowed Actions ONLY

| Action | Description |
|---|---|
| View status | Project status, task status, node health (summary) |
| Continue | Continue a previously defined LOW-risk task |
| Pause | Pause the current project |
| Reject | Reject a pending approval |
| Acknowledge | Mark notification as read |

### 5.2 Strictly Prohibited

| Prohibited Action | Reason |
|---|---|
| Create new tasks | Cannot define scope on watch screen |
| Modify task parameters | Cannot validate changes on watch screen |
| Approve HIGH/CRITICAL risk actions | Cannot display full scope on watch screen |
| Manage node credentials | Security-critical operation needs full UI |
| View raw secrets/credentials | Never displayed on any client |
| Initiate pairing | Requires CLI with full confirmation |

### 5.3 High-Risk Approvals
Must be performed on Web/PWA or Mobile client where full scope can be displayed:
- What action is being approved
- What the risks are
- What files/resources are affected
- What the alternatives are
- Confirmation requires explicit action (not single-tap)

---

## 6. Client Security

### 6.1 Token Storage
| Client | Storage | Lifetime |
|---|---|---|
| CLI | `~/.nous/client_token` (0600) | Until revoked |
| Web/PWA | sessionStorage | Session duration |
| Mobile | Secure storage (Keychain/Keystore) | Configurable |
| Watch | Secure storage | Until revoked |

### 6.2 Client Responsibilities
- Validate server certificate (TLS)
- Never store node credentials (only server API tokens)
- Never cache secrets or credentials in plaintext
- Clear session data on logout
- Respect server-enforced rate limits (exponential backoff on 429)

### 6.3 Client Prohibitions
- No autonomous task creation without user action
- No bypassing approval requirements
- No storing node private keys
- No direct node communication (all through Control Plane)

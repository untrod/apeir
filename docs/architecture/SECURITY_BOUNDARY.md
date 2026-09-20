# Security Boundary — Nous Runtime

> **Where trust changes. What crosses boundaries. What must be verified.**
> **Last updated:** 2026-08-28

---

## Trust Zones

```
┌─────────────────────────────────────────────────────┐
│ ZONE 0: External Network                            │
│ - Remote API providers (OpenAI, Anthropic, etc.)     │
│ - Remote nodes (peer control plane)                  │
│ - User browsers (WebView)                            │
│ TRUST: NONE — all input validated, all output gated  │
└────────────────────┬────────────────────────────────┘
                     │ TLS + API keys + HMAC
┌────────────────────▼────────────────────────────────┐
│ ZONE 1: Local Network (loopback)                    │
│ - Desktop WebView ↔ Python runtime (127.0.0.1:8770) │
│ - Python runtime ↔ nousd (127.0.0.1:8771)           │
│ - WebSocket connections (127.0.0.1:8770)            │
│ TRUST: LOW — token auth, CSP restrictions           │
└────────────────────┬────────────────────────────────┘
                     │ Session token + CORS
┌────────────────────▼────────────────────────────────┐
│ ZONE 2: Runtime Process                             │
│ - Python runtime (sidecar)                          │
│ - Agent processes (subprocesses)                    │
│ - Model gateway, governance, capability             │
│ TRUST: MEDIUM — capability-gated, sandboxed         │
└────────────────────┬────────────────────────────────┘
                     │ Effect Gate
┌────────────────────▼────────────────────────────────┐
│ ZONE 3: Kernel / Effect Boundary                    │
│ - nousd (Rust kernel daemon)                        │
│ - Journal (append-only SQLite)                      │
│ - Proof verification                                │
│ TRUST: HIGH — kernel-level, lease-gated             │
└────────────────────┬────────────────────────────────┘
                     │ OS permissions
┌────────────────────▼────────────────────────────────┐
│ ZONE 4: Host System                                 │
│ - Filesystem (%LOCALAPPDATA%\Nous)                  │
│ - Shell execution (capability-gated)                │
│ - Device control (Effect Gate)                      │
│ TRUST: FULL — OS-level, user-consented              │
└─────────────────────────────────────────────────────┘
```

## Boundary Rules

### External → Local (Z0→Z1)
- All input validated against schema
- Rate limiting: 120 req/min per IP
- CORS: loopback + `tauri://localhost` only
- CSP: connect-src restricted to 127.0.0.1:8770

### Local → Runtime (Z1→Z2)
- Session token required (64-hex, constant-time compare)
- Token is per-startup, not persistent
- Identity propagated through all downstream calls

### Runtime → Kernel (Z2→Z3)
- NKI protocol: framed JSON over TCP/UDS
- Every workload goes through admission control
- Resource leases are time-bounded
- Journal entries are append-only with checksums

### Kernel → Host (Z3→Z4)
- Effect Gate: ALL external side effects pass through
- Canonical Action → Policy Decision → Approval Binding → Effect Intent → Effector → Receipt → Commit
- High-risk actions require explicit human approval
- No shell execution without capability grant

## P0–P4 Hardening Status

1. **P0 — governed execution complete:** production gateways use NKI/Kernel by default and fail closed; direct provider execution is restricted to explicit compatibility/test callers.
2. **P0 — shell boundary complete:** Remote Agent and `brain_exec` execute only through the designated strict sandbox path; legacy local execution is disabled by default.
3. **P1 — workspace authority complete:** Python Runtime is the sole writer of `workspace.json` and `.nous/workspaces.json`; Tauri only selects/reserves the root.
4. **P2 — token hardening complete:** token files are atomically written and restricted to the current OS identity; permission failures revoke state and abort startup.
5. **P3 — Kernel readiness complete:** production Runtime API startup probes Kernel deep health before any workspace, migration, provider, or HTTP-server initialization.
6. **P4 — quality closure complete:** architecture tests, full Python tests, Desktop gates, dependency audit, and component-lock verification pass on the recorded host.

## Residual Risks and Compatibility Boundaries

- `ModelGateway(use_nki=False)` and the legacy `ExecutionSandbox` compatibility path remain available for explicit isolated compatibility/tests; product construction paths must not select them implicitly.
- The bundled sidecars target Windows ARM64. An AMD64 release requires rebuilding/staging native sidecars and updating the component lock.
- The current host lacks Visual Studio C++ Build Tools and Windows SDK libraries, so Rust link/test and Tauri native compilation must be rerun after installing that prerequisite.
- Migration checksums describe the immutable pre-development transfer snapshot and are expected to differ after P0–P4 source changes.

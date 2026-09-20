# Control Center Alignment v1.0

## Principle

One Runtime. Multiple surfaces. Same data. Same state.

CLI, Web Control Center, IDE Extension, SDK, and Mobile must all call the same Runtime API. No surface maintains its own database, own job manager, or own capability registry.

## Architecture

```
CLI (`nous`) ──────────┐
Web Control Center ────┤
IDE Extension ─────────┤
SDK (Python) ──────────┤
Mobile (Android) ──────┤
                        │
                        ▼
              ┌─────────────────┐
              │  Nous Client API │
              ├─────────────────┤
              │  REST + SSE      │
              │  /api/v1/kernel/ │
              │  /capability/    │
              │  /provider/      │
              │  /pack/          │
              │  /job/           │
              │  /trace/         │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  nousd (Daemon) │
              ├─────────────────┤
              │  Kernel         │
              │  Capability OS  │
              │  Provider Reg.  │
              │  Job System     │
              │  State Manager  │
              │  Security       │
              └─────────────────┘
```

## Current State

| Surface | Data Source | Status |
|---------|------------|--------|
| CLI (`nous`) | `nous_runtime` Python API | Yes Unified |
| Web Control Center | Direct HTTP to brain.py | Warning  Bypasses nous_runtime |
| Android App | HTTP to brain.py | Warning  Bypasses nous_runtime |
| Desktop App (Tauri) | HTTP to brain.py | Warning  Bypasses nous_runtime |

## Alignment Plan

### v1.0.0 (Current)
- CLI uses `nous_runtime` API — the canonical path
- brain.py serves as HTTP bridge for mobile/desktop
- Document the API endpoints for external consumers

### v1.1 (Next)
- Extract HTTP routes from brain.py into `nous_runtime/api/`
- Web Control Center calls `/api/v1/kernel/` endpoints
- Desktop App calls the same endpoints
- Mobile App calls the same endpoints

### v2.0 (Future)
- `nousd` daemon process serves all surfaces
- Client API library (Python, JS, Kotlin) wraps REST calls
- All surfaces use the client library, not raw HTTP

## Rules

1. No surface creates its own database
2. No surface manages its own job queue
3. No surface registers its own capabilities
4. All state changes go through the Runtime API
5. All surfaces see the same state within one polling interval

## Forbidden Patterns

```
No CLI manages jobs in local JSON
No Web has its own SQLite database
No Desktop app registers providers directly
No Mobile creates capabilities locally
No IDE bypasses the security pipeline
```

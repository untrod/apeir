# CLI Architecture v1.1

## Principle

CLI never contains business logic. CLI is a thin presentation layer over the SDK.

## Architecture

```
nous CLI (shell_v2.py)
    ↓  calls
NousClient SDK (sdk/client.py)
    ↓  calls
Runtime API (api/routes.py)
    ↓  calls
nous_core Kernel
```

## Forbidden

- CLI directly importing `brain.py` functions
- CLI directly calling `nous_core.capability.register_capability()`
- CLI managing its own job queue
- CLI creating its own database connections
- CLI bypassing the security pipeline

## Allowed

- CLI calling `client.run()`, `client.status()`, `client.list_packs()`
- CLI formatting output for the terminal
- CLI maintaining session history (local only, not Runtime state)
- CLI calling `/api/v1/*` endpoints via SDK

## Current Status

| Surface | Data Path | Status |
|---------|-----------|:------:|
| CLI (shell_v2) | CLI -> SDK -> API -> Kernel | Yes |
| CLI (main.py commands) | CLI -> SDK -> API -> Kernel | Yes |
| Web Control Center | HTTP -> brain.py | Warning  direct |
| Desktop App | HTTP -> brain.py | Warning  direct |
| Android App | HTTP -> brain.py | Warning  direct |

## Migration to SDK-only (v1.1 target)

1. All brain.py endpoints that duplicate SDK logic -> marked deprecated
2. Web Control Center -> use JS SDK client
3. Desktop App -> use JS SDK client
4. Mobile App -> use API endpoints directly (no SDK for Kotlin yet)

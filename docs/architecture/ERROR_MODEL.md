# Error Model v1.0

## Unified Error Codes

Every error returned by the Runtime uses a standardized code.

```
NOUS_OK                          — Success
NOUS_INVALID_REQUEST             — Malformed request
NOUS_CAPABILITY_NOT_FOUND        — Capability not registered
NOUS_CAPABILITY_DISABLED         — Capability is disabled
NOUS_CAPABILITY_DEPRECATED       — Capability is deprecated
NOUS_PROVIDER_NOT_FOUND          — No provider for capability
NOUS_PROVIDER_UNAVAILABLE        — Provider is down or degraded
NOUS_PROVIDER_TIMEOUT            — Provider did not respond in time
NOUS_PERMISSION_DENIED           — Insufficient permissions
NOUS_POLICY_REJECTED             — Policy blocked the request
NOUS_AUTHENTICATION_FAILED       — Invalid or missing credentials
NOUS_RATE_LIMITED                — Too many requests
NOUS_DEPENDENCY_FAILED           — A required capability failed
NOUS_EXECUTION_FAILED            — Execution completed with errors
NOUS_TIMEOUT                     — Execution exceeded time limit
NOUS_RECOVERY_FAILED             — Automatic recovery unsuccessful
NOUS_INTERNAL_ERROR              — Unexpected internal error
NOUS_NOT_IMPLEMENTED             — Feature not yet implemented
```

## Error Response Format

```json
{
  "ok": false,
  "error": {
    "code": "NOUS_PROVIDER_UNAVAILABLE",
    "message": "Provider 'openai' is currently degraded: rate limited",
    "details": {
      "provider": "openai",
      "capability": "model.reason",
      "retry_after_seconds": 30
    },
    "trace_id": "trace_20260708_a1b2c3d4"
  }
}
```

## Error Handling Rules

1. Every module uses the unified error codes
2. No bare `except: pass` in kernel code
3. Errors include trace_id for correlation
4. Provider errors are wrapped, not swallowed
5. Recovery is attempted where retryable
6. Unrecoverable errors are escalated to the caller

## Retry Policy

| Error | Retry? | Strategy |
|-------|--------|----------|
| NOUS_PROVIDER_TIMEOUT | Yes | Exponential backoff, max 3 |
| NOUS_PROVIDER_UNAVAILABLE | Yes | Exponential backoff, max 5 |
| NOUS_RATE_LIMITED | Yes | Wait for retry_after, max 3 |
| NOUS_DEPENDENCY_FAILED | Yes | Retry dependency, then retry |
| NOUS_PERMISSION_DENIED | No | Requires human intervention |
| NOUS_POLICY_REJECTED | No | Requires policy change |
| NOUS_INVALID_REQUEST | No | Fix the request |

## Deprecation Path

Existing bare `except:pass` patterns (114 found in baseline audit):
- Phase 1: Add warning logs to all bare excepts
- Phase 2: Replace with structured error handling
- Phase 3: Remove all bare excepts from kernel code

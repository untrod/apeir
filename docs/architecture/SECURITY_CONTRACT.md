# Security Contract v1.0

## Admission Pipeline

```
Request
  ↓
Identity          <- Who is making the request?
  ↓
Validation        <- Is the request well-formed?
  ↓
Authentication    <- Are they who they claim to be?
  ↓
Authorization     <- Do they have access to this resource?
  ↓
Permission        <- Does their role allow this action?
  ↓
Policy            <- Does any policy block this?
  ↓
Risk              <- What is the risk level?
  ↓
Admission         <- ALLOW | DENY | REQUIRE_APPROVAL | SANDBOX_ONLY
  ↓
Execution         <- Run with appropriate constraints
  ↓
Audit             <- Record the decision and outcome
```

## Admission Decisions

| Decision | Meaning |
|----------|---------|
| `ALLOW` | Proceed normally |
| `DENY` | Reject immediately |
| `REQUIRE_APPROVAL` | Pause until human approves |
| `SANDBOX_ONLY` | Allow but with restricted capabilities |

## Risk Levels

| Level | Auto-allow? | Requires | Example |
|-------|------------|----------|---------|
| `low` | Yes | None | `model.reason`, `rag.search` |
| `medium` | Yes | Audit log | `file.read`, `web.search` |
| `high` | No | User approval | `file.write`, `device.shell` |
| `critical` | No | Multi-party approval | `device.factory_reset`, `security.policy_change` |

## Permission Model

```yaml
permissions:
  - read:knowledge       # Read knowledge data
  - write:knowledge      # Write knowledge data
  - execute:shell        # Execute shell commands
  - execute:code         # Execute arbitrary code
  - manage:devices       # Register/modify devices
  - manage:providers     # Register/remove providers
  - manage:packs         # Install/remove packs
  - manage:security      # Modify security policies
  - access:secrets       # Read encrypted secrets
```

## Secret Handling

1. Secrets never stored in plaintext in the repository
2. Secrets never logged (auto-masked in audit)
3. Secrets loaded from environment or encrypted vault
4. Provider credentials scoped per-provider, not global

## Audit

- Every admission decision is logged
- Every capability execution is logged
- Logs are append-only, immutable
- Retention: configurable, default 90 days
- Sensitive fields auto-masked before storage

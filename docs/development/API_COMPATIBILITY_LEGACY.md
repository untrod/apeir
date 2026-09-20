# API Compatibility v1.0

## Versioning
- `/api/v1/kernel/*` — stable, breaking changes get v2
- Legacy endpoints (`/chat`, `/learn/*`) — deprecated but maintained
- New fields are additive, never remove existing fields

## Breaking Change Policy
1. Deprecate in current version (emit warning)
2. Maintain for 2 minor versions
3. Remove in next major version

## Endpoint Stability

| Endpoint | Stability |
|----------|:---:|
| `/api/v1/kernel/health` | Stable |
| `/api/v1/kernel/capabilities` | Stable |
| `/api/v1/kernel/capabilities/invoke` | Stable |
| `/api/v1/kernel/jobs` | Stable |
| `/api/v1/kernel/security` | Stable |
| `/api/v1/control/*` | Stable |
| `/chat`, `/learn/*` | Deprecated |

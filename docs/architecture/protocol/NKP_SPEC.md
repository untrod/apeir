# NKP: Nous Kernel Protocol v1.0

> For apps, web dashboards, and external systems calling the Kernel.

## Base URL

All endpoints at `/api/v1/kernel/*`

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /health | Health check |
| GET | /devices | List registered devices |
| GET | /capabilities | List all capabilities |
| GET | /providers | List registered providers |
| GET | /security | Security statistics |
| GET | /observer | Observer statistics |
| POST | /events | Submit event |
| POST | /jobs | Create or query jobs |
| POST | /capabilities/invoke | Invoke a capability |

## Auth

- Header: `Authorization: Bearer <token>`
- Or query: `?token=<token>`
- HMAC signature for write operations

## Response Format

```json
{
  "api_version": "v1",
  "result": {},
  "error_code": 0,
  "error_msg": "Success"
}
```

## Versioning

- `/api/v1/...` — stable, breaking changes get v2
- Backward compat: new fields are additive
- Old endpoints (`/chat`, `/learn/*`) continue to work but are deprecated

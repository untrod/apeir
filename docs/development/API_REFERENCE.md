# Nous Runtime API Reference v1.0

## HTTP API

Base URL: `http://{host}:8770`

### Authentication

All endpoints require `X-Auth-Token` header or `?token=` query parameter.

### Health

```
GET /health
-> {"status": "ok", "version": "1.0.0", "providers": N, ...}
```

### Kernel API (v1)

```
GET  /api/v1/kernel/health
GET  /api/v1/kernel/status
GET  /api/v1/kernel/capabilities
GET  /api/v1/kernel/providers
GET  /api/v1/kernel/jobs
POST /api/v1/kernel/capabilities/invoke
POST /api/v1/kernel/jobs
```

### Capability

```
GET  /capabilities                    # List all capabilities
POST /capability/request              # Execute a capability
POST /capability/graph/request        # Execute with dependency resolution
```

### Trace

```
GET /traces/recent?limit=10           # Recent execution traces
GET /traces/session/{id}              # Traces for a session
```

---

## Python SDK

```python
from nous_runtime.sdk import NousClient

client = NousClient(host="localhost", port=8770, token="demo")

# Runtime
client.health()
client.status()

# Capabilities
result = client.run("model.reason", prompt="Explain")
client.list_capabilities()

# Providers
client.list_providers()
client.provider_health()

# Packs
client.list_packs()
client.install_pack("./my-pack")
client.remove_pack("my-pack")

# Trace
client.trace(limit=10)
client.experience_stats(provider_id="openai")
```

## JavaScript SDK (Stub)

```javascript
// nous-client.js — coming in v1.1
const client = new NousClient({ host: "localhost", port: 8770, token: "demo" });
await client.health();
const result = await client.run("model.reason", { prompt: "Hello" });
```

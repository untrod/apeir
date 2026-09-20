# Federation Protocol v0.1

> Multi-node Nous interconnection — draft spec, not fully implemented.

## Node Identity

```json
{
  "node_id": "nous-main-01",
  "node_name": "Main Nous",
  "node_role": "coordinator",
  "version": "1.0.0",
  "public_key": "...",
  "endpoint": "<brain-host>:8770"
}
```

## Node Roles

| Role | Description |
|------|-------------|
| `coordinator` | Routes tasks, aggregates results |
| `worker` | Executes capabilities, reports back |
| `edge` | Lightweight, sensor/actuator focused |
| `storage` | Data persistence, vector DB |
| `gateway` | External API, auth boundary |

## Capability Exchange

Nodes announce capabilities on connect:
```json
{
  "node_id": "nous-learning-01",
  "capabilities": ["learning.analyze", "learning.plan", "learning.review"],
  "health": {"status": "ok", "load": 0.3}
}
```

## Task Delegation

```
coordinator -> worker: {task_id, capability, payload, deadline}
worker -> coordinator: {task_id, status, result, audit_summary}
```

## Health Heartbeat

Every 30s, each node sends:
```json
{"node_id": "...", "status": "ok", "capabilities_healthy": 12, "queue_depth": 3}
```

## Security

- All inter-node traffic over VPN tunnel or mTLS
- Nodes authenticate via public key
- Capability risk levels respected across nodes
- Audit trail includes originating node

## Future (not implemented yet)

- Task load balancing across workers
- Node auto-discovery via mDNS
- Cross-node capability graph
- Shared audit ledger

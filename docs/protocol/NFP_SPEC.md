# NFP: Nous Federation Protocol v0.1

> Multi-node Nous interconnect — draft spec.

## Node Identity

```json
{
  "node_id": "nous_main_01",
  "node_name": "Main Brain",
  "role": "coordinator",
  "version": "1.0.0",
  "public_key": "ed25519_base64...",
  "endpoint": "<brain-host>:8770"
}
```

## Message Types

HELLO — node announces presence
CAPS_EXCHANGE — share capability registry
TASK_DELEGATE — delegate a job to another node
RESULT — return delegated task result
AUDIT_SYNC — share audit summaries
HEARTBEAT — health ping

## Security

- mTLS or WireGuard for transport
- Node public key authentication
- Capability risk levels preserved across nodes
- Origin node recorded in audit trail

## Status: Draft

Full implementation deferred to P6.

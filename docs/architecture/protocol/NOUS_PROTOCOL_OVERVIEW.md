# Nous Protocol White Paper v1.0

> How Nous nodes, devices, models, tools, and modules communicate securely.

## Why Protocols

Nous is not a monolith. It's a distributed system:
- Phone calls Brain
- Brain delegates to PC Agent
- ESP32 streams sensor data
- Multiple Brain nodes federate
- Third-party developers write Skills

Without protocols, every connection is ad-hoc, fragile, and insecure.

## Protocol Layering

```
┌─────────────────────────────────────────────┐
│ NSP — Skill / Provider Protocol             │  <- 3rd-party devs
├─────────────────────────────────────────────┤
│ NFP — Federation Protocol                   │  <- multi-node
├─────────────────────────────────────────────┤
│ NEP — Edge Protocol                         │  <- devices (ESP32, Jetson)
├─────────────────────────────────────────────┤
│ NKP — Kernel Protocol                       │  <- apps, web, external
├─────────────────────────────────────────────┤
│ Unified Message Envelope (all protocols)    │  <- shared format
└─────────────────────────────────────────────┘
```

## Protocol Summary

| Protocol | Name | Audience | Transport |
|----------|------|----------|-----------|
| NKP | Nous Kernel Protocol | Apps, web, external systems | HTTP/SSE |
| NEP | Nous Edge Protocol | ESP32, STM32, Jetson, robots | WebSocket/MQTT/UART |
| NFP | Nous Federation Protocol | Multi-node interconnect | WebSocket/gRPC |
| NSP | Nous Skill/Provider Protocol | 3rd-party developers | HTTP |

## Unified Message Envelope

All protocols share one message format:

```json
{
  "protocol": "NEP",
  "version": "0.1",
  "type": "CAPS",
  "id": "msg_20260707_a1b2",
  "source": "esp32_arm_01",
  "target": "main_brain",
  "timestamp": "2026-07-07T10:00:00Z",
  "correlation_id": "corr_20260707_c3d4",
  "payload": {},
  "signature": "hmac_sha256_base64..."
}
```

## Authentication

- **NKP**: Token (HMAC compare) in header or query
- **NEP**: Device pre-shared key + HMAC signature
- **NFP**: Node public key + mutual TLS
- **NSP**: API key + capability scope

## Error Codes

| Code | Name | Meaning |
|------|------|---------|
| 0 | OK | Success |
| 1 | AUTH_FAILED | Invalid credentials |
| 2 | CAP_NOT_FOUND | Capability not registered |
| 3 | RISK_BLOCKED | Risk policy denied |
| 4 | TIMEOUT | Execution timeout |
| 5 | DEVICE_OFFLINE | Target device not reachable |
| 6 | RATE_LIMITED | Too many requests |
| 7 | INVALID_MSG | Malformed message |
| 8 | INTERNAL | Internal error |

## Versioning

- Protocol versions are `MAJOR.MINOR`
- Minor version changes are backward-compatible
- Major version changes may break compatibility
- Nodes declare supported versions in HELLO

## Compatibility

- New fields are additive (old clients ignore unknown fields)
- Deprecated fields are marked for 2 minor versions before removal
- Breaking changes require a new major protocol version

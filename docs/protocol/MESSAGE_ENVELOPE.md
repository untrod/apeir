# Unified Message Envelope

All Nous protocols share one message format:

```json
{
  "protocol": "NKP",
  "version": "0.1",
  "type": "CAP_INVOKE",
  "id": "msg_20260707_a1b2",
  "source": "phone",
  "target": "main_brain",
  "timestamp": "2026-07-07T10:00:00Z",
  "correlation_id": "corr_20260707_c3d4",
  "payload": {},
  "signature": "hmac_sha256..."
}
```

## Fields

| Field | Required | Description |
|-------|:---:|------|
| protocol | Yes | NKP, NEP, NFP, NSP |
| version | Yes | Protocol version |
| type | Yes | Message type |
| id | Yes | Unique message ID |
| source | Yes | Sender ID |
| target | Yes | Recipient ID |
| timestamp | Yes | UTC ISO-8601 |
| correlation_id | | Links related messages |
| payload | Yes | Message body |
| signature | | HMAC signature |

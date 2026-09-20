# NEP: Nous Edge Protocol v0.1

> For ESP32, STM32, Jetson, industrial controllers, robot arms — any edge device.

## Design Principles

1. **Minimal**: each message type has a clear purpose
2. **Transport-agnostic**: works over WebSocket, MQTT, UART, CAN
3. **Secure**: HMAC-signed, device pre-shared key
4. **Reliable**: ACK for critical messages, idempotent job IDs

## Message Types

### HELLO (device -> brain)
Device announces itself on connect.
```json
{
  "protocol": "NEP", "type": "HELLO",
  "source": "esp32_lab_01",
  "payload": {
    "device_type": "esp32",
    "firmware_version": "1.0.0",
    "supported_protocols": ["0.1"]
  }
}
```

### CAPS (device -> brain)
Device declares its capabilities.
```json
{
  "type": "CAPS",
  "payload": {
    "capabilities": [
      {"id": "gpio.led.set", "risk": "low", "timeout_ms": 1000},
      {"id": "sensor.temp.read", "risk": "low", "timeout_ms": 500},
      {"id": "servo.move", "risk": "high", "timeout_ms": 5000}
    ]
  }
}
```

### HEARTBEAT (device -> brain, every 30s)
```json
{"type": "HEARTBEAT", "payload": {"uptime_s": 3600, "free_heap": 123456}}
```

### JOB (brain -> device)
Brain dispatches a task.
```json
{
  "type": "JOB",
  "payload": {
    "job_id": "job_20260707_abc",
    "capability": "gpio.led.set",
    "params": {"pin": 2, "state": "on"},
    "deadline_ms": 5000
  }
}
```

### RESULT (device -> brain)
Device returns job result.
```json
{
  "type": "RESULT",
  "correlation_id": "...",
  "payload": {
    "job_id": "job_20260707_abc",
    "ok": true,
    "output": {"pin": 2, "state": "on"},
    "duration_ms": 45
  }
}
```

### ALERT (device -> brain, async)
Device reports anomaly without being asked.
```json
{
  "type": "ALERT",
  "payload": {
    "alert_type": "over_temp",
    "severity": "high",
    "value": 85.5,
    "threshold": 80.0
  }
}
```

### ACK (brain -> device)
Acknowledge receipt of critical messages.
```json
{"type": "ACK", "correlation_id": "...", "payload": {"ack_id": "msg_xxx"}}
```

### STOP (brain -> device)
Emergency stop all operations.
```json
{"type": "STOP", "payload": {"reason": "safety", "all_motors": true}}
```

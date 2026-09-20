#!/usr/bin/env python3
"""Demo 3: Edge Device Mock — simulate an ESP32 connecting to Nous via NEP."""
import json
import time
import urllib.request

BRAIN = "http://localhost:8770"
TOKEN = "your_token_here"
DEVICE_ID = "esp32_demo_01"

def send(msg):
    data = json.dumps(msg).encode()
    req = urllib.request.Request(
        f"{BRAIN}/edge/msg?token={TOKEN}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# 1. HELLO
print("ESP32 Demo: Connecting...")
r = send({
    "protocol": "NEP", "type": "HELLO",
    "source": DEVICE_ID, "target": "main_brain",
    "payload": {"device_type": "esp32", "firmware_version": "1.0.0"},
})
print(f"  HELLO: {r}")

# 2. CAPS
r = send({
    "protocol": "NEP", "type": "CAPS",
    "source": DEVICE_ID, "target": "main_brain",
    "payload": {"capabilities": [
        {"id": "gpio.led.set", "risk": "low", "timeout_ms": 1000},
        {"id": "sensor.temp.read", "risk": "low", "timeout_ms": 500},
        {"id": "servo.move", "risk": "high", "timeout_ms": 5000},
    ]},
})
print(f"  CAPS: {r}")

# 3. HEARTBEAT loop (3 cycles)
print("  Starting heartbeat...")
for i in range(3):
    r = send({
        "protocol": "NEP", "type": "HEARTBEAT",
        "source": DEVICE_ID, "target": "main_brain",
        "payload": {"uptime_s": i * 10, "free_heap": 100000 - i * 1000},
    })
    print(f"  HEARTBEAT {i+1}: {r['error_code']}")
    time.sleep(2)

# 4. Simulate sensor reading → ALERT
print("  Sensor detects over-temp!")
r = send({
    "protocol": "NEP", "type": "ALERT",
    "source": DEVICE_ID, "target": "main_brain",
    "payload": {"alert_type": "over_temp", "severity": "high",
                "value": 85.5, "threshold": 80.0},
})
print(f"  ALERT: {r}")

print("ESP32 Demo: Complete!")

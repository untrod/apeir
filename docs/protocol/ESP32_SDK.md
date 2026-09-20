# ESP32 Minimal SDK Spec v0.1

> For ESP32 / Arduino / MicroPython edge devices.

## Transport

- **Primary**: WebSocket (for WiFi-enabled devices)
- **Fallback**: MQTT (for low-power, many-device scenarios)
- **Minimal**: HTTP POST polling (for simplest integration)

## Firmware Flow

```
1. Connect WiFi
2. Open WebSocket to wss://brain:8770/edge/ws
3. Send HELLO
4. Send CAPS
5. Start HEARTBEAT (every 30s)
6. Listen for JOB messages
7. Execute -> send RESULT
8. On anomaly -> send ALERT
```

## Minimal Capabilities (v0.1)

| Capability | Risk | Timeout |
|-----------|------|---------|
| `gpio.led.set` | low | 1s |
| `gpio.led.blink` | low | 5s |
| `sensor.temp.read` | low | 500ms |
| `sensor.humidity.read` | low | 500ms |
| `servo.move` | high | 5s |
| `relay.set` | high | 1s |
| `display.text` | low | 1s |

## Arduino Sketch (pseudocode)

```cpp
#include <WiFi.h>
#include <WebSocketsClient.h>

WebSocketsClient ws;
String device_id = "esp32_lab_01";
String secret = "example-device-psk";

void setup() {
  WiFi.begin("SSID", "PASS");
  ws.begin("<brain-host>", 8770, "/edge/ws");
  ws.onEvent(handle_message);
}

void loop() {
  ws.loop();
  if (millis() - last_hb > 30000) {
    send_heartbeat();
    last_hb = millis();
  }
}

void handle_message(uint8_t *payload, size_t len) {
  json msg = json_parse(payload, len);
  if (msg["type"] == "JOB") {
    execute_job(msg["payload"]);
  } else if (msg["type"] == "STOP") {
    emergency_stop();
  }
}
```

## MicroPython Version

```python
import network, ujson, usocket

wlan = network.WLAN(network.STA_IF)
wlan.connect("SSID", "PASS")

ws = usocket.socket()
ws.connect(("<brain-host>", 8770))

def send(msg):
    ws.send(ujson.dumps(msg))

send({"protocol":"NEP","type":"HELLO","source":"esp32_01",
      "target":"main_brain","payload":{"device_type":"esp32","version":"0.1"}})

send({"protocol":"NEP","type":"CAPS","source":"esp32_01",
      "target":"main_brain","payload":{"capabilities":[
        {"id":"gpio.led.set","risk":"low","timeout_ms":1000}]}})

while True:
    # listen for JOB, execute, send RESULT
    data = ujson.loads(ws.recv(1024))
    if data.get("type") == "JOB":
        # execute capability...
        send({"protocol":"NEP","type":"RESULT","source":"esp32_01",
              "target":"main_brain","payload":{"job_id":data["payload"]["job_id"],
              "ok":True,"output":{},"duration_ms":10}})
```

## Security

- Pre-shared key per device
- HMAC signature on all messages
- Brain whitelists device public keys
- STOP message bypasses queue (immediate)

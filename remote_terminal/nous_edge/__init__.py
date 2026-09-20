# -*- coding: utf-8 -*-
"""
Nous Edge SDK — connect any device to Nous Brain.

Minimal client for Linux, PC, Jetson, Raspberry Pi. ESP32 uses a
separate C/MicroPython SDK (see docs/protocol/ESP32_SDK.md).

Usage:
  from nous_edge import EdgeClient

  client = EdgeClient(
      device_id="jetson_lab_01",
      device_type="jetson",
      brain_url="http://<brain-host>:8770",
      secret="YOUR_DEVICE_PRE_SHARED_KEY",
  )

  @client.capability("gpio.led.set")
  def set_led(pin: int, state: str):
      GPIO.output(pin, state == "on")
      return {"pin": pin, "state": state}

  @client.capability("sensor.temp.read")
  def read_temp(sensor_id: int = 0):
      return {"temperature_c": 25.5, "sensor_id": sensor_id}

  client.connect()  # HELLO → CAPS → HEARTBEAT loop → listen for JOBs
"""

from __future__ import annotations

import json as _json
import logging as _logging
import threading as _threading
import time as _time_module
from typing import Any, Callable

_log = _logging.getLogger("nous_edge")


class EdgeClient:
    """Minimal NEP client for edge devices."""

    def __init__(self, *, device_id: str, device_type: str,
                 brain_url: str, secret: str = "",
                 heartbeat_interval: float = 30.0):
        self.device_id = device_id
        self.device_type = device_type
        self.brain_url = brain_url.rstrip("/")
        self.secret = secret
        self.heartbeat_interval = heartbeat_interval

        self._capabilities: dict[str, Callable] = {}
        self._running = False
        self._thread: _threading.Thread | None = None

    # Register capabilities

    def capability(self, cap_id: str):
        """Decorator: register a function as a capability handler."""
        def wrapper(fn):
            self._capabilities[cap_id] = fn
            _log.info("Registered capability: %s", cap_id)
            return fn
        return wrapper

    def register_capability(self, cap_id: str, handler: Callable):
        """Register a capability handler function."""
        self._capabilities[cap_id] = handler

    # Lifecycle

    def connect(self):
        """Connect to Brain: HELLO → CAPS → start heartbeat loop."""
        self._running = True

        # HELLO
        hello = {
            "protocol": "NEP", "type": "HELLO",
            "source": self.device_id, "target": "main_brain",
            "payload": {"device_type": self.device_type, "version": "0.1"},
        }
        resp = self._send(hello)
        _log.info("HELLO response: %s", resp)

        # CAPS
        caps_list = [
            {"id": cid, "risk": "low", "timeout_ms": 5000}
            for cid in self._capabilities
        ]
        caps_msg = {
            "protocol": "NEP", "type": "CAPS",
            "source": self.device_id, "target": "main_brain",
            "payload": {"capabilities": caps_list},
        }
        self._send(caps_msg)
        _log.info("Declared %d capabilities", len(caps_list))

        # Start heartbeat + job listener in background
        self._thread = _threading.Thread(target=self._loop, daemon=True,
                                         name="nous-edge-loop")
        self._thread.start()

    def disconnect(self):
        """Stop the edge client."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # Send results

    def send_result(self, job_id: str, ok: bool, output: dict,
                    duration_ms: int = 0):
        """Send a job result back to Brain."""
        result = {
            "protocol": "NEP", "type": "RESULT",
            "source": self.device_id, "target": "main_brain",
            "payload": {"job_id": job_id, "ok": ok, "output": output,
                        "duration_ms": duration_ms},
        }
        self._send(result)

    def send_alert(self, alert_type: str, severity: str, value: Any,
                   threshold: Any = None):
        """Send an async alert to Brain."""
        alert = {
            "protocol": "NEP", "type": "ALERT",
            "source": self.device_id, "target": "main_brain",
            "payload": {"alert_type": alert_type, "severity": severity,
                        "value": value, "threshold": threshold},
        }
        self._send(alert)

    # Internals

    def _loop(self):
        """Background heartbeat + job polling loop."""
        import urllib.request as _ur
        while self._running:
            try:
                # Heartbeat
                hb = {
                    "protocol": "NEP", "type": "HEARTBEAT",
                    "source": self.device_id, "target": "main_brain",
                    "payload": {"uptime_s": int(_time_module.monotonic())},
                }
                self._send(hb)

                # Poll for jobs
                try:
                    req = _ur.Request(
                        f"{self.brain_url}/api/v1/kernel/jobs?token={self.secret}",
                        method="GET",
                    )
                    with _ur.urlopen(req, timeout=5) as resp:
                        data = _json.loads(resp.read())
                        for job in data.get("jobs", []):
                            if job.get("status") == "running":
                                self._execute_job(job)
                except Exception:
                    pass

            except Exception as e:
                _log.error("Edge loop error: %s", e)

            _time_module.sleep(self.heartbeat_interval)

    def _execute_job(self, job: dict):
        """Execute a job dispatched by Brain."""
        cap_id = job.get("capability", "")
        handler = self._capabilities.get(cap_id)
        if not handler:
            self.send_result(job["id"], False, {},
                             error=f"No handler for {cap_id}")
            return

        params = job.get("payload", {}).get("params", {})
        started = _time_module.time()
        try:
            output = handler(**params) if isinstance(params, dict) else handler()
            self.send_result(job["id"], True, output,
                             duration_ms=int((_time_module.time() - started) * 1000))
        except Exception as e:
            self.send_result(job["id"], False, {"error": str(e)})

    def _send(self, msg: dict) -> dict:
        """Send a message to Brain via HTTP POST."""
        import urllib.request as _ur
        try:
            data = _json.dumps(msg).encode()
            req = _ur.Request(
                f"{self.brain_url}/api/v1/kernel/capabilities/invoke",
                data=data,
                headers={"Content-Type": "application/json",
                        "Authorization": f"Bearer {self.secret}"},
                method="POST",
            )
            with _ur.urlopen(req, timeout=10) as resp:
                return _json.loads(resp.read())
        except Exception as e:
            _log.debug("Send failed (non-fatal): %s", e)
            return {}

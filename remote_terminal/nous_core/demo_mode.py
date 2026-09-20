# -*- coding: utf-8 -*-
"""
Demo Mode — run Nous without real models, devices, or data.

Enable with: export NOUS_DEMO_MODE=1

Provides mock implementations of all providers so the system
can be demonstrated without API keys or real hardware.
"""
from __future__ import annotations

import os as _os
import random as _random

DEMO_ENABLED = _os.environ.get("NOUS_DEMO_MODE") == "1"

# Mock Data

MOCK_EVENTS = [
    {"type": "brain.startup", "source": "brain", "payload": {"version": "1.0.0"}},
    {"type": "device.online", "source": "laptop", "device_id": "laptop"},
    {"type": "chat.message.received", "source": "phone", "session_id": "demo-001",
     "payload": {"model": "demo", "message_length": 42}},
]

MOCK_DEVICES = [
    {"id": "laptop", "name": "My PC", "device_type": "pc",
     "is_online": True, "capabilities": ["model.reason", "device.pc.shell"]},
    {"id": "phone", "name": "My Phone", "device_type": "phone",
     "is_online": True, "capabilities": ["phone.tap", "audio.record"]},
]

MOCK_JOBS = [
    {"type": "review_study", "status": "done", "source": "study_loop",
     "payload": {"subjects": ["math"], "action": "review"}},
    {"type": "shell_exec", "status": "pending", "source": "phone",
     "payload": {"command": "npm run build", "target_device": "laptop"}},
]

MOCK_NOTIFICATIONS = [
    {"type": "task_done", "title": "System Ready", "target_client": "desktop"},
    {"type": "study_reminder", "title": "Time to Review", "target_client": "phone"},
]

MOCK_AUDIT = [
    {"action": "command.executed", "result": "success", "actor": "demo"},
    {"action": "approval.approved", "result": "approved", "actor": "demo"},
]


class MockModelProvider:
    """Returns plausible but fake responses without any API call."""
    def invoke(self, capability_id: str, payload: dict) -> dict:
        prompt = str(payload.get("prompt", ""))[:50]
        return {
            "ok": True,
            "content": f"[Demo Mode] This is a mock response to: '{prompt}...'.\n\n"
                       f"In production, this would call a real LLM via the configured provider.",
            "model": "demo-mock",
            "usage": {"prompt_tokens": len(prompt), "completion_tokens": 30},
        }

    def health(self) -> dict:
        return {"status": "ok", "mode": "demo"}


class MockDeviceProvider:
    """Simulates device control without real hardware."""
    def invoke(self, capability_id: str, payload: dict) -> dict:
        cmd = str(payload.get("command", ""))[:40]
        return {
            "ok": True,
            "output": f"[Demo] Simulated execution: '{cmd}'\nstdout: (mock output)\n",
            "returncode": 0,
            "duration_ms": _random.randint(5, 50),
        }


class MockNotificationProvider:
    """Logs notifications instead of sending them."""
    def invoke(self, capability_id: str, payload: dict) -> dict:
        return {
            "ok": True,
            "notification_id": f"demo-{_random.randint(1000, 9999)}",
            "mode": "demo",
        }


def enable_demo_mode():
    """Activate demo mode — register mock providers, seed sample data."""
    import os
    os.environ["NOUS_DEMO_MODE"] = "1"
    global DEMO_ENABLED
    DEMO_ENABLED = True

    try:
        from .capability import register_capability
        from .devices import register_device

        # Register demo capabilities
        register_capability("demo.model.reason", category="model", provider="demo_model",
                           risk="low", description="Demo model provider")
        register_capability("demo.device.shell", category="device", provider="demo_device",
                           risk="low", description="Demo device provider")

        # Seed devices
        for d in MOCK_DEVICES:
            register_device(d["id"], name=d["name"], device_type=d["device_type"],
                          capabilities=d.get("capabilities", []))

        # Seed events
        from .events import emit_event
        for e in MOCK_EVENTS:
            emit_event(e["type"], source=e["source"], payload=e.get("payload"))

        # Seed jobs
        from .jobs import create_job, claim_job, complete_job
        for j in MOCK_JOBS:
            jid = create_job(j["type"], source=j["source"], payload=j.get("payload", {}))
            if j["status"] == "done":
                claim_job(jid)
                complete_job(jid, {"result": "demo completed"})

        # Seed notifications
        from .notifications import notify
        for n in MOCK_NOTIFICATIONS:
            notify(n["type"], title=n["title"], target_client=n["target_client"])

        # Seed audit
        from .audit import audit_log
        for a in MOCK_AUDIT:
            audit_log(a["action"], actor=a["actor"], result=a["result"])

    except Exception as e:
        import logging
        logging.getLogger("nous_core.demo").warning("Demo init: %s", e)

    return True


def is_demo_mode() -> bool:
    return DEMO_ENABLED

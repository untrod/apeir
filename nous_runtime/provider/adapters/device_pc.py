# -*- coding: utf-8 -*-
"""PC Agent Provider -device.pc.*"""

from __future__ import annotations

import logging
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.device_pc")


class PCAgentProvider(Provider):
    """Provider for PC command execution via Agent."""

    name = "pc_agent"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return [
            "device.pc.exec",
            "device.pc.screenshot",
            "device.pc.file_read",
            "device.pc.file_write",
        ]

    def invoke(self, capability_id: str, **params) -> dict:
        from remote_terminal import config
        from nous_runtime.compat.brain_exec import _exec_raw

        device_id = params.get("device_id", config.DEFAULT_DEVICE)
        command = params.get("command", "")
        if command:
            output, rc = _exec_raw(command, device_id=device_id)
            return {"ok": rc == 0, "output": output, "returncode": rc}
        return {"ok": False, "error": "No command provided"}

    def health(self) -> dict:
        try:
            from nous_runtime.compat.brain_exec import _is_device_online
            from remote_terminal import config
            online = _is_device_online(config.DEFAULT_DEVICE)
            return {"status": "ok" if online else "degraded", "online": online}
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

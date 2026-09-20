# -*- coding: utf-8 -*-
"""Android Provider -device.phone.*, device.watch.*"""

from __future__ import annotations

import logging
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.android")


class AndroidProvider(Provider):
    """Provider for phone and watch control via Android app."""

    name = "android"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return [
            "device.phone.observe",
            "device.phone.act",
            "device.phone.screenshot",
            "device.phone.info",
            "device.watch.observe",
            "device.watch.act",
        ]

    def invoke(self, capability_id: str, **params) -> dict:
        action = params.get("action", "observe")
        try:
            import remote_terminal.tools as tools_module

            if action == "observe":
                result = tools_module.handle_phone_observe(
                    {}, {}, lambda cmd: ("", -1)
                )
                output = result.output if hasattr(result, "output") else str(result)
                return {"ok": True, "ui_tree": output}
            elif action == "act":
                result = tools_module.execute_phone_act(params)
                return {"ok": True, "result": result}
            return {"ok": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        try:
            from remote_terminal import config
            import urllib.request
            host = getattr(config, "PHONE_CONTROL_HOST", "")
            if host:
                urllib.request.urlopen(f"http://{host}:8788/health", timeout=3)
                return {"status": "ok"}
            return {"status": "degraded", "error": "No phone configured"}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

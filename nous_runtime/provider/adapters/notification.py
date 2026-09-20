# -*- coding: utf-8 -*-
"""Notification Provider -notification.send."""

from __future__ import annotations

import logging
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.notification")


class NotificationProvider(Provider):
    """Provider for sending notifications to devices."""

    name = "nous_notify"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["notification.send"]

    def invoke(self, capability_id: str, **params) -> dict:
        try:
            from nous_runtime.compat.notifications import notify
            nid = notify(
                params.get("type", "capability"),
                title=params.get("title", ""),
                body=params.get("body", ""),
                target_client=params.get("target_client", ""),
                priority=int(params.get("priority", 0)),
                data=params.get("data"),
            )
            return {"ok": True, "notification_id": nid}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        return {"status": "ok"}

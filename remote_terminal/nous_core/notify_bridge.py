# -*- coding: utf-8 -*-
"""
Unified Notification Bridge — routes notifications to Desktop, Phone, Watch.

Notification types:
  task_done       → Task completed
  study_reminder  → Time to review
  approval_required → High-risk operation needs confirmation
  device_offline  → Device went offline
  system_alert    → System anomaly (memory, DB, etc.)

Each client type polls or receives via SSE:
  Desktop → polling GET /api/v1/control/notifications
  Phone   → SSE /chat/stream event: notification
  Watch   → SSE /chat/stream event: notification
"""
from __future__ import annotations

from typing import Any
from .notifications import notify as _notify


def dispatch(
    ntype: str,
    title: str,
    body: str,
    *,
    target: str = "all",  # "all", "desktop", "phone", "watch"
    priority: int = 0,
    data: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Send notification to specified targets. Returns IDs per target."""
    ids: dict[str, str] = {}

    targets = ["desktop", "phone", "watch"] if target == "all" else [target]

    for t in targets:
        nid = _notify(
            ntype, title=title, body=body,
            target_client=t, priority=priority,
            data=data,
        )
        if nid:
            ids[t] = nid

    return ids


# Pre-built notification templates
def notify_task_done(task_name: str, target: str = "all"):
    return dispatch("task_done", "✅ 任务完成", f"「{task_name}」已完成。",
                    target=target, priority=0)

def notify_study_reminder(subjects: list[str], target: str = "phone"):
    return dispatch("study_reminder", "📚 复习提醒",
                    f"该复习了：{', '.join(subjects[:3])}",
                    target=target, priority=1,
                    data={"subjects": subjects})

def notify_approval_required(operation: str, dangers: list[str], target: str = "all"):
    return dispatch("approval_required", "🔐 需要审批",
                    f"高风险操作：{operation}",
                    target=target, priority=2,
                    data={"operation": operation, "dangers": dangers})

def notify_device_offline(device_name: str, target: str = "all"):
    return dispatch("device_offline", "📴 设备离线",
                    f"「{device_name}」已断开连接。",
                    target=target, priority=1,
                    data={"device": device_name})

def notify_system_alert(message: str, target: str = "desktop"):
    return dispatch("system_alert", "⚠️ 系统告警", message,
                    target=target, priority=2)

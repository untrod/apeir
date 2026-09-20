# -*- coding: utf-8 -*-
"""DeviceProvider — reads context from the device / node runtime."""

from __future__ import annotations

import logging

from nous_runtime.context.models import ContextItem
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.types import ProviderHealth

_log = logging.getLogger("nous.context.providers.device")


class DeviceProvider:
    """Collects context items from device registrations and node runtime.

    Reads connected devices, their capabilities, and health status.
    """

    source_type: str = ContextSource.DEVICE.value

    def __init__(self, workspace_path: str = ""):
        self._workspace = workspace_path



    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        """Collect device context items."""
        items: list[ContextItem] = []
        try:
            # Try the node runtime first
            from nous_runtime.connectivity.node.runtime import NodeRuntime

            runtime = NodeRuntime()
            nodes = runtime.list_nodes()

            for node in nodes[:limit]:
                node_id = node.get("node_id", node.get("id", ""))
                node_name = node.get("name", node_id)
                node_status = node.get("status", "unknown")
                node_kind = node.get("kind", node.get("device_type", ""))

                content_parts = [f"Device: {node_name}"]
                if node_status:
                    content_parts.append(f"[{node_status}]")
                if node_kind:
                    content_parts.append(f"type={node_kind}")

                items.append(ContextItem(
                    content=" ".join(content_parts),
                    source_type=ContextSource.DEVICE.value,
                    source_id=node_id,
                    importance=0.5,
                    confidence=0.8,
                    permission="read",
                    tags=("device", node_status),
                ))

        except Exception as exc:
            _log.debug("DeviceProvider: node runtime unavailable (%s), trying legacy path", exc)
            # Fallback: try legacy compat
            try:
                from nous_runtime.compat.devices import list_devices
                devices = list_devices()
                for dev in devices[:limit]:
                    dev_id = dev.get("device_id", dev.get("id", ""))
                    items.append(ContextItem(
                        content=f"Device: {dev.get('name', dev_id)} [{dev.get('status', 'unknown')}]",
                        source_type=ContextSource.DEVICE.value,
                        source_id=dev_id,
                        importance=0.5,
                        confidence=0.7,
                        permission="read",
                        tags=("device", "legacy"),
                    ))
            except Exception:
                pass

        return items[:limit]



    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {iid: f"Device context item {iid} — sourced from node/device runtime." for iid in item_ids}

    def health(self) -> ProviderHealth:
        available = False
        item_count = 0
        error = ""
        try:
            from nous_runtime.connectivity.node.runtime import NodeRuntime
            nodes = NodeRuntime().list_nodes()
            available = True
            item_count = len(nodes)
        except Exception as exc:
            error = str(exc)
            # Fallback
            try:
                from nous_runtime.compat.devices import list_devices
                devices = list_devices()
                available = True
                item_count = len(devices)
                error = ""
            except Exception:
                pass
        return ProviderHealth(
            source=ContextSource.DEVICE.value,
            available=available,
            item_count=item_count,
            last_collected_at="",
            error=error,
        )

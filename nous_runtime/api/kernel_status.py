"""Read-only, token-safe view of the live Rust Kernel over NKI."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

_LOCK = threading.Lock()
_CACHE: tuple[float, dict[str, Any]] = (0.0, {})


async def _probe(endpoint: str, timeout: float) -> dict[str, Any]:
    from compat.nki_client import NKIClient

    client = NKIClient(endpoint)
    await asyncio.wait_for(client._connect(), timeout=timeout)
    try:
        health = await asyncio.wait_for(client.health_check(deep=True), timeout=timeout)
        try:
            metrics = await asyncio.wait_for(client.get_metrics(), timeout=timeout)
        except Exception:
            metrics = {}
        return {**health, "metrics": metrics}
    finally:
        await client.close()


def kernel_status(*, timeout: float = 0.8, cache_seconds: float = 2.0) -> dict[str, Any]:
    """Return an honest live status without exposing the NKI session token."""
    global _CACHE
    endpoint = os.environ.get("NOUS_KERNEL_ENDPOINT", "").strip()
    base = {
        "configured": bool(endpoint),
        "connected": False,
        "ready": False,
        "state": "UNCONFIGURED" if not endpoint else "UNREACHABLE",
        "runtime_version": "",
        "journal_sequence": 0,
        "active_operations": 0,
        "node": {},
        "error": "",
    }
    if not endpoint:
        return base
    now = time.monotonic()
    with _LOCK:
        cached_at, cached = _CACHE
        if cached and now - cached_at < cache_seconds:
            return dict(cached)
        try:
            payload = asyncio.run(_probe(endpoint, timeout))
            node = payload.get("node") if isinstance(payload.get("node"), dict) else {}
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            state = str(payload.get("state") or "UNKNOWN").upper()
            connected = str(node.get("connection") or "").upper() == "CONNECTED"
            result = {
                **base,
                "connected": connected,
                "ready": connected and state == "READY",
                "state": state,
                "runtime_version": str(payload.get("runtime_version") or ""),
                "journal_sequence": int(payload.get("journal_sequence") or metrics.get("journal_sequence") or 0),
                "active_operations": int(metrics.get("active_operations") or 0),
                "node": node,
            }
        except Exception as exc:
            result = {**base, "error": f"{type(exc).__name__}: {exc}"}
        _CACHE = (now, result)
        return dict(result)


__all__ = ["kernel_status"]

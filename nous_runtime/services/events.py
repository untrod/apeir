"""Event query service used by SDK and diagnostics surfaces."""

from __future__ import annotations

from typing import Any


def list_events(limit: int = 20, event_type: str = "") -> list[dict[str, Any]]:
    """List recent runtime events."""
    try:
        from nous_runtime.compat.events import list_events as _list_events

        return _list_events(limit=limit, event_type=event_type)
    except TypeError:
        try:
            from nous_runtime.compat.events import list_events as _list_events

            return _list_events(limit=limit)
        except Exception:
            return []
    except Exception:
        return []


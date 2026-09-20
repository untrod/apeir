# -*- coding: utf-8 -*-
"""
nous_core time utilities.

All timestamps are UTC ISO-8601 strings (e.g. "2026-07-06T14:30:00Z").
We use strings, not floats, for readability and cross-platform determinism.
"""

from __future__ import annotations

import time as _time
from datetime import datetime as _dt
from datetime import timezone as _tz


def utc_now() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return _dt.now(tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_epoch() -> float:
    """Return current UTC time as Unix epoch seconds (for internal calculations)."""
    return _time.time()


def parse_iso(ts: str) -> float:
    """
    Parse an ISO-8601 timestamp string back to epoch seconds.
    Returns 0.0 on parse failure (never throws).
    """
    if not ts:
        return 0.0
    try:
        # Handle both "Z" and "+00:00" suffixes
        ts = ts.replace("Z", "+00:00")
        return _dt.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0

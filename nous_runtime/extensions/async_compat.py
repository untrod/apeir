"""Asyncio compatibility used by optional extension transports."""

from __future__ import annotations

try:
    from asyncio import timeout
except ImportError:  # Python 3.10
    from async_timeout import timeout

__all__ = ["timeout"]

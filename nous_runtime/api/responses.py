"""Stable API response envelopes shared by route modules."""

from __future__ import annotations

from typing import Any


def ok_response(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data}


def err_response(code: str, message: str, details: dict | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "details": details or {}},
    }
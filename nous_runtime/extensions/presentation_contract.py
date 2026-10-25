"""Data-only Studio contributions. A descriptor cannot grant data or execution access."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from nous_runtime.schema_registry import STUDIO_UI_SCHEMA_VERSION

FIELDS = frozenset(
    {
        "running",
        "version",
        "providers",
        "capabilities",
        "devices",
        "events",
        "jobs_pending",
        "kernel_state",
        "kernel_ready",
    }
)
SOURCES = frozenset({"runtime.status", "runtime.lifecycle"})
EVENTS = frozenset({"runtime.started", "runtime.stopped"})
_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def component_type(extension_id: str, local_id: str) -> str:
    return f"ui:{hashlib.sha256(extension_id.encode()).hexdigest()[:32]}:{local_id}"


def _object(value: Any, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ValueError("Unsupported or missing Studio contribution field")
    return value


def _text(value: Any, limit: int = 128, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or "\x00" in value
    ):
        raise ValueError("Invalid Studio contribution text")
    return value


def _view(value: Any, subscriptions: set[str], depth: int = 0) -> None:
    if depth > 2:
        raise ValueError("Studio view nesting exceeds two levels")
    view = _object(
        value,
        {
            "kind",
            "label",
            "text",
            "source",
            "field",
            "fields",
            "children",
            "action",
            "params",
        },
        {"kind"},
    )
    kind = view["kind"]
    common = {"kind", "label"}
    if "label" in view:
        _text(view["label"], 64)
    if kind == "text":
        _object(view, common | {"text"}, {"kind", "text"})
        _text(view["text"], 2048)
    elif kind == "stack":
        _object(view, common | {"children"}, {"kind", "children"})
        children = view["children"]
        if not isinstance(children, list) or not 1 <= len(children) <= 12:
            raise ValueError("Studio stack requires 1–12 children")
        for child in children:
            _view(child, subscriptions, depth + 1)
    elif kind in {"metric", "status", "chart", "table"}:
        _object(view, common | {"source", "field", "fields"}, {"kind", "source"})
        if view["source"] not in subscriptions:
            raise ValueError("Studio view source is not declared")
        if kind == "table":
            if (
                "field" in view
                or not isinstance(view.get("fields"), list)
                or not 1 <= len(view["fields"]) <= 12
            ):
                raise ValueError("Studio table requires bounded fields")
            for field in view["fields"]:
                _object(field, {"field", "label"}, {"field", "label"})
                if field["field"] not in FIELDS:
                    raise ValueError("Unsupported Studio data field")
                _text(field["label"], 64)
        elif view.get("field") not in FIELDS or "fields" in view:
            raise ValueError("Unsupported Studio data field")
        if view["source"] != "runtime.status":
            raise ValueError("Only sanitized Runtime status binds view values")
    elif kind == "action":
        _object(
            view, common | {"action", "params"}, {"kind", "label", "action", "params"}
        )
        if view["action"] != "workflow.run":
            raise ValueError("Unsupported governed Studio action")
        params = _object(
            view["params"],
            {"workflow_id", "version", "inputs"},
            {"workflow_id", "version"},
        )
        for key in ("workflow_id", "version"):
            if not isinstance(params[key], str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", params[key]
            ):
                raise ValueError("Invalid original Workflow reference")
        if not isinstance(params.get("inputs", {}), dict):
            raise ValueError("Workflow inputs must be an object")

        def inputs(value, level=0):
            if level > 10:
                raise ValueError("Studio action input nesting exceeds bounds")
            if isinstance(value, dict):
                for key, item in value.items():
                    if not isinstance(key, str) or key.startswith("_"):
                        raise ValueError("Reserved Workflow action input")
                    inputs(item, level + 1)
            elif isinstance(value, list):
                for item in value:
                    inputs(item, level + 1)

        inputs(params.get("inputs", {}))
    else:
        raise ValueError("Unsupported Studio view; executable JavaScript is BLOCKED")


def validate_presentation(value: Any) -> dict:
    """Validate the public declarative profile, without code or network evaluation."""
    data = _object(value, {"schema", "contributions"}, {"schema", "contributions"})
    if data["schema"] != STUDIO_UI_SCHEMA_VERSION:
        raise ValueError("Unsupported Studio UI schema")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 64 * 1024:
        raise ValueError("Studio contributions exceed 64 KiB")
    contributions = data["contributions"]
    if not isinstance(contributions, list) or not 1 <= len(contributions) <= 16:
        raise ValueError("Studio requires 1–16 contributions")
    ids = set()
    for contribution in contributions:
        item = _object(
            contribution,
            {"id", "kind", "title", "description", "subscriptions", "events", "view"},
            {"id", "kind", "title", "view"},
        )
        if (
            not isinstance(item["id"], str)
            or not _ID.fullmatch(item["id"])
            or item["id"] in ids
        ):
            raise ValueError("Invalid or duplicate Studio contribution ID")
        ids.add(item["id"])
        if item["kind"] not in {"panel", "widget"}:
            raise ValueError("Unsupported Studio contribution kind")
        _text(item["title"], 64)
        _text(item.get("description", ""), 1024, empty=True)
        subscriptions = item.get("subscriptions", [])
        if (
            not isinstance(subscriptions, list)
            or any(
                not isinstance(source, str) or source not in SOURCES
                for source in subscriptions
            )
            or len(subscriptions) != len(set(subscriptions))
        ):
            raise ValueError("Unsupported or duplicate Studio subscription")
        events = item.get("events", [])
        if (
            not isinstance(events, list)
            or any(
                not isinstance(event, str) or event not in EVENTS for event in events
            )
            or len(events) != len(set(events))
        ):
            raise ValueError("Unsupported or duplicate Studio event")
        if events and "runtime.lifecycle" not in subscriptions:
            raise ValueError("Studio event source must be declared")
        _view(item["view"], set(subscriptions))

        def action_count(view):
            return int(view["kind"] == "action") + sum(
                action_count(child) for child in view.get("children", [])
            )

        if action_count(item["view"]) > 1:
            raise ValueError("A contribution may declare only one governed action")
    return data

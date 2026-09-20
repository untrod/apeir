# -*- coding: utf-8 -*-
"""
Unified Observation Layer — standardized tool execution output.

Every tool/capability execution produces an Observation.  This is the
single contract between the Tool layer and everything downstream:
Context Builder, LLM, Trace, Memory, and future Task Graph.

Schema versioning ensures forward/backward compatibility as the
observation format evolves.

Design rule:
    No downstream consumer should receive a raw unstructured dict
    from a tool.  Everything goes through Observation.
"""

from __future__ import annotations

import json as _json
import re as _re
import uuid as _uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from nous_runtime.schema_registry import OBSERVATION_SCHEMA_VERSION as SCHEMA_VERSION

_PATH_KEYS = {
    "absolute_path",
    "base_path",
    "cwd",
    "path",
    "root",
    "workspace",
    "workspace_path",
}
_WINDOWS_ABS_RE = _re.compile(r"^[A-Za-z]:[\\/]")


@dataclass
class Observation:
    """Standardised output from any tool or capability execution.

    Attributes:
        schema_version: Semantic version of this schema ("1.0").
        observation_id: Unique ID for this observation instance.
        tool: Tool name that produced this (e.g. "project.scan").
        capability: Resolved capability used (e.g. "model.reason").
        status: "success", "failed", or "skipped".
        data: Structured result payload — keys are tool-defined,
              values are JSON-serialisable primitives.
        errors: List of error strings (empty on success).
        duration_ms: Wall-clock execution time in milliseconds.
        started_at: ISO-8601 UTC start timestamp.
        finished_at: ISO-8601 UTC finish timestamp.
        metadata: Arbitrary key-value annotations (tool version,
                  workspace path, provider info, etc.).
    """

    schema_version: str = SCHEMA_VERSION
    observation_id: str = ""
    tool: str = ""
    capability: str = ""
    status: str = "success"        # success | failed | skipped
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.observation_id:
            self.observation_id = _uuid.uuid4().hex[:12]
        now = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.started_at:
            self.started_at = now
        if not self.finished_at:
            self.finished_at = now

    # factory helpers

    @classmethod
    def success(
        cls, tool: str, data: dict[str, Any], *,
        capability: str = "", duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> Observation:
        """Create a successful observation."""
        return cls(
            tool=tool, capability=capability or tool,
            status="success", data=data,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls, tool: str, errors: list[str], *,
        capability: str = "", duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> Observation:
        """Create a failed observation."""
        return cls(
            tool=tool, capability=capability or tool,
            status="failed", errors=errors,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    @classmethod
    def skipped(
        cls, tool: str, reason: str = "", *,
        capability: str = "",
    ) -> Observation:
        """Create a skipped observation."""
        return cls(
            tool=tool, capability=capability or tool,
            status="skipped",
            errors=[reason] if reason else [],
        )

    # serialisation

    def to_dict(self) -> dict[str, Any]:
        """Full dict representation (for JSON consumers)."""
        return asdict(self)

    def to_json(self) -> str:
        """Compact JSON string."""
        return _json.dumps(self.to_dict(), ensure_ascii=False)

    def summary(self) -> dict[str, Any]:
        """Lightweight summary for trace / memory / timeline."""
        return {
            "id": self.observation_id,
            "tool": self.tool,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "data_keys": list(self.data.keys()) if self.data else [],
            "error_count": len(self.errors),
        }

    def to_context_block(self) -> str:
        """Render as a structured text block for LLM context assembly.

        The LLM sees a clean, predictable format regardless of which
        tool produced the observation.
        """
        if self.status == "success":
            data_text = _json.dumps(
                _context_safe_data(self.data),
                ensure_ascii=False,
                indent=2,
            )
            return (
                f"[Observation {self.observation_id}]\n"
                f"Tool: {self.tool}\n"
                f"Status: success\n"
                f"Duration: {self.duration_ms:.0f}ms\n"
                f"Data:\n{data_text}"
            )
        elif self.status == "failed":
            return (
                f"[Observation {self.observation_id}]\n"
                f"Tool: {self.tool}\n"
                f"Status: failed\n"
                f"Errors: {', '.join(self.errors)}"
            )
        else:
            return (
                f"[Observation {self.observation_id}]\n"
                f"Tool: {self.tool}\n"
                f"Status: skipped"
            )


def _context_safe_data(value: Any, key: str = "") -> Any:
    """Return a copy safe to include in LLM context."""
    if isinstance(value, dict):
        return {k: _context_safe_data(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_context_safe_data(item, key) for item in value]
    if isinstance(value, tuple):
        return [_context_safe_data(item, key) for item in value]
    if isinstance(value, str) and key.lower() in _PATH_KEYS and _is_absolute_path(value):
        return "<redacted-path>"
    return value


def _is_absolute_path(value: str) -> bool:
    return value.startswith("/") or value.startswith("\\\\") or bool(_WINDOWS_ABS_RE.match(value))

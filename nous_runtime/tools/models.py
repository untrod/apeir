"""Canonical discovery projection for executable Runtime tools."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


_EFFECT_CLASSES = {"none", "read", "write", "execute", "network", "unknown"}
_AVAILABILITY = {"available", "unavailable"}


@dataclass(frozen=True)
class ToolDefinition:
    """Tool metadata used for discovery, never an authorization grant."""

    tool_id: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    capability_id: str = "tool.invoke"
    category: str = "other"
    effect_class: str = "unknown"
    execution_backend: str = "runtime"
    timeout_seconds: int = 60
    requires_network: bool = False
    requires_filesystem: bool = False
    approval_policy: str = "runtime_policy"
    availability: str = "available"
    unavailable_reason: str = ""
    source: str = "builtin"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.tool_id):
            raise ValueError(f"invalid model-facing tool_id: {self.tool_id}")
        if not self.description.strip():
            raise ValueError(f"tool description is required: {self.tool_id}")
        if self.effect_class not in _EFFECT_CLASSES:
            raise ValueError(f"invalid effect class: {self.effect_class}")
        if self.availability not in _AVAILABILITY:
            raise ValueError(f"invalid tool availability: {self.availability}")
        if self.timeout_seconds < 1:
            raise ValueError("tool timeout must be positive")

    def summary(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "description": self.description,
            "capability_id": self.capability_id,
            "category": self.category,
            "effect_class": self.effect_class,
            "execution_backend": self.execution_backend,
            "requires_network": self.requires_network,
            "requires_filesystem": self.requires_filesystem,
            "approval_policy": self.approval_policy,
            "availability": self.availability,
            "unavailable_reason": self.unavailable_reason,
            "source": self.source,
            "metadata": {**dict(self.metadata), "authority": "none"},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "timeout_seconds": self.timeout_seconds,
        }

    def model_specification(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_id,
                "description": self.description,
                "parameters": dict(self.input_schema),
            },
        }


__all__ = ["ToolDefinition"]

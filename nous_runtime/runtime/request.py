"""Unified Runtime request model."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.core.errors import ConfigurationError


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class RuntimeRequest:
    user_input: str
    workspace: str = ""
    session: str = ""
    user_id: str = "local"
    constraints: dict[str, Any] = field(default_factory=dict)
    authorization_context: dict[str, Any] = field(default_factory=dict)
    governance_surface: str = "local_cli"
    request_id: str = ""
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.user_input.strip():
            raise ConfigurationError("user_input is required")
        if not self.request_id:
            seed = f"{self.user_id}:{self.session}:{self.workspace}:{self.user_input}:{self.created_at}"
            object.__setattr__(self, "request_id", hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

"""Unified Runtime request model."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, replace
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
    authenticated_context: Any = field(default=None, repr=False, compare=False)
    workspace_file_refs: tuple[Any, ...] = field(default=(), kw_only=True)
    _selected_input: Any = field(default=None, init=False, repr=False, compare=False)
    request_id: str = ""
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        from nous_runtime.context.selected_input import (
            MAX_REFERENCES,
            WorkspaceFileReference,
            SelectedInputError,
        )

        if (
            not isinstance(self.workspace_file_refs, (list, tuple))
            or len(self.workspace_file_refs) > MAX_REFERENCES
        ):
            raise SelectedInputError("invalid_reference_count")
        refs = tuple(
            ref
            if isinstance(ref, WorkspaceFileReference)
            else WorkspaceFileReference.from_mapping(ref)
            for ref in self.workspace_file_refs
        )
        if len({ref.path for ref in refs}) != len(refs):
            raise SelectedInputError("invalid_reference_count")
        object.__setattr__(self, "workspace_file_refs", refs)
        if not self.user_input.strip():
            raise ConfigurationError("user_input is required")
        if not self.request_id:
            seed = f"{self.user_id}:{self.session}:{self.workspace}:{self.user_input}:{self.created_at}"
            object.__setattr__(
                self,
                "request_id",
                hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16],
            )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(
            replace(self, authenticated_context=None, workspace_file_refs=())
        )
        result.pop("authenticated_context", None)
        result.pop("_selected_input", None)
        result["workspace_file_refs"] = [
            {"source_id": ref.source_id, "source_version": ref.sha256}
            for ref in self.workspace_file_refs
        ]
        return result

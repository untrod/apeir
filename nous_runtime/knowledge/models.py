"""User-owned Knowledge Library contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class KnowledgeLibrary:
    workspace_id: str
    owner_id: str
    name: str
    library_id: str = field(default_factory=lambda: new_id("lib"))
    active_generation: str = ""


@dataclass(frozen=True)
class KnowledgeDocument:
    library_id: str
    logical_source: str
    checksum: str
    content: str
    document_id: str = field(default_factory=lambda: new_id("doc"))
    modified_ns: int = 0
    duplicate_of: str = ""
    deleted: bool = False


@dataclass(frozen=True)
class KnowledgeResult:
    library_id: str
    document_id: str
    logical_source: str
    chunk_id: str
    relevance: float
    citation_snippet: str
    index_generation: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)
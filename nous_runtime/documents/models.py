"""Versioned, bounded intermediate representation for professional documents."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from nous_runtime.schema_registry import DOCUMENT_SCHEMA_VERSION as SCHEMA_VERSION
_ID = re.compile(r"^doc_[a-f0-9]{32}$")
_BLOCK_KINDS = {
    "paragraph", "heading", "bullet_list", "numbered_list", "table",
    "code", "citation", "page_break",
}
_MAX_BLOCKS = 500
_MAX_TEXT_CHARS = 500_000
_MAX_TABLE_ROWS = 200
_MAX_TABLE_COLUMNS = 20


class DocumentValidationError(ValueError):
    """Raised when untrusted Document IR violates the public contract."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clean_text(value: Any, *, name: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if required and not text:
        raise DocumentValidationError(f"{name} is required")
    if len(text) > maximum:
        raise DocumentValidationError(f"{name} exceeds {maximum} characters")
    return text


@dataclass(frozen=True)
class DocumentBlock:
    kind: str
    text: str = ""
    level: int = 1
    items: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    language: str = ""
    source_id: str = ""
    snapshot_id: str = ""
    url: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DocumentBlock":
        if not isinstance(value, Mapping):
            raise DocumentValidationError("each block must be an object")
        kind = _clean_text(value.get("kind"), name="block.kind", maximum=32, required=True).lower()
        if kind not in _BLOCK_KINDS:
            raise DocumentValidationError(f"unsupported block kind: {kind}")
        text = _clean_text(value.get("text"), name="block.text", maximum=50_000)
        level = int(value.get("level") or 1)
        if kind == "heading" and level not in {1, 2, 3}:
            raise DocumentValidationError("heading level must be 1, 2, or 3")
        raw_items = value.get("items") or []
        if not isinstance(raw_items, (list, tuple)) or len(raw_items) > 200:
            raise DocumentValidationError("list items must be an array with at most 200 entries")
        items = tuple(_clean_text(item, name="list item", maximum=5_000, required=True) for item in raw_items)
        raw_rows = value.get("rows") or []
        if not isinstance(raw_rows, (list, tuple)) or len(raw_rows) > _MAX_TABLE_ROWS:
            raise DocumentValidationError(f"table rows must contain at most {_MAX_TABLE_ROWS} entries")
        rows: list[tuple[str, ...]] = []
        width = 0
        for raw_row in raw_rows:
            if not isinstance(raw_row, (list, tuple)) or not raw_row or len(raw_row) > _MAX_TABLE_COLUMNS:
                raise DocumentValidationError(f"each table row must have 1-{_MAX_TABLE_COLUMNS} cells")
            row = tuple(_clean_text(cell, name="table cell", maximum=10_000) for cell in raw_row)
            width = width or len(row)
            if len(row) != width:
                raise DocumentValidationError("all table rows must have the same number of cells")
            rows.append(row)
        if kind in {"paragraph", "heading", "code", "citation"} and not text:
            raise DocumentValidationError(f"{kind} blocks require text")
        if kind in {"bullet_list", "numbered_list"} and not items:
            raise DocumentValidationError(f"{kind} blocks require items")
        if kind == "table" and not rows:
            raise DocumentValidationError("table blocks require rows")
        return cls(
            kind=kind, text=text, level=level, items=items, rows=tuple(rows),
            language=_clean_text(value.get("language"), name="language", maximum=64),
            source_id=_clean_text(value.get("source_id"), name="source_id", maximum=128),
            snapshot_id=_clean_text(value.get("snapshot_id"), name="snapshot_id", maximum=128),
            url=_clean_text(value.get("url"), name="url", maximum=2_048),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind}
        if self.text:
            result["text"] = self.text
        if self.kind == "heading":
            result["level"] = self.level
        if self.items:
            result["items"] = list(self.items)
        if self.rows:
            result["rows"] = [list(row) for row in self.rows]
        for name in ("language", "source_id", "snapshot_id", "url"):
            value = getattr(self, name)
            if value:
                result[name] = value
        return result


@dataclass(frozen=True)
class DocumentIR:
    title: str
    blocks: tuple[DocumentBlock, ...]
    document_id: str = field(default_factory=lambda: f"doc_{uuid.uuid4().hex}")
    subtitle: str = ""
    author: str = "Nous"
    language: str = "zh-CN"
    preset: str = "standard_business_brief"
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=_timestamp)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, new_identity: bool = False) -> "DocumentIR":
        if not isinstance(value, Mapping):
            raise DocumentValidationError("document must be an object")
        raw_blocks = value.get("blocks") or []
        if not isinstance(raw_blocks, (list, tuple)) or not raw_blocks or len(raw_blocks) > _MAX_BLOCKS:
            raise DocumentValidationError(f"blocks must contain 1-{_MAX_BLOCKS} entries")
        blocks = tuple(DocumentBlock.from_mapping(item) for item in raw_blocks)
        text_size = sum(len(json.dumps(block.to_dict(), ensure_ascii=False)) for block in blocks)
        if text_size > _MAX_TEXT_CHARS:
            raise DocumentValidationError(f"document content exceeds {_MAX_TEXT_CHARS} characters")
        document_id = f"doc_{uuid.uuid4().hex}" if new_identity else str(value.get("document_id") or f"doc_{uuid.uuid4().hex}")
        if not _ID.fullmatch(document_id):
            raise DocumentValidationError("document_id is invalid")
        preset = _clean_text(value.get("preset") or "standard_business_brief", name="preset", maximum=64)
        if preset not in {"standard_business_brief", "compact_reference_guide", "narrative_proposal"}:
            raise DocumentValidationError("unsupported document preset")
        schema = str(value.get("schema_version") or SCHEMA_VERSION)
        if schema != SCHEMA_VERSION:
            raise DocumentValidationError(f"unsupported schema_version: {schema}")
        return cls(
            document_id=document_id,
            title=_clean_text(value.get("title"), name="title", maximum=300, required=True),
            subtitle=_clean_text(value.get("subtitle"), name="subtitle", maximum=500),
            author=_clean_text(value.get("author") or "Nous", name="author", maximum=200),
            language=_clean_text(value.get("language") or "zh-CN", name="language", maximum=32),
            preset=preset,
            schema_version=schema,
            created_at=str(value.get("created_at") or _timestamp()),
            blocks=blocks,
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "author": self.author,
            "language": self.language,
            "preset": self.preset,
            "created_at": self.created_at,
            "blocks": [block.to_dict() for block in self.blocks],
        }
        if include_digest:
            result["sha256"] = self.digest()
        return result

    def digest(self) -> str:
        payload = json.dumps(self.to_dict(include_digest=False), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
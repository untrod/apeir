# -*- coding: utf-8 -*-
"""Persistent source registry for external research evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from nous_runtime.locking import file_lock


class SourceType(str, Enum):
    WEB_PAGE = "web_page"
    ACADEMIC_PAPER = "academic_paper"
    DOCUMENTATION = "documentation"
    CODE_REPOSITORY = "code_repository"
    API_RESPONSE = "api_response"
    DATASET = "dataset"
    NEWS_ARTICLE = "news_article"
    BLOG_POST = "blog_post"
    GOVERNMENT = "government"
    UNKNOWN = "unknown"


class TrustTier(str, Enum):
    VERIFIED = "verified"
    TRUSTED = "trusted"
    UNKNOWN = "unknown"
    UNTRUSTED = "untrusted"
    BLOCKED = "blocked"


@dataclass
class SourceRecord:
    source_id: str = ""
    url: str = ""
    title: str = ""
    publisher: str = ""
    author: str = ""
    publication_time: str = ""
    retrieval_time: str = ""
    retrieved_at: str = ""
    content_hash: str = ""
    mime_type: str = ""
    source_type: SourceType = SourceType.UNKNOWN
    trust_tier: TrustTier = TrustTier.UNKNOWN
    license: str = ""
    freshness_class: str = "daily"
    snapshot_location: str = ""
    snapshot_artifact_id: str = ""
    extraction_method: str = ""
    injection_risk: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["source_type"] = self.source_type.value
        values["trust_tier"] = self.trust_tier.value
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "SourceRecord":
        data = dict(values)
        try:
            data["source_type"] = SourceType(str(data.get("source_type") or SourceType.UNKNOWN.value))
        except ValueError:
            data["source_type"] = SourceType.UNKNOWN
        try:
            data["trust_tier"] = TrustTier(str(data.get("trust_tier") or TrustTier.UNKNOWN.value))
        except ValueError:
            data["trust_tier"] = TrustTier.UNKNOWN
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in allowed})


class SourceRegistry:
    """Thread-safe source authority with optional atomic JSON persistence."""

    def __init__(self, storage_path: str | Path = "") -> None:
        self._sources: dict[str, SourceRecord] = {}
        self._url_index: dict[str, str] = {}
        self._lock = threading.RLock()
        self._path = Path(storage_path).expanduser().resolve() if storage_path else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def register(self, record: SourceRecord) -> str:
        if not isinstance(record, SourceRecord):
            raise TypeError("record must be a SourceRecord")
        with self._lock:
            if not record.source_id:
                record.source_id = f"src_{uuid.uuid4().hex[:12]}"
            timestamp = record.retrieved_at or record.retrieval_time or _utc_now()
            record.retrieved_at = timestamp
            record.retrieval_time = timestamp
            if not record.content_hash and record.url:
                record.content_hash = hashlib.sha256(record.url.encode("utf-8")).hexdigest()
            self._sources[record.source_id] = record
            if record.url:
                self._url_index[record.url] = record.source_id
            self._persist()
            return record.source_id

    def get(self, source_id: str) -> SourceRecord | None:
        with self._lock:
            return self._sources.get(str(source_id))

    def get_by_url(self, url: str) -> SourceRecord | None:
        with self._lock:
            source_id = self._url_index.get(str(url))
            return self._sources.get(source_id) if source_id else None

    def query(
        self,
        *,
        trust_tier: TrustTier | None = None,
        source_type: SourceType | None = None,
        limit: int = 200,
    ) -> list[SourceRecord]:
        with self._lock:
            results = list(self._sources.values())
        if trust_tier:
            results = [record for record in results if record.trust_tier == trust_tier]
        if source_type:
            results = [record for record in results if record.source_type == source_type]
        results.sort(key=lambda record: record.retrieved_at or record.retrieval_time, reverse=True)
        return results[: max(1, min(int(limit), 1000))]

    def block_source(self, source_id: str) -> None:
        with self._lock:
            source = self._sources.get(str(source_id))
            if source:
                source.trust_tier = TrustTier.BLOCKED
                self._persist()

    def count(self) -> int:
        with self._lock:
            return len(self._sources)

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            with file_lock(str(self._path) + ".lock"):
                values = json.loads(self._path.read_text(encoding="utf-8"))
            records = values.get("sources", []) if isinstance(values, dict) else values
            for value in records:
                if not isinstance(value, dict):
                    continue
                record = SourceRecord.from_dict(value)
                if not record.source_id:
                    continue
                self._sources[record.source_id] = record
                if record.url:
                    self._url_index[record.url] = record.source_id
        except (OSError, ValueError, TypeError):
            self._sources.clear()
            self._url_index.clear()

    def _persist(self) -> None:
        if self._path is None:
            return
        payload = {
            "schema_version": "1.0",
            "sources": [record.to_dict() for record in self._sources.values()],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=".sources-", dir=self._path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            with file_lock(str(self._path) + ".lock"):
                os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

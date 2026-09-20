"""Python implementations of the ContextPage contract.

Page Types (from spec/context-address-space/v1alpha/):
  - TokenPage: Raw token sequences with position metadata
  - SemanticPage: High-level semantic representations
  - RetrievalPage: Search/retrieval results
  - ToolResultPage: Tool execution outputs
  - ArtifactPage: Generated artifacts (code, documents, images)
  - SummaryPage: Compressed/abstracted context
  - EvidencePage: Proof-carrying execution evidence
  - KVPage: Key-value state storage
  - CheckpointPage: Process state snapshots
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PageType(Enum):
    """Versioned context page types."""
    TOKEN = "token"
    SEMANTIC = "semantic"
    RETRIEVAL = "retrieval"
    TOOL_RESULT = "tool_result"
    ARTIFACT = "artifact"
    SUMMARY = "summary"
    EVIDENCE = "evidence"
    KV = "kv"
    CHECKPOINT = "checkpoint"


class StorageTier(Enum):
    """Storage tier for page placement."""
    RAM = "ram"        # Hot — immediate access
    NVME = "nvme"      # Warm — fast disk
    REMOTE = "remote"  # Cold — network access


class ConsistencyLevel(Enum):
    """Page consistency guarantees."""
    STRONG = "strong"          # Always consistent
    EVENTUAL = "eventual"      # Eventually consistent
    STALE_READ_OK = "stale"    # Stale reads acceptable


@dataclass
class ContextPage:
    """Base context page matching the shared ContextPage contract.

    Each page is an immutable, content-addressed unit of agent context.
    Pages can be paged in/out, shared across processes, and tiered
    across RAM/NVMe/Remote storage.
    """
    page_id: str
    page_type: PageType
    content_hash: str = ""
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    storage_tier: StorageTier = StorageTier.RAM
    size_bytes: int = 0
    permissions: str = "rw"  # rw, r, shared-read
    owner_process_id: str | None = None
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_hash(self, content: bytes) -> str:
        """Content-address the page."""
        return hashlib.sha256(content).hexdigest()[:16]

    def touch(self) -> None:
        """Update access metadata."""
        self.last_accessed = time.time()
        self.access_count += 1

    def is_stale(self, max_age_seconds: float = 3600) -> bool:
        """Check if page needs refresh."""
        return (time.time() - self.last_accessed) > max_age_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_type": self.page_type.value,
            "content_hash": self.content_hash,
            "storage_tier": self.storage_tier.value,
            "size_bytes": self.size_bytes,
            "version": self.version,
        }


@dataclass
class TokenPage(ContextPage):
    """Raw token sequences with position metadata."""
    tokens: list[int] = field(default_factory=list)
    model_id: str = ""
    token_count: int = 0
    position_start: int = 0

    def __post_init__(self):
        self.page_type = PageType.TOKEN
        self.token_count = len(self.tokens)


@dataclass
class SemanticPage(ContextPage):
    """High-level semantic representation."""
    embedding: list[float] | None = None
    text_summary: str = ""
    entities: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def __post_init__(self):
        self.page_type = PageType.SEMANTIC


@dataclass
class RetrievalPage(ContextPage):
    """Search/retrieval results."""
    query: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""  # backend name
    total_hits: int = 0

    def __post_init__(self):
        self.page_type = PageType.RETRIEVAL


@dataclass
class ToolResultPage(ContextPage):
    """Tool execution output."""
    tool_name: str = ""
    input_params: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    exit_code: int = 0
    duration_ms: float = 0.0
    effect_receipt: str | None = None  # Proof of external effect

    def __post_init__(self):
        self.page_type = PageType.TOOL_RESULT


@dataclass
class ArtifactPage(ContextPage):
    """Generated artifact (code, document, image)."""
    artifact_type: str = ""  # code, document, image, audio
    content: bytes = b""
    mime_type: str = "application/octet-stream"
    source_task_id: str | None = None
    verified: bool = False

    def __post_init__(self):
        self.page_type = PageType.ARTIFACT
        if not self.content_hash and self.content:
            self.content_hash = self.compute_hash(self.content)
        self.size_bytes = len(self.content)


@dataclass
class SummaryPage(ContextPage):
    """Compressed/abstracted context."""
    summary_text: str = ""
    original_page_ids: list[str] = field(default_factory=list)
    compression_ratio: float = 1.0
    method: str = ""  # extractive, abstractive, hierarchical

    def __post_init__(self):
        self.page_type = PageType.SUMMARY


@dataclass
class EvidencePage(ContextPage):
    """Proof-carrying execution evidence."""
    action_hash: str = ""
    approval_id: str | None = None
    effector_id: str | None = None
    receipt: str | None = None
    proof_data: dict[str, Any] = field(default_factory=dict)
    verified: bool = False

    def __post_init__(self):
        self.page_type = PageType.EVIDENCE


@dataclass
class KVPage(ContextPage):
    """Key-value state storage."""
    data: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self):
        self.page_type = PageType.KV

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.version += 1


@dataclass
class CheckpointPage(ContextPage):
    """Process state snapshot."""
    process_id: str = ""
    process_state: str = ""  # serialized state
    program_counter: int = 0
    capability_set: list[str] = field(default_factory=list)
    budget_remaining: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.page_type = PageType.CHECKPOINT


# Page type registry for deserialization
PAGE_TYPE_MAP: dict[PageType, type[ContextPage]] = {
    PageType.TOKEN: TokenPage,
    PageType.SEMANTIC: SemanticPage,
    PageType.RETRIEVAL: RetrievalPage,
    PageType.TOOL_RESULT: ToolResultPage,
    PageType.ARTIFACT: ArtifactPage,
    PageType.SUMMARY: SummaryPage,
    PageType.EVIDENCE: EvidencePage,
    PageType.KV: KVPage,
    PageType.CHECKPOINT: CheckpointPage,
}

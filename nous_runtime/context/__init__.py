# -*- coding: utf-8 -*-
"""Context Runtime — AI Runtime Context Layer.

Context is a Read Model. It does NOT own data. Sources of truth are:
  Memory, Project, Agent, Decision, Device.

Context reads from those sources, builds ContextSnapshot instances,
and provides explainable, auditable context for AI operations.

The Context VM and page types expose the shared context-address-space contract
to the Python distribution without becoming an independent state authority.
"""

# Context VM exports
from nous_runtime.context.page_types import (
    PAGE_TYPE_MAP,
    ArtifactPage,
    CheckpointPage,
    ContextPage,
    EvidencePage,
    KVPage,
    PageType,
    RetrievalPage,
    SemanticPage,
    StorageTier,
    SummaryPage,
    TokenPage,
    ToolResultPage,
)
from nous_runtime.context.pager import (
    ContextPager,
    FaultResolution,
    PageFaultResult,
    PagerStats,
)
from nous_runtime.context.vm import (
    ContextAddressSpace,
    ContextVMManager,
)

from nous_runtime.context.exceptions import (
    ContextBuildError,
    ContextError,
    ContextPermissionError,
    ContextProviderError,
    ContextResolutionError,
    ContextRestoreError,
    ContextStoreError,
    ContextValidationError,
)
from nous_runtime.context.models import (
    ContextItem,
    ContextSnapshot,
)
from nous_runtime.context.schema import (
    CONTEXT_SCHEMA_VERSION,
    ContextSource,
    SnapshotStatus,
)
from nous_runtime.context.store import ContextStore
from nous_runtime.context.types import (
    BuildRequest,
    ContextExplanation,
    ContextScore,
    ProviderHealth,
    RankedContext,
    RestoreResult,
    SnapshotMetadata,
)


# Lazy-friendly deferred imports for heavier modules
def __getattr__(name: str):
    _deferred = {
        "ContextBuilder": "nous_runtime.context.builder",
        "build_context": "nous_runtime.context.builder",
        "ContextResolver": "nous_runtime.context.resolver",
        "resolve_context": "nous_runtime.context.resolver",
        "create_snapshot": "nous_runtime.context.snapshot",
        "restore_snapshot": "nous_runtime.context.snapshot",
        "list_snapshots": "nous_runtime.context.snapshot",
        "latest_snapshot_id": "nous_runtime.context.snapshot",
        "ContextCompressor": "nous_runtime.context.compression",
        "CompressionTier": "nous_runtime.context.compression",
        "CompressedItem": "nous_runtime.context.compression",
        "compress_context": "nous_runtime.context.compression",
        "ContextRanker": "nous_runtime.context.ranking",
        "rank_context": "nous_runtime.context.ranking",
        "RankingResult": "nous_runtime.context.ranking",
        "ContextExplainer": "nous_runtime.context.explain",
        "explain_snapshot": "nous_runtime.context.explain",
        "explain_resolution": "nous_runtime.context.explain",
        "SnapshotExplanation": "nous_runtime.context.explain",
        "ContextGuard": "nous_runtime.context.security",
        "ContextAccessRequest": "nous_runtime.context.security",
        "ContextAccessDecision": "nous_runtime.context.security",
        "authorize_context_access": "nous_runtime.context.security",
        "ExecutionContextBuilder": "nous_runtime.context.execution",
        "build_execution_context": "nous_runtime.context.execution",
    }
    if name in _deferred:
        import importlib

        mod = importlib.import_module(_deferred[name])
        return getattr(mod, name)
    raise AttributeError(f"module 'nous_runtime.context' has no attribute {name!r}")


__all__ = [
    "PAGE_TYPE_MAP",
    "ArtifactPage",
    "CheckpointPage",
    "ContextAddressSpace",
    "ContextPage",
    "ContextPager",
    "ContextVMManager",
    "EvidencePage",
    "FaultResolution",
    "KVPage",
    "PageFaultResult",
    "PageType",
    "PagerStats",
    "RetrievalPage",
    "SemanticPage",
    "StorageTier",
    "SummaryPage",
    "TokenPage",
    "ToolResultPage",
    # Models
    "ContextSnapshot",
    "ContextItem",
    # Schema
    "CONTEXT_SCHEMA_VERSION",
    "ContextSource",
    "SnapshotStatus",
    # Store
    "ContextStore",
    # Types
    "BuildRequest",
    "ContextExplanation",
    "ContextScore",
    "ProviderHealth",
    "RankedContext",
    "RestoreResult",
    "SnapshotMetadata",
    # Builder
    "ContextBuilder",
    "build_context",
    # Resolver
    "ContextResolver",
    "resolve_context",
    # Snapshot
    "create_snapshot",
    "restore_snapshot",
    "list_snapshots",
    "latest_snapshot_id",
    # Compression
    "ContextCompressor",
    "CompressionTier",
    "CompressedItem",
    "compress_context",
    # Ranking
    "ContextRanker",
    "rank_context",
    "RankingResult",
    # Explanation
    "ContextExplainer",
    "explain_snapshot",
    "explain_resolution",
    "SnapshotExplanation",
    # Security
    "ContextGuard",
    "ContextAccessRequest",
    "ContextAccessDecision",
    "authorize_context_access",
    "ExecutionContextBuilder",
    "build_execution_context",
    # Exceptions
    "ContextError",
    "ContextBuildError",
    "ContextPermissionError",
    "ContextProviderError",
    "ContextResolutionError",
    "ContextRestoreError",
    "ContextStoreError",
    "ContextValidationError",
]

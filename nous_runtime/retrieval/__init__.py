"""Retrieval Fabric public API."""

from nous_runtime.retrieval.backends.local import LocalRetrievalBackend
from nous_runtime.retrieval.backends.persistent_local import PersistentLocalRetrievalBackend
from nous_runtime.retrieval.embeddings import (
    EmbeddingModelManifest,
    EmbeddingRegistry,
    HashEmbeddingProvider,
    embedding_registry,
)
from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.indexing import (
    IndexBuildOptions,
    IndexBuildResult,
    IndexGeneration,
    IndexGenerationState,
    LogicalIndexSpec,
    RetrievalIndexVerification,
)
from nous_runtime.retrieval.manager import RetrievalIndexManager
from nous_runtime.retrieval.models import (
    AccessScope,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalRecord,
    RetrievalResult,
    RetrievalScope,
)
from nous_runtime.retrieval.protocol import (
    BackendHealth,
    BackendSearchRequest,
    BackendSearchResult,
    BackendWriteResult,
    IndexSpec,
    IndexVerification,
    RetrievalBackend,
    RetrievalBackendManifest,
)
from nous_runtime.retrieval.registry import RetrievalBackendRegistry, registry
from nous_runtime.retrieval.store import JsonlIndexGenerationStore

if "local" not in registry.list():
    registry.register(LocalRetrievalBackend())

__all__ = [
    "AccessScope",
    "BackendHealth",
    "BackendSearchRequest",
    "BackendSearchResult",
    "BackendWriteResult",
    "EmbeddingModelManifest",
    "EmbeddingRegistry",
    "HashEmbeddingProvider",
    "IndexBuildOptions",
    "IndexBuildResult",
    "IndexGeneration",
    "IndexGenerationState",
    "IndexSpec",
    "IndexVerification",
    "LocalRetrievalBackend",
    "PersistentLocalRetrievalBackend",
    "LogicalIndexSpec",
    "RetrievalBackend",
    "RetrievalBackendManifest",
    "RetrievalBackendRegistry",
    "RetrievalFilters",
    "RetrievalGateway",
    "RetrievalIndexManager",
    "RetrievalIndexVerification",
    "RetrievalQuery",
    "RetrievalRecord",
    "RetrievalResult",
    "RetrievalScope",
    "JsonlIndexGenerationStore",
    "embedding_registry",
    "registry",
]

"""Embedding registry and model manifests."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Protocol

from nous_runtime.retrieval.errors import RetrievalBackendError


@dataclass(frozen=True)
class EmbeddingModelManifest:
    model_id: str
    provider_id: str
    dimension: int
    vector_fields: tuple[str, ...] = ("content",)
    distance_metric: str = "cosine"
    normalize: bool = True
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["vector_fields"] = list(self.vector_fields)
        return data


class EmbeddingProvider(Protocol):
    def manifest(self) -> EmbeddingModelManifest:
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    def __init__(self, model_id: str = "hash-embedding-v1", dimension: int = 32):
        self._manifest = EmbeddingModelManifest(
            model_id=model_id,
            provider_id="local.hash",
            dimension=dimension,
            metadata={"deterministic": True, "production": False},
        )

    def manifest(self) -> EmbeddingModelManifest:
        return self._manifest

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_vector(text, self._manifest.dimension) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)


class FastEmbedEmbeddingProvider:
    def __init__(
        self,
        model_id: str,
        *,
        dimension: int,
        batch_size: int = 32,
        device: str = "cpu",
        revision: str = "",
    ):
        self.model_id = model_id
        self.batch_size = batch_size
        self.device = device
        self._model = None
        self._manifest = EmbeddingModelManifest(
            model_id=model_id,
            provider_id="fastembed",
            dimension=dimension,
            metadata={
                "optional_dependency": "fastembed",
                "device": device,
                "revision": revision,
                "lazy_load": True,
            },
        )

    def manifest(self) -> EmbeddingModelManifest:
        return self._manifest

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        vectors = model.embed(texts, batch_size=self.batch_size)
        return [list(vector) for vector in vectors]

    def available(self) -> bool:
        try:
            self._load_model()
        except Exception:
            return False
        return True

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding
        except Exception as exc:
            raise RetrievalBackendError("fastembed is not installed") from exc
        self._model = TextEmbedding(model_name=self.model_id)
        return self._model


@dataclass
class EmbeddingRegistry:
    _providers: dict[str, EmbeddingProvider] = field(default_factory=dict)

    def register(self, provider: EmbeddingProvider) -> None:
        self._providers[provider.manifest().model_id] = provider

    def resolve(self, model_id: str) -> EmbeddingProvider:
        if model_id not in self._providers:
            raise KeyError(f"embedding model not registered: {model_id}")
        return self._providers[model_id]

    def list(self) -> list[EmbeddingModelManifest]:
        return [self._providers[key].manifest() for key in sorted(self._providers)]


def _hash_vector(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for idx in range(dimension):
        byte = digest[idx % len(digest)]
        values.append((byte / 127.5) - 1.0)
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values] if norm else values


embedding_registry = EmbeddingRegistry()
embedding_registry.register(HashEmbeddingProvider())

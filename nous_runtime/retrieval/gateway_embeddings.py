"""Embedding Provider backed by the unified ModelGateway facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nous_runtime.model_runtime.facade import (
    GatewayExecutionContext,
    GatewayOperation,
    GatewayRequest,
    ModelGatewayFacade,
)
from nous_runtime.model_runtime.models import ModelModality, ModelRole
from nous_runtime.retrieval.embeddings import EmbeddingModelManifest
from nous_runtime.retrieval.errors import RetrievalBackendError


class GatewayEmbeddingProvider:
    """Keep retrieval independent from provider SDK response formats."""

    def __init__(
        self,
        facade: ModelGatewayFacade,
        *,
        model_id: str,
        dimension: int,
        preferred_models: tuple[str, ...] = (),
    ) -> None:
        if dimension < 1:
            raise RetrievalBackendError(
                "embedding dimension must be positive"
            )
        self.facade = facade
        self.preferred_models = tuple(preferred_models)
        self._manifest = EmbeddingModelManifest(
            model_id=model_id,
            provider_id="model_gateway",
            dimension=dimension,
            metadata={"gateway_managed": True},
        )

    def manifest(self) -> EmbeddingModelManifest:
        return self._manifest

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.facade.invoke_sync(
            GatewayRequest(
                operation=GatewayOperation.EMBEDDING,
                execution=GatewayExecutionContext(
                    task_id="retrieval-embedding"
                ),
                input=list(texts),
                required_capabilities=frozenset({"embedding"}),
                required_modalities=frozenset(
                    {ModelModality.EMBEDDING}
                ),
                role=ModelRole.EMBEDDING,
                preferred_models=self.preferred_models,
                metadata={"batch_size": len(texts)},
            )
        )
        vectors = _extract_vectors(response.content)
        if len(vectors) != len(texts):
            raise RetrievalBackendError(
                "gateway embedding result count does not match input"
            )
        for vector in vectors:
            if len(vector) != self._manifest.dimension:
                raise RetrievalBackendError(
                    "gateway embedding dimension mismatch"
                )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)


def _extract_vectors(value: Any) -> list[list[float]]:
    raw = value
    if isinstance(raw, Mapping):
        raw = raw.get("embeddings", raw.get("data", raw.get("vectors")))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise RetrievalBackendError(
            "gateway embedding response is not a vector sequence"
        )
    vectors = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("embedding", item.get("vector"))
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)):
            raise RetrievalBackendError(
                "gateway embedding item is not a vector"
            )
        vectors.append([float(component) for component in item])
    return vectors


__all__ = ["GatewayEmbeddingProvider"]

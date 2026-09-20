"""Dense, sparse, and hybrid retrieval orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import RetrievalQuery, RetrievalResult
from nous_runtime.retrieval.ranking import fuse_results


@dataclass
class HybridRetrievalEngine:
    gateway: RetrievalGateway
    lexical_backend: str = "local"
    dense_backend: str | None = None
    lexical_weight: float = 0.65
    dense_weight: float = 0.35

    def search(self, query: RetrievalQuery) -> list[RetrievalResult]:
        lexical = self.gateway.search(query, backend_name=self.lexical_backend)
        dense = self.gateway.search(query, backend_name=self.dense_backend) if self.dense_backend else []
        return fuse_results(
            {"lexical": lexical, "dense": dense},
            {"lexical": self.lexical_weight, "dense": self.dense_weight},
            limit=query.limit,
        )

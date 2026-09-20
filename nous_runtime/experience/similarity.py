# -*- coding: utf-8 -*-
"""Experience Similarity — finds similar past experiences for a given task."""

from __future__ import annotations

import logging

from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.store import ExperienceStore

_log = logging.getLogger("nous.experience.similarity")


class SimilarityEngine:
    """Finds experiences similar to a given query or task.

    Uses keyword overlap (Jaccard) on task_summary and action fields.
    """

    def __init__(self, store: ExperienceStore | None = None):
        self._store = store or ExperienceStore()

    def find_similar(
        self,
        query: str,
        task_type: str = "",
        limit: int = 20,
        min_score: float = 0.1,
    ) -> list[tuple[ExperienceRecord, float]]:
        """Find experiences similar to a query string.

        Returns list of (record, similarity_score) sorted by score descending.
        """
        candidates = self._store.list(task_type=task_type, limit=200) if task_type else self._store.list(limit=200)
        if not candidates and query:
            candidates = self._store.search(query, limit=100)

        scored: list[tuple[ExperienceRecord, float]] = []
        query_tokens = set(query.lower().split()) if query else set()

        for exp in candidates:
            score = self._similarity(query_tokens, exp)
            if score >= min_score:
                scored.append((exp, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _similarity(self, query_tokens: set[str], exp: ExperienceRecord) -> float:
        """Compute Jaccard similarity between query and experience."""
        if not query_tokens:
            return 0.3  # Default relevance

        exp_text = f"{exp.task_summary} {exp.action} {exp.failure_reason} {' '.join(exp.lessons)}"
        exp_tokens = set(exp_text.lower().split())

        if not exp_tokens:
            return 0.0

        intersection = query_tokens & exp_tokens
        union = query_tokens | exp_tokens
        jaccard = len(intersection) / max(len(union), 1)

        # Boost for trusted experiences
        boost = 0.1 if exp.status == "trusted" else 0.0
        # Boost for successful experiences
        if exp.success:
            boost += 0.05

        return min(1.0, jaccard + boost)

    def find_similar_tasks(self, task_summary: str, limit: int = 20) -> list[tuple[ExperienceRecord, float]]:
        """Find experiences from similar tasks."""
        return self.find_similar(query=task_summary, limit=limit, min_score=0.15)

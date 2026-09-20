# -*- coding: utf-8 -*-
"""Context Ranking — fast multi-dimensional ranking of context items.

Performance target: 10 000 items in < 500 ms.

Dimensions (sorted by priority):
  relevance  — how well the item matches the intent
  freshness  — how recently the item was created
  confidence — how confident we are in the item's accuracy
  importance — how important the item is intrinsically
  relation   — how well it connects to other selected items
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from nous_runtime.context.models import ContextItem
from nous_runtime.context.types import ContextScore, RankedContext

_log = logging.getLogger("nous.context.ranking")



# Ranked result


@dataclass
class RankingResult:
    """Result of a ranking operation."""
    ranked: list[RankedContext] = field(default_factory=list)
    total_items: int = 0
    duration_ms: int = 0
    threshold: float = 0.0



# Ranker


class ContextRanker:
    """Sorts context items by a weighted multi-dimensional score.

    Usage::

        ranker = ContextRanker()
        result = ranker.rank(items, intent="continue project X")
        top = result.ranked[:10]
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
    ):
        self._weights = weights or {
            "relevance": 0.35,
            "freshness": 0.25,
            "confidence": 0.20,
            "importance": 0.20,
        }



    def rank(
        self,
        items: list[ContextItem],
        intent: str = "",
        *,
        limit: int = 100,
        threshold: float = 0.0,
    ) -> RankingResult:
        """Rank items by composite score.

        Args:
            items: Context items to rank.
            intent: User intent for relevance scoring.
            limit: Maximum items to return.
            threshold: Minimum composite score to include.

        Returns:
            RankingResult with sorted items and metadata.
        """
        t0 = time.perf_counter()
        n = len(items)

        if not items:
            return RankingResult(
                ranked=[],
                total_items=0,
                duration_ms=int((time.perf_counter() - t0) * 1000),
                threshold=threshold,
            )

        # Score all items
        scored: list[tuple[float, int, RankedContext]] = []
        for idx, item in enumerate(items):
            score = self._score(item, intent)
            if score.composite < threshold:
                continue
            ranked = RankedContext(
                item_id=item.item_id,
                source_type=item.source_type,
                content_summary=item.content[:120],
                score=score,
                rank=0,
                selected=True,
                selection_reason=score.explanation,
            )
            scored.append((score.composite, idx, ranked))

        # Sort: composite DESC, then original index ASC (stable tie-break)
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Assign ranks
        ranked: list[RankedContext] = []
        for i, (_, _, r) in enumerate(scored[:limit]):
            object.__setattr__(r, "rank", i + 1)
            ranked.append(r)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if elapsed_ms > 400:
            _log.warning("Ranking %d items took %d ms (target <500 ms)", n, elapsed_ms)

        return RankingResult(
            ranked=ranked,
            total_items=n,
            duration_ms=elapsed_ms,
            threshold=threshold,
        )



    def _score(self, item: ContextItem, intent: str) -> ContextScore:
        """Compute decomposed score."""
        relevance = self._relevance(item, intent)
        freshness = self._freshness(item)
        confidence = item.confidence
        importance = item.importance

        composite = (
            self._weights["relevance"] * relevance
            + self._weights["freshness"] * freshness
            + self._weights["confidence"] * confidence
            + self._weights["importance"] * importance
        )
        composite = max(0.0, min(1.0, composite))

        parts: list[str] = []
        if relevance > 0.4:
            parts.append(f"relevant({relevance:.2f})")
        if freshness > 0.4:
            parts.append(f"fresh({freshness:.2f})")
        if confidence > 0.5:
            parts.append(f"confident({confidence:.2f})")
        if importance > 0.5:
            parts.append(f"important({importance:.2f})")
        if not parts:
            parts.append("low")

        return ContextScore(
            item_id=item.item_id,
            relevance=relevance,
            freshness=freshness,
            confidence=confidence,
            importance=importance,
            composite=composite,
            explanation=", ".join(parts),
        )



    @staticmethod
    def _relevance(item: ContextItem, intent: str) -> float:
        """Compute relevance via token overlap."""
        if not intent:
            return 0.5
        intent_tokens = set(intent.lower().split())
        content_tokens = set(item.content.lower().split())
        if not intent_tokens:
            return 0.5
        overlap = intent_tokens & content_tokens
        jaccard = len(overlap) / max(len(intent_tokens | content_tokens), 1)

        # Substring boost
        boost = 0.0
        for token in intent_tokens:
            if len(token) >= 3 and token in item.content.lower():
                boost = max(boost, 0.3)

        # Tag boost
        for tag in item.tags:
            if tag in intent.lower():
                boost = max(boost, 0.4)

        return max(0.0, min(1.0, jaccard + boost))

    @staticmethod
    def _freshness(item: ContextItem) -> float:
        """Compute freshness via exponential decay (3-day half-life)."""
        if not item.created_at:
            return 0.5
        try:
            from datetime import datetime, timezone
            created = datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = (now - created).total_seconds()
            if delta < 0:
                return 1.0
            half_life = 3 * 24 * 3600  # 3 days
            score = 2.0 ** (-delta / half_life)
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.5



# Convenience


def rank_context(
    items: list[ContextItem],
    intent: str = "",
    *,
    limit: int = 100,
    threshold: float = 0.0,
) -> RankingResult:
    """One-shot context ranking."""
    return ContextRanker().rank(items, intent=intent, limit=limit, threshold=threshold)

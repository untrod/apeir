# -*- coding: utf-8 -*-
"""Context Resolver — scores, selects, and explains context items.

Algorithm:
  composite = 0.35 * relevance + 0.25 * freshness + 0.20 * confidence + 0.20 * importance

Every decision is explainable: why selected, why discarded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from nous_runtime.context.models import ContextItem
from nous_runtime.context.types import ContextExplanation, ContextScore, RankedContext

_log = logging.getLogger("nous.context.resolver")



# Scoring weights (tuneable, but stable defaults)


DEFAULT_WEIGHTS = {
    "relevance": 0.35,
    "freshness": 0.25,
    "confidence": 0.20,
    "importance": 0.20,
}

SELECTION_THRESHOLD = 0.40  # Items scoring below this are discarded by default



# Resolver


class ContextResolver:
    """Resolve which context items are relevant for a given intent.

    Usage::

        resolver = ContextResolver()
        explanation = resolver.resolve(items, intent="continue project X")
        for item in explanation.selected_items:
            print(item.content_summary, item.score.composite)
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        threshold: float = SELECTION_THRESHOLD,
    ):
        self._weights = weights or dict(DEFAULT_WEIGHTS)
        self._threshold = threshold
        self._now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


    # Public API


    def resolve(
        self,
        items: list[ContextItem],
        intent: str = "",
        *,
        max_items: int = 50,
        threshold: float | None = None,
    ) -> ContextExplanation:
        """Score and select context items.

        Args:
            items: Context items to evaluate.
            intent: What the caller is trying to do (used for relevance scoring).
            max_items: Maximum items to select.
            threshold: Override the default selection threshold.

        Returns:
            ContextExplanation with selected/discarded items and reasoning.
        """
        threshold = threshold if threshold is not None else self._threshold

        if not items:
            return ContextExplanation(
                selection_summary="No context items to resolve.",
                confidence=1.0,
                reasoning=["Input item list was empty."],
            )

        # Phase 1 — Score every item
        ranked: list[RankedContext] = []
        for item in items:
            score = self._score_item(item, intent)
            selected = score.composite >= threshold
            ranked.append(RankedContext(
                item_id=item.item_id,
                source_type=item.source_type,
                content_summary=item.content[:120],
                score=score,
                rank=0,  # Filled after sorting
                selected=selected,
                selection_reason=score.explanation if selected else f"Composite {score.composite:.3f} below threshold {threshold:.3f}",
            ))

        # Phase 2 — Sort by composite score descending
        ranked.sort(key=lambda r: r.score.composite, reverse=True)

        # Phase 3 — Assign ranks
        for i, r in enumerate(ranked):
            object.__setattr__(r, "rank", i + 1)

        # Phase 4 — Partition
        selected = [r for r in ranked if r.selected][:max_items]
        discarded = [r for r in ranked if not r.selected]

        # Phase 5 — Build explanation
        reasoning = self._build_reasoning(selected, discarded, intent, len(items))

        if selected:
            avg = sum(r.score.composite for r in selected) / len(selected)
        else:
            avg = 0.0

        return ContextExplanation(
            selected_items=selected,
            discarded_items=discarded,
            selection_summary=(
                f"Selected {len(selected)} of {len(items)} items "
                f"for intent '{intent or '(none)'}' "
                f"(threshold={threshold:.2f}, avg score={avg:.3f})"
            ),
            confidence=round(avg, 3),
            reasoning=reasoning,
        )


    # Scoring


    def _score_item(self, item: ContextItem, intent: str) -> ContextScore:
        """Compute a decomposed score for a single item."""
        relevance = self._compute_relevance(item, intent)
        freshness = self._compute_freshness(item)
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
        if relevance > 0.5:
            parts.append(f"relevant to intent (r={relevance:.2f})")
        if freshness > 0.5:
            parts.append(f"fresh (f={freshness:.2f})")
        if confidence > 0.5:
            parts.append(f"high confidence (c={confidence:.2f})")
        if importance > 0.5:
            parts.append(f"important (i={importance:.2f})")
        if not parts:
            parts.append("default")

        return ContextScore(
            item_id=item.item_id,
            relevance=relevance,
            freshness=freshness,
            confidence=confidence,
            importance=importance,
            composite=composite,
            explanation="; ".join(parts),
        )


    # Sub-scores


    def _compute_relevance(self, item: ContextItem, intent: str) -> float:
        """Compute relevance of an item to the given intent.

        Uses simple keyword overlap. Can be extended with embeddings.
        """
        if not intent:
            return 0.5  # Neutral when no intent specified

        intent_lower = intent.lower()
        content_lower = item.content.lower()

        # Tokenize
        intent_tokens = set(intent_lower.split())
        content_tokens = set(content_lower.split())

        # Jaccard-like overlap
        if not intent_tokens:
            return 0.5
        overlap = intent_tokens & content_tokens
        jaccard = len(overlap) / max(len(intent_tokens | content_tokens), 1)

        # Boost for exact substring match
        substring_boost = 0.0
        for token in intent_tokens:
            if len(token) >= 3 and token in content_lower:
                substring_boost = max(substring_boost, 0.3)

        # Tag-based boost
        tag_boost = 0.0
        for tag in item.tags:
            if tag in intent_lower:
                tag_boost = max(tag_boost, 0.4)

        return max(0.0, min(1.0, jaccard + substring_boost + tag_boost))

    def _compute_freshness(self, item: ContextItem) -> float:
        """Compute freshness: recent items score higher."""
        if not item.created_at:
            return 0.5
        try:
            created = datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
            now = datetime.fromisoformat(self._now.replace("Z", "+00:00"))
            delta_seconds = (now - created).total_seconds()
            if delta_seconds < 0:
                return 1.0
            # Half-life of 3 days
            half_life = 3 * 24 * 3600
            score = 2.0 ** (-delta_seconds / half_life)
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.5


    # Explanation


    def _build_reasoning(
        self,
        selected: list[RankedContext],
        discarded: list[RankedContext],
        intent: str,
        total: int,
    ) -> list[str]:
        """Build human-readable reasoning for the selection."""
        reasons: list[str] = []

        reasons.append(f"Evaluated {total} context items against intent '{intent or '(none)'}'.")

        # Why selected
        if selected:
            sources = {s.source_type for s in selected}
            reasons.append(f"Selected {len(selected)} items from sources: {', '.join(sorted(sources))}.")
            top = selected[0]
            reasons.append(
                f"Top item: [{top.source_type}] {top.content_summary[:100]} "
                f"(score={top.score.composite:.3f})"
            )
            if len(selected) > 1:
                bottom = selected[-1]
                reasons.append(
                    f"Lowest selected: [{bottom.source_type}] score={bottom.score.composite:.3f}"
                )
        else:
            reasons.append("No items met the selection threshold.")

        # Why discarded
        if discarded:
            reasons.append(f"Discarded {len(discarded)} items (below threshold {self._threshold:.2f}).")
            # Show top 3 discarded
            for d in discarded[:3]:
                reasons.append(
                    f"  - [{d.source_type}] {d.content_summary[:80]} → "
                    f"score={d.score.composite:.3f} (r={d.score.relevance:.2f} "
                    f"f={d.score.freshness:.2f} c={d.score.confidence:.2f} "
                    f"i={d.score.importance:.2f})"
                )

        # Weights used
        reasons.append(
            f"Weights: relevance={self._weights['relevance']:.2f} "
            f"freshness={self._weights['freshness']:.2f} "
            f"confidence={self._weights['confidence']:.2f} "
            f"importance={self._weights['importance']:.2f}"
        )

        return reasons



# Convenience


def resolve_context(
    items: list[ContextItem],
    intent: str = "",
    *,
    max_items: int = 50,
    threshold: float = SELECTION_THRESHOLD,
) -> ContextExplanation:
    """One-shot context resolution."""
    return ContextResolver(threshold=threshold).resolve(
        items, intent=intent, max_items=max_items,
    )

# -*- coding: utf-8 -*-
"""Context Explanation — human-readable reasoning for context decisions.

Answers:
  - Why was this project restored?
  - Why was this context selected?
  - Why was other information ignored?
  - What is the confidence in this selection?
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.types import ContextExplanation
from nous_runtime.context.token_estimator import estimate_tokens

_log = logging.getLogger("nous.context.explain")


def explain_model_input(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    provenance: Mapping[int, dict[str, Any]],
) -> dict[str, Any]:
    """Describe the admitted Gateway input without copying prompt/tool contents.

    Positional provenance describes the final input after inserted prompts
    and subsequent tool turns. This is an input manifest, not permission, proof
    of provider receipt, or an explanation of a newly built ContextSnapshot.
    """

    def encoded(value: Any) -> str:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def digest(value: Any) -> str:
        return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()

    records = []
    estimated_tokens = 3
    for index, message in enumerate(messages):
        content = message.get("content") or ""
        text = content if isinstance(content, str) else encoded(content)
        # Structured tool calls are part of the input even when content is empty.
        structured = {k: v for k, v in message.items() if k not in {"role", "content"}}
        tokens = (
            estimate_tokens(text)
            + (estimate_tokens(encoded(structured)) if structured else 0)
            + 4
        )
        estimated_tokens += tokens
        if index < 256:
            role = str(message.get("role") or "unknown")
            records.append(
                {
                    "index": index,
                    "role": role
                    if role in {"system", "user", "assistant", "tool"}
                    else "unknown",
                    "content_characters": len(text),
                    "estimated_tokens": tokens,
                    "sha256": digest(message),
                    "source": provenance.get(
                        index,
                        {"kind": "instruction" if role == "system" else "conversation"},
                    ),
                }
            )
    tool_tokens = estimate_tokens(encoded(tools)) if tools else 0
    return {
        "schema_version": 1,
        "scope": "admitted-gateway-input",
        "input_sha256": digest({"messages": messages, "tools": tools}),
        "message_count": len(messages),
        "messages": records,
        "messages_truncated": len(messages) > len(records),
        "tool_count": len(tools),
        "tools": [
            {
                "name": str((tool.get("function") or {}).get("name") or "unknown"),
                "sha256": digest(tool),
            }
            for tool in tools[:64]
        ],
        "tools_truncated": len(tools) > 64,
        "estimated_input_tokens": estimated_tokens + tool_tokens,
        "input_measurement": "estimate",
        "raw_content_recorded": False,
        "execution_authority": False,
    }


# Explanation result


@dataclass
class SnapshotExplanation:
    """Full explanation of a snapshot — what, why, confidence."""

    snapshot_id: str = ""
    timestamp: str = ""

    # Why this snapshot exists
    build_intent: str = ""
    build_summary: str = ""

    # What was selected
    selected_summary: str = ""
    selected_items: list[dict[str, Any]] = field(default_factory=list)

    # What was ignored
    discarded_summary: str = ""
    discarded_items: list[dict[str, Any]] = field(default_factory=list)

    # Sources
    sources_used: list[str] = field(default_factory=list)
    sources_missing: list[str] = field(default_factory=list)

    # Confidence
    confidence: float = 0.0
    confidence_explanation: str = ""

    # Full reasoning chain
    reasoning: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "build_intent": self.build_intent,
            "build_summary": self.build_summary,
            "selected_summary": self.selected_summary,
            "selected_items": self.selected_items,
            "discarded_summary": self.discarded_summary,
            "discarded_items": self.discarded_items,
            "sources_used": self.sources_used,
            "sources_missing": self.sources_missing,
            "confidence": self.confidence,
            "confidence_explanation": self.confidence_explanation,
            "reasoning": self.reasoning,
        }


# Explainer


class ContextExplainer:
    """Generates human-readable explanations for context decisions.

    Usage::

        explainer = ContextExplainer()
        exp = explainer.explain_snapshot(snapshot)
        print(exp.build_summary)
    """

    # Snapshot-level explanation

    def explain_snapshot(self, snapshot: ContextSnapshot) -> SnapshotExplanation:
        """Explain a complete snapshot — why it exists and what it contains."""
        items = list(snapshot.items)

        # Why this snapshot?
        intent = snapshot.metadata.get("intent", snapshot.runtime.get("intent", ""))
        build_summary = self._describe_snapshot(snapshot, items)

        # Sources
        sources_used = list(snapshot.sources)
        all_sources = {
            "memory",
            "project",
            "agent",
            "device",
            "decision",
            "retrieval",
            "experience",
            "runtime",
        }
        sources_missing = sorted(all_sources - set(sources_used))

        # Selected vs discarded
        selected = items[:20]  # Top 20 by construction order
        discarded: list[
            ContextItem
        ] = []  # Built snapshots don't carry discards directly

        # Confidence
        confidence = snapshot.confidence
        conf_explanation = self._explain_confidence(
            confidence, len(items), len(sources_used)
        )

        # Reasoning chain
        reasoning = self._build_reasoning_chain(
            snapshot, items, sources_used, sources_missing
        )

        return SnapshotExplanation(
            snapshot_id=snapshot.id,
            timestamp=snapshot.timestamp,
            build_intent=intent,
            build_summary=build_summary,
            selected_summary=f"{len(selected)} items from {len(sources_used)} sources",
            selected_items=[
                {
                    "source": i.source_type,
                    "content": i.content[:200],
                    "confidence": i.confidence,
                    "importance": i.importance,
                }
                for i in selected
            ],
            discarded_summary=f"{len(discarded)} items discarded",
            discarded_items=[],
            sources_used=sources_used,
            sources_missing=sources_missing,
            confidence=confidence,
            confidence_explanation=conf_explanation,
            reasoning=reasoning,
        )

    # Resolution-level explanation

    def explain_resolution(self, explanation: ContextExplanation) -> dict[str, Any]:
        """Format a resolution explanation for human consumption."""
        selected = explanation.selected_items
        discarded = explanation.discarded_items

        result: dict[str, Any] = {
            "summary": explanation.selection_summary,
            "confidence": explanation.confidence,
            "reasoning": explanation.reasoning,
        }

        # Selected items detail
        result["selected"] = [
            {
                "rank": r.rank,
                "source": r.source_type,
                "content": r.content_summary,
                "score": {
                    "composite": round(r.score.composite, 3),
                    "relevance": round(r.score.relevance, 3),
                    "freshness": round(r.score.freshness, 3),
                    "confidence": round(r.score.confidence, 3),
                    "importance": round(r.score.importance, 3),
                },
                "reason": r.selection_reason,
            }
            for r in selected
        ]

        # Discarded items detail (top 10)
        result["discarded"] = [
            {
                "source": r.source_type,
                "content": r.content_summary,
                "composite_score": round(r.score.composite, 3),
                "reason": r.selection_reason,
            }
            for r in discarded[:10]
        ]

        # Why selected?
        if selected:
            result["why_selected"] = [
                f"Top source: {selected[0].source_type}",
                f"Average composite score: {sum(r.score.composite for r in selected) / len(selected):.3f}",
                f"Score breakdown: r={sum(r.score.relevance for r in selected) / len(selected):.3f} "
                f"f={sum(r.score.freshness for r in selected) / len(selected):.3f} "
                f"c={sum(r.score.confidence for r in selected) / len(selected):.3f} "
                f"i={sum(r.score.importance for r in selected) / len(selected):.3f}",
            ]

        # Why ignored?
        if discarded:
            result["why_ignored"] = [
                f"All {len(discarded)} discarded items fell below the selection threshold.",
                "Common reasons: low relevance to intent, stale timestamp, or low importance.",
            ]

        return result

    # Item-level explanation

    def explain_item(self, item: ContextItem, intent: str = "") -> dict[str, Any]:
        """Explain why a single context item was included."""
        return {
            "item_id": item.item_id,
            "source": item.source_type,
            "content_preview": item.content[:200],
            "why_included": [
                f"Source type '{item.source_type}' matches context needs.",
                f"Importance={item.importance:.2f}, Confidence={item.confidence:.2f}",
            ],
            "permission": item.permission,
            "tags": list(item.tags),
            "created_at": item.created_at,
        }

    # Helpers

    @staticmethod
    def _describe_snapshot(snapshot: ContextSnapshot, items: list[ContextItem]) -> str:
        """Build a one-paragraph description of what this snapshot captures."""
        n = len(items)
        sources = list(snapshot.sources)
        parts: list[str] = []

        if snapshot.project:
            name = snapshot.project.get(
                "summary", snapshot.project.get("project_id", "")
            )
            if name:
                parts.append(f"Project: {name}")

        phase = snapshot.project.get("phase", "")
        if phase:
            parts.append(f"Phase: {phase}")

        if n > 0:
            parts.append(
                f"{n} context items from {len(sources)} sources ({', '.join(sources[:4])})"
            )

        return " | ".join(parts) if parts else f"Snapshot {snapshot.id} with {n} items."

    @staticmethod
    def _explain_confidence(
        confidence: float, item_count: int, source_count: int
    ) -> str:
        """Explain the confidence score."""
        if confidence >= 0.8:
            base = "High confidence"
        elif confidence >= 0.5:
            base = "Moderate confidence"
        else:
            base = "Low confidence"

        reasons: list[str] = []
        if item_count >= 20:
            reasons.append(f"based on {item_count} items")
        if source_count >= 3:
            reasons.append(f"from {source_count} diverse sources")
        elif source_count < 2:
            reasons.append("due to limited source diversity")

        return f"{base} ({confidence:.2f})" + (
            ": " + ", ".join(reasons) if reasons else ""
        )

    @staticmethod
    def _build_reasoning_chain(
        snapshot: ContextSnapshot,
        items: list[ContextItem],
        sources_used: list[str],
        sources_missing: list[str],
    ) -> list[str]:
        """Build a chain of reasoning for the snapshot."""
        chain: list[str] = []

        # 1. Snapshot origin
        intent = snapshot.metadata.get("intent", "unknown")
        chain.append(f"Snapshot created for intent: '{intent}'.")

        # 2. Sources
        chain.append(
            f"Context collected from {len(sources_used)} sources: {', '.join(sources_used)}."
        )
        if sources_missing:
            chain.append(f"Sources not available: {', '.join(sources_missing)}.")

        # 3. Items
        chain.append(f"Collected {len(items)} context items across all sources.")

        # 4. Top items by source
        source_counts: dict[str, int] = {}
        for item in items:
            source_counts[item.source_type] = source_counts.get(item.source_type, 0) + 1
        for src, count in sorted(source_counts.items()):
            chain.append(f"  - {src}: {count} items")

        # 5. Confidence
        chain.append(f"Aggregate confidence: {snapshot.confidence:.2f}.")

        return chain


# Convenience functions


def explain_snapshot(snapshot: ContextSnapshot) -> SnapshotExplanation:
    """One-shot snapshot explanation."""
    return ContextExplainer().explain_snapshot(snapshot)


def explain_resolution(explanation: ContextExplanation) -> dict[str, Any]:
    """One-shot resolution explanation."""
    return ContextExplainer().explain_resolution(explanation)

# -*- coding: utf-8 -*-
"""Context Builder — orchestrates providers into a ContextSnapshot.

Pipeline:
  Request → Collect (providers) → Normalize → Filter → Rank → Snapshot
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from nous_runtime.context.exceptions import ContextBuildError
from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.providers.agent import AgentProvider
from nous_runtime.context.providers.base import ContextProvider
from nous_runtime.context.providers.decision import DecisionProvider
from nous_runtime.context.providers.device import DeviceProvider
from nous_runtime.context.providers.memory import MemoryProvider
from nous_runtime.context.providers.project import ProjectProvider
from nous_runtime.context.schema import ContextSource, SnapshotStatus
from nous_runtime.context.types import BuildRequest

_log = logging.getLogger("nous.context.builder")
CONTEXT_CLASSES = (
    "governance_system",
    "active_objective",
    "active_plan",
    "recent_messages",
    "workspace_facts",
    "knowledge_retrieval",
    "experience",
    "archived_history",
)
DEFAULT_TOKEN_BUDGETS = {
    "governance_system": 4_096,
    "active_objective": 2_048,
    "active_plan": 4_096,
    "recent_messages": 8_192,
    "workspace_facts": 4_096,
    "knowledge_retrieval": 8_192,
    "experience": 2_048,
    "archived_history": 1_024,
}




# Default provider registry


def _default_providers(workspace: str = "") -> list[ContextProvider]:
    """Return the standard set of context providers."""
    return [
        MemoryProvider(workspace),
        ProjectProvider(workspace),
        AgentProvider(workspace),
        DeviceProvider(workspace),
        DecisionProvider(workspace),
    ]



# Builder


class ContextBuilder:
    """Orchestrates context collection, normalization, filtering, and snapshot creation.

    Usage::

        builder = ContextBuilder(workspace="/path/to/.nous")
        snapshot = builder.build(BuildRequest(intent="continue project X"))
    """

    def __init__(self, workspace: str = "", providers: list[ContextProvider] | None = None):
        self._workspace = workspace
        self._providers = providers if providers is not None else _default_providers(workspace)


    # Public API


    def build_context(self, request: BuildRequest) -> ContextSnapshot:
        """Execute the full context building pipeline.

        Args:
            request: A BuildRequest describing what context is needed.

        Returns:
            A fully built ContextSnapshot.

        Raises:
            ContextBuildError: If the pipeline fails critically.
        """
        t0 = time.perf_counter()

        try:
            # Phase 1 — Collect from all providers
            raw_items = self._collect(request)

            # Phase 2 — Normalize (dedup, fill defaults)
            normalized = self._normalize(raw_items)

            # Phase 3 — Filter (permissions, relevance)
            filtered = self._filter(normalized, request)

            # Phase 4 — Rank (scoring and sorting)
            ranked = self._rank(filtered, request)

            # Phase 5 — Build snapshot
            selected, budget_profile = self._apply_token_budgets(
                ranked, request
            )
            snapshot = self._assemble(selected, request)

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            object.__setattr__(snapshot, "metadata", {
                **snapshot.metadata,
                "build_duration_ms": elapsed_ms,
                "raw_count": len(raw_items),
                "filtered_count": len(filtered),
                "duplicate_suppressed": len(raw_items) - len(normalized),
                "truncation_explanation": budget_profile["truncated"],
                "context_build_profile": {
                    "duration_ms": elapsed_ms,
                    "tokens_by_class": budget_profile["tokens_by_class"],
                    "token_budgets": budget_profile["token_budgets"],
                },
                "citation_coverage": _citation_coverage(selected),
            })

            _log.info(
                "Built snapshot %s: %d raw → %d filtered → %d ranked (%d ms)",
                snapshot.id, len(raw_items), len(filtered), len(ranked), elapsed_ms,
            )
            return snapshot

        except ContextBuildError:
            raise
        except Exception as exc:
            raise ContextBuildError(f"Context build failed: {exc}") from exc


    # Pipeline phases


    def _collect(self, request: BuildRequest) -> list[ContextItem]:
        """Collect items from all (or requested) providers."""
        requested_sources = set(request.sources) if request.sources else set()
        all_items: list[ContextItem] = []

        for provider in self._providers:
            source = getattr(provider, "source_type", "unknown")
            # Skip if request specifies sources and this isn't one of them
            if requested_sources and source not in requested_sources:
                continue
            try:
                items = provider.collect(
                    request_hint=request.intent or request.context_hint,
                    limit=request.max_items,
                )
                all_items.extend(items)
            except Exception as exc:
                _log.warning("Provider %s failed: %s", source, exc)

        return all_items

    def _normalize(self, items: list[ContextItem]) -> list[ContextItem]:
        """Normalize items: deduplicate by content, ensure defaults are set."""
        seen: set[str] = set()
        result: list[ContextItem] = []

        for item in items:
            normalized_content = " ".join(item.content.split()).casefold()
            dedup_key = hashlib.sha256(
                normalized_content.encode("utf-8")
            ).hexdigest()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Validate and skip invalid items
            errors = item.validate()
            if errors:
                _log.debug("Skipping invalid item %s: %s", item.item_id, errors)
                continue

            result.append(item)

        return result

    def _filter(self, items: list[ContextItem], request: BuildRequest) -> list[ContextItem]:
        """Filter items by permissions, source restrictions, and relevance threshold."""
        filtered: list[ContextItem] = []

        for item in items:
            # Private items are excluded from shared context
            if item.permission == "private":
                continue

            # Restricted items only included if explicitly requested
            if item.permission == "restricted" and not request.metadata.get("include_restricted"):
                continue

            # Filter out items below minimum importance
            min_importance = request.metadata.get("min_importance", 0.0)
            if item.importance < min_importance:
                continue

            # Filter out items below minimum confidence
            min_confidence = request.metadata.get("min_confidence", 0.0)
            if item.confidence < min_confidence:
                continue

            filtered.append(item)

        return filtered

    def _rank(self, items: list[ContextItem], request: BuildRequest) -> list[ContextItem]:
        """Rank items by a simple scoring heuristic.

        For full scoring use ContextResolver (Phase 3.5).
        This is a fast default ranking for the builder pipeline.
        """
        # Score = 0.35 * importance + 0.25 * recency + 0.20 * confidence + 0.20 * source_priority
        scored: list[tuple[float, ContextItem]] = []

        source_priority = {
            ContextSource.PROJECT.value: 0.9,
            ContextSource.MEMORY.value: 0.8,
            ContextSource.DECISION.value: 0.7,
            ContextSource.AGENT.value: 0.6,
            ContextSource.DEVICE.value: 0.5,
            ContextSource.RETRIEVAL.value: 0.4,
            ContextSource.EXPERIENCE.value: 0.3,
            ContextSource.RUNTIME.value: 0.2,
        }

        now_str = _now_iso()

        for item in items:
            importance = item.importance
            confidence = item.confidence

            # Freshness: items created recently score higher
            freshness = 0.5
            if item.created_at:
                freshness = _freshness_score(item.created_at, now_str)

            # Source priority
            sp = source_priority.get(item.source_type, 0.5)

            score = 0.35 * importance + 0.25 * freshness + 0.20 * confidence + 0.20 * sp
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[: request.max_items]]

    def _apply_token_budgets(
        self,
        items: list[ContextItem],
        request: BuildRequest,
    ) -> tuple[list[ContextItem], dict[str, Any]]:
        configured = dict(request.metadata.get("token_budgets") or {})
        budgets = {
            name: max(
                0, int(configured.get(name, DEFAULT_TOKEN_BUDGETS[name]))
            )
            for name in CONTEXT_CLASSES
        }
        used = {name: 0 for name in CONTEXT_CLASSES}
        selected: list[ContextItem] = []
        truncated: list[dict[str, Any]] = []
        for item in items:
            context_class = _context_class(item)
            tokens = _estimated_tokens(item.content)
            if used[context_class] + tokens > budgets[context_class]:
                truncated.append(
                    {
                        "item_id": item.item_id,
                        "context_class": context_class,
                        "estimated_tokens": tokens,
                        "reason": "context_class_token_budget",
                    }
                )
                continue
            used[context_class] += tokens
            selected.append(item)
        return selected, {
            "tokens_by_class": used,
            "token_budgets": budgets,
            "truncated": truncated,
        }

    def _assemble(self, items: list[ContextItem], request: BuildRequest) -> ContextSnapshot:
        """Assemble the final ContextSnapshot from ranked items."""
        sources = sorted({item.source_type for item in items})

        # Compute aggregate confidence
        if items:
            agg_confidence = sum(i.confidence for i in items) / len(items)
        else:
            agg_confidence = 0.0

        # Partition items into source-aligned sections
        memory_items = [i.to_dict() for i in items if i.source_type == ContextSource.MEMORY.value]
        decision_items = [i.to_dict() for i in items if i.source_type == ContextSource.DECISION.value]
        retrieval_items = [i.to_dict() for i in items if i.source_type == ContextSource.RETRIEVAL.value]
        experience_items = [i.to_dict() for i in items if i.source_type == ContextSource.EXPERIENCE.value]

        # Extract project/agent/device context as summary dicts
        project_ctx: dict[str, Any] = {"project_id": request.project_id}
        for i in items:
            if i.source_type == ContextSource.PROJECT.value and "project" in i.content.lower():
                project_ctx["summary"] = i.content

        agent_ctx: dict[str, Any] = {"agent_id": request.agent_id}
        for i in items:
            if i.source_type == ContextSource.AGENT.value:
                agent_ctx.setdefault("agents", []).append(i.content)

        device_ctx: dict[str, Any] = {"device_id": request.device_id}
        for i in items:
            if i.source_type == ContextSource.DEVICE.value:
                device_ctx.setdefault("devices", []).append(i.content)

        return ContextSnapshot(
            user={"user_id": request.user_id} if request.user_id else {},
            project=project_ctx,
            task={"task_id": request.task_id} if request.task_id else {},
            agent=agent_ctx,
            device=device_ctx,
            memory=memory_items,
            decision=decision_items,
            retrieval=retrieval_items,
            experience=experience_items,
            runtime={"intent": request.intent, "context_hint": request.context_hint},
            items=tuple(items),
            sources=tuple(sources),
            confidence=agg_confidence,
            status=SnapshotStatus.ACTIVE.value,
        )



# Convenience factory


def build_context(request: BuildRequest, workspace: str = "") -> ContextSnapshot:
    """One-shot context build with default providers.

    Args:
        request: What context to build.
        workspace: Optional workspace path.

    Returns:
        A ContextSnapshot.
    """
    builder = ContextBuilder(workspace=workspace)
    return builder.build_context(request)



# Internal helpers


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _estimated_tokens(content: str) -> int:
    return max(1, (len(content) + 3) // 4)


def _context_class(item: ContextItem) -> str:
    explicit = str(item.metadata.get("context_class") or "")
    if explicit in CONTEXT_CLASSES:
        return explicit
    if "archived" in item.tags:
        return "archived_history"
    return {
        ContextSource.RUNTIME.value: "governance_system",
        ContextSource.AGENT.value: "active_objective",
        ContextSource.DECISION.value: "active_plan",
        ContextSource.MEMORY.value: "recent_messages",
        ContextSource.PROJECT.value: "workspace_facts",
        ContextSource.DEVICE.value: "workspace_facts",
        ContextSource.RETRIEVAL.value: "knowledge_retrieval",
        ContextSource.EXPERIENCE.value: "experience",
    }.get(item.source_type, "workspace_facts")


def _citation_coverage(items: list[ContextItem]) -> float:
    retrieval = [
        item
        for item in items
        if item.source_type == ContextSource.RETRIEVAL.value
    ]
    if not retrieval:
        return 1.0
    cited = sum(
        1
        for item in retrieval
        if item.source_id
        or item.metadata.get("citation")
        or item.metadata.get("citations")
    )
    return round(cited / len(retrieval), 4)



def _freshness_score(item_ts: str, now_ts: str) -> float:
    """Score freshness: 1.0 for now, decaying to 0.0 over ~7 days."""
    try:
        from datetime import datetime
        now = datetime.fromisoformat(now_ts.replace("Z", "+00:00"))
        then = datetime.fromisoformat(item_ts.replace("Z", "+00:00"))
        delta_seconds = (now - then).total_seconds()
        # Half-life of 3 days
        half_life = 3 * 24 * 3600
        # Exponential decay: score = 2^(-delta/halflife)
        score = 2.0 ** (-delta_seconds / half_life)
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.5

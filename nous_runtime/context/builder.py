# -*- coding: utf-8 -*-
"""Context Builder — orchestrates providers into a ContextSnapshot.

Pipeline:
  Request → Collect (providers) → Normalize → Filter → Rank → Snapshot
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import replace
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
from nous_runtime.context.token_estimator import estimate_tokens
from nous_runtime.core.redaction import contains_sensitive_value

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
PROTECTED_CONTEXT_CLASSES = frozenset(
    {"governance_system", "active_objective", "active_plan"}
)
PROVIDER_COLLECTION_LIMIT = 100


class ContextBudgetError(ContextBuildError):
    """Required context cannot fit the admitted input or item bound."""


# Default provider registry


def _default_providers(workspace: str = "") -> list[ContextProvider]:
    """Return the standard set of context providers."""
    if workspace:
        from pathlib import Path

        path = Path(workspace).expanduser().resolve()
        state_root = str(path if path.name == ".nous" else path / ".nous")
    else:
        state_root = ""
    return [
        MemoryProvider(state_root),
        ProjectProvider(state_root),
        AgentProvider(state_root),
        DeviceProvider(workspace),
        DecisionProvider(state_root),
    ]


# Builder


class ContextBuilder:
    """Orchestrates context collection, normalization, filtering, and snapshot creation.

    Usage::

        builder = ContextBuilder(workspace="/path/to/.nous")
        snapshot = builder.build(BuildRequest(intent="continue project X"))
    """

    def __init__(
        self,
        workspace: str = "",
        providers: list[ContextProvider] | None = None,
        extra_providers: tuple[ContextProvider, ...] = (),
    ):
        if not workspace and providers is None:
            from nous_runtime.project.workspace import find_workspace

            workspace = str(find_workspace(allow_uninitialized=True) or "")
        self._workspace = workspace
        self._providers = (
            providers if providers is not None else _default_providers(workspace)
        ) + list(extra_providers)

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
            _budget_settings(request)
            # Phase 1 — Collect from all providers
            raw_items = self._collect(request)
            raw_count = len(raw_items)
            raw_items = [
                replace(
                    item,
                    metadata={
                        **item.metadata,
                        "source_position": position,
                        "original_content_sha256": hashlib.sha256(
                            item.content.encode("utf-8")
                        ).hexdigest(),
                        "original_content_characters": len(item.content),
                    },
                )
                for position, item in enumerate(raw_items)
                if isinstance(item, ContextItem) and isinstance(item.metadata, dict)
            ]

            # Phase 2 — Normalize (dedup, fill defaults)
            normalized = self._normalize(raw_items)

            # Phase 3 — Filter (permissions, relevance)
            filtered = self._filter(normalized, request)

            # Phase 4 — Rank (scoring and sorting)
            ranked = self._rank(filtered, request)

            # Phase 5 — Build snapshot
            selected, budget_profile = self._apply_token_budgets(ranked, request)
            snapshot = self._assemble(selected, request)

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            object.__setattr__(
                snapshot,
                "metadata",
                {
                    **snapshot.metadata,
                    "build_duration_ms": elapsed_ms,
                    "raw_count": raw_count,
                    "filtered_count": len(filtered),
                    "duplicate_suppressed": len(raw_items) - len(normalized),
                    "truncation_explanation": budget_profile["truncated"],
                    "context_build_profile": {
                        "duration_ms": elapsed_ms,
                        "tokens_by_class": budget_profile["tokens_by_class"],
                        "token_budgets": budget_profile["token_budgets"],
                        "max_input_tokens": budget_profile["max_input_tokens"],
                        "estimated_input_tokens": sum(
                            budget_profile["tokens_by_class"].values()
                        ),
                        "token_measurement": "estimated",
                        "collection_limit_per_provider": PROVIDER_COLLECTION_LIMIT,
                    },
                    **(
                        {"context_binding": dict(request.metadata["context_binding"])}
                        if "context_binding" in request.metadata
                        else {}
                    ),
                    "citation_coverage": _citation_coverage(selected),
                },
            )

            _log.info(
                "Built snapshot %s: %d raw → %d filtered → %d ranked (%d ms)",
                snapshot.id,
                len(raw_items),
                len(filtered),
                len(ranked),
                elapsed_ms,
            )
            return snapshot

        except ContextBuildError:
            raise
        except Exception as exc:
            raise ContextBuildError("Context build failed") from exc

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
                    request_hint=request.context_hint or request.intent,
                    # Collection has a separate bound so low output item
                    # limits cannot hide a later mandatory objective/plan.
                    limit=PROVIDER_COLLECTION_LIMIT,
                )
                all_items.extend(items)
            except Exception:
                _log.warning("Context provider collection failed")

        return all_items

    def _normalize(self, items: list[ContextItem]) -> list[ContextItem]:
        """Deduplicate only identical content with the same source and permission."""
        seen: set[str] = set()
        seen_item_ids: set[str] = set()
        result: list[ContextItem] = []

        for item in items:
            # Validate and skip invalid items
            errors = item.validate()
            if errors:
                _log.debug("Skipping invalid item %s: %s", item.item_id, errors)
                continue

            dedup_key = hashlib.sha256(
                json.dumps(
                    {
                        "source_type": item.source_type,
                        "source_id": item.source_id or item.item_id,
                        "content": item.content,
                        "permission": item.permission,
                        "owner_id": item.metadata.get("owner_id"),
                        "context_class": _context_class(item),
                        "source_version": item.metadata.get("source_version")
                        or item.metadata.get("file_sha256"),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            if dedup_key in seen:
                continue
            if item.item_id in seen_item_ids:
                raise ContextBuildError("Context source item identifiers are ambiguous")
            seen.add(dedup_key)
            seen_item_ids.add(item.item_id)

            result.append(item)

        return result

    def _filter(
        self, items: list[ContextItem], request: BuildRequest
    ) -> list[ContextItem]:
        """Filter items by permissions, source restrictions, and relevance threshold."""
        filtered: list[ContextItem] = []

        for item in items:
            if request.sources and item.source_type not in request.sources:
                continue
            if contains_sensitive_value(json.dumps(item.to_dict(), ensure_ascii=False)):
                continue
            guard = request.metadata.get("context_guard")
            context = request.metadata.get("authorization_context")
            if guard is not None:
                from nous_runtime.context.security import ContextGuard

                if not isinstance(
                    guard, ContextGuard
                ) or not guard.check_item_permission(
                    item,
                    actor=getattr(context, "subject_id", ""),
                    actor_type=str(request.metadata.get("actor_type") or ""),
                    authorization_context=context,
                    purpose=str(request.metadata.get("purpose") or ""),
                ):
                    continue
            elif item.permission != "read":
                # A request flag is not admission for sensitive source data.
                continue

            # Filter out items below minimum importance
            min_importance = request.metadata.get("min_importance", 0.0)
            protected = _context_class(item) in PROTECTED_CONTEXT_CLASSES
            if not protected and item.importance < min_importance:
                continue

            # Filter out items below minimum confidence
            min_confidence = request.metadata.get("min_confidence", 0.0)
            if not protected and item.confidence < min_confidence:
                continue

            filtered.append(item)

        return filtered

    def _rank(
        self, items: list[ContextItem], request: BuildRequest
    ) -> list[ContextItem]:
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
        return [item for _, item in scored]

    def _apply_token_budgets(
        self,
        items: list[ContextItem],
        request: BuildRequest,
    ) -> tuple[list[ContextItem], dict[str, Any]]:
        budgets, max_input_tokens = _budget_settings(request)
        used = {name: 0 for name in CONTEXT_CLASSES}
        selected: list[ContextItem] = []
        truncated: list[dict[str, Any]] = []
        protected = [
            item for item in items if _context_class(item) in PROTECTED_CONTEXT_CLASSES
        ]
        if (
            len(protected) > request.max_items
            or sum(_estimated_tokens(item.content) for item in protected)
            > max_input_tokens
        ):
            raise ContextBudgetError(
                "Required objective or governance context exceeds the admitted input bound"
            )
        # Protected classes retain complete content and may borrow optional
        # class space. This priority is selection, never execution authority.
        ordered = protected + [
            item
            for item in items
            if _context_class(item) not in PROTECTED_CONTEXT_CLASSES
        ]
        for item in ordered:
            context_class = _context_class(item)
            tokens = _estimated_tokens(item.content)
            reason = ""
            if len(selected) >= request.max_items:
                reason = "context_item_budget"
            elif sum(used.values()) + tokens > max_input_tokens:
                reason = "context_input_token_budget"
            elif (
                context_class not in PROTECTED_CONTEXT_CLASSES
                and used[context_class] + tokens > budgets[context_class]
            ):
                reason = "context_class_token_budget"
            if reason:
                truncated.append(
                    {
                        "item_id": item.item_id,
                        "source_id": item.source_id,
                        "source_type": item.source_type,
                        "permission": item.permission,
                        "context_class": context_class,
                        "estimated_tokens": tokens,
                        "source_position": item.metadata.get("source_position"),
                        "original_content_sha256": item.metadata.get(
                            "original_content_sha256"
                        ),
                        "original_content_characters": len(item.content),
                        "included_characters": 0,
                        "status": "omitted",
                        "reason": reason,
                    }
                )
                continue
            used[context_class] += tokens
            selected.append(
                replace(
                    item,
                    metadata={
                        **item.metadata,
                        "context_class": context_class,
                        "source_version_key": item.source_version_key,
                        "source_version_measurement": "reported"
                        if item.metadata.get("source_version")
                        or item.metadata.get("file_sha256")
                        else "derived",
                        "included_position": len(selected),
                        "included_content_sha256": hashlib.sha256(
                            item.content.encode("utf-8")
                        ).hexdigest(),
                        "included_content_characters": len(item.content),
                        "estimated_tokens": tokens,
                        "inclusion": "included",
                    },
                )
            )
        return selected, {
            "tokens_by_class": used,
            "token_budgets": budgets,
            "truncated": truncated,
            "max_input_tokens": max_input_tokens,
        }

    def _assemble(
        self, items: list[ContextItem], request: BuildRequest
    ) -> ContextSnapshot:
        """Assemble the final ContextSnapshot from ranked items."""
        sources = sorted({item.source_type for item in items})

        # Compute aggregate confidence
        if items:
            agg_confidence = sum(i.confidence for i in items) / len(items)
        else:
            agg_confidence = 0.0

        # Partition items into source-aligned sections
        memory_items = [
            i.to_dict() for i in items if i.source_type == ContextSource.MEMORY.value
        ]
        decision_items = [
            i.to_dict() for i in items if i.source_type == ContextSource.DECISION.value
        ]
        retrieval_items = [
            i.to_dict() for i in items if i.source_type == ContextSource.RETRIEVAL.value
        ]
        experience_items = [
            i.to_dict()
            for i in items
            if i.source_type == ContextSource.EXPERIENCE.value
        ]

        # Extract project/agent/device context as summary dicts
        project_ctx: dict[str, Any] = {"project_id": request.project_id}
        for i in items:
            if (
                i.source_type == ContextSource.PROJECT.value
                and "project" in i.content.lower()
            ):
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


def build_context(
    request: BuildRequest,
    workspace: str = "",
    *,
    extra_providers: tuple[ContextProvider, ...] = (),
) -> ContextSnapshot:
    """One-shot context build with default providers.

    Args:
        request: What context to build.
        workspace: Optional workspace path.

    Returns:
        A ContextSnapshot.
    """
    builder = ContextBuilder(workspace=workspace, extra_providers=extra_providers)
    return builder.build_context(request)


# Internal helpers


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _estimated_tokens(content: str) -> int:
    return max(1, estimate_tokens(content))


def _budget_settings(request: BuildRequest) -> tuple[dict[str, int], int]:
    configured = request.metadata.get("token_budgets") or {}
    if not isinstance(configured, dict):
        raise ContextBuildError("Context class token bounds must be a mapping")
    budgets: dict[str, int] = {}
    for name in CONTEXT_CLASSES:
        value = configured.get(name, DEFAULT_TOKEN_BUDGETS[name])
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContextBuildError(
                "Context class token bounds must be nonnegative integers"
            )
        budgets[name] = value
    max_input_tokens = request.metadata.get("max_input_tokens", sum(budgets.values()))
    if (
        isinstance(max_input_tokens, bool)
        or not isinstance(max_input_tokens, int)
        or max_input_tokens <= 0
    ):
        raise ContextBuildError("Context input token bound must be a positive integer")
    if (
        isinstance(request.max_items, bool)
        or not isinstance(request.max_items, int)
        or request.max_items <= 0
    ):
        raise ContextBuildError("Context item bound must be a positive integer")
    return budgets, max_input_tokens


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
        item for item in items if item.source_type == ContextSource.RETRIEVAL.value
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

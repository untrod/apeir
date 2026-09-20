# -*- coding: utf-8 -*-
"""DecisionProvider — reads context from the decision store."""

from __future__ import annotations

import logging

from nous_runtime.context.models import ContextItem
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.types import ProviderHealth

_log = logging.getLogger("nous.context.providers.decision")


class DecisionProvider:
    """Collects context items from the runtime decision store.

    Reads past decisions, outcomes, and decision timelines.
    """

    source_type: str = ContextSource.DECISION.value

    def __init__(self, workspace_path: str = ""):
        self._workspace = workspace_path



    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        """Collect decision context items."""
        items: list[ContextItem] = []
        try:
            from nous_runtime.intelligence.store import JsonlDecisionStore
            from nous_runtime.project.workspace import find_workspace

            ws = self._workspace or find_workspace()
            if ws is None:
                return items

            store = JsonlDecisionStore(ws)

            # Recent decisions
            decisions = store.list_decisions(limit=limit)
            for dec in decisions:
                dec_id = getattr(dec, "decision_id", "")
                goal = getattr(dec, "goal_summary", getattr(dec, "goal", ""))
                status = getattr(dec, "status", getattr(dec, "decision_status", ""))
                confidence = getattr(dec, "confidence", 0.5)

                content_parts = [f"Decision: {goal}"] if goal else [f"Decision {dec_id}"]
                if status:
                    content_parts.append(f"[{status}]")

                items.append(ContextItem(
                    content=" ".join(content_parts),
                    source_type=ContextSource.DECISION.value,
                    source_id=dec_id,
                    created_at=getattr(dec, "created_at", ""),
                    importance=0.7,
                    confidence=float(confidence) if confidence else 0.5,
                    permission="read",
                    tags=("decision", status),
                ))

            # Incomplete decisions are particularly relevant
            incomplete = store.find_incomplete_decisions()
            for dec in incomplete:
                dec_id = getattr(dec, "decision_id", "")
                goal = getattr(dec, "goal_summary", getattr(dec, "goal", ""))
                items.append(ContextItem(
                    content=f"Incomplete decision: {goal}",
                    source_type=ContextSource.DECISION.value,
                    source_id=dec_id,
                    importance=0.85,
                    confidence=0.9,
                    permission="read",
                    tags=("decision", "incomplete", "action_needed"),
                ))

        except Exception as exc:
            _log.warning("DecisionProvider.collect failed: %s", exc)

        return items[:limit]



    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {iid: f"Decision context item {iid} — sourced from decision store." for iid in item_ids}

    def health(self) -> ProviderHealth:
        available = False
        item_count = 0
        last = ""
        error = ""
        try:
            from nous_runtime.intelligence.store import JsonlDecisionStore
            from nous_runtime.project.workspace import find_workspace
            ws = find_workspace()
            if ws:
                store = JsonlDecisionStore(ws)
                decisions = store.list_decisions(limit=100)
                available = True
                item_count = len(decisions)
                if decisions:
                    last = getattr(decisions[0], "created_at", "")
        except Exception as exc:
            error = str(exc)
        return ProviderHealth(
            source=ContextSource.DECISION.value,
            available=available,
            item_count=item_count,
            last_collected_at=last,
            error=error,
        )

# -*- coding: utf-8 -*-
"""MemoryProvider -reads context from the project memory stores (JSONL)."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.context.models import ContextItem
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.types import ProviderHealth

_log = logging.getLogger("nous.context.providers.memory")


class MemoryProvider:
    """Collects context items from the project memory engine.

    Reads facts, summaries, events, decisions, and experiences from the
    workspace JSONL memory stores.  Does NOT own the data -only reads it.
    """

    source_type: str = ContextSource.MEMORY.value

    def __init__(self, workspace_path: str = ""):
        self._workspace = workspace_path

    def _get_workspace(self) -> str | None:
        if self._workspace:
            return self._workspace
        # Try to find workspace
        try:
            from nous_runtime.project.workspace import find_workspace
            ws = find_workspace()
            return ws
        except Exception:
            return None



    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        """Collect memory context items."""
        items: list[ContextItem] = []
        ws = self._get_workspace()
        if ws is None:
            return items

        try:
            from nous_runtime.project.memory import active_facts, read_recent, search_memory

            # 1. Active facts (most important)
            facts = active_facts(workspace=ws)
            for fact in facts[: max(limit // 4, 10)]:
                items.append(ContextItem(
                    content=f"{fact.key}: {fact.value}",
                    source_type=ContextSource.MEMORY.value,
                    source_id=getattr(fact, "memory_id", ""),
                    created_at=getattr(fact, "created_at", ""),
                    importance=0.8,
                    confidence=getattr(fact, "confidence", 0.8),
                    permission="read",
                    tags=("fact",),
                ))

            # 2. Recent records
            recent = read_recent(limit=max(limit // 2, 20), workspace=ws)
            for rec in recent:
                items.append(ContextItem(
                    content=self._summarise_record(rec),
                    source_type=ContextSource.MEMORY.value,
                    source_id=getattr(rec, "memory_id", ""),
                    created_at=getattr(rec, "created_at", ""),
                    importance=0.5,
                    confidence=getattr(rec, "confidence", 0.7),
                    permission="read",
                    tags=(getattr(rec, "record_type", "memory"),),
                ))

            # 3. Search if hint provided
            if request_hint:
                results = search_memory(ws, request_hint, limit=max(limit // 4, 5))
                for rec in results:
                    items.append(ContextItem(
                        content=self._summarise_record(rec),
                        source_type=ContextSource.MEMORY.value,
                        source_id=getattr(rec, "memory_id", ""),
                        created_at=getattr(rec, "created_at", ""),
                        importance=0.6,
                        confidence=0.6,
                        permission="read",
                        tags=("search_result",),
                    ))

        except Exception as exc:
            _log.warning("MemoryProvider.collect failed: %s", exc)

        return items[:limit]



    def explain(self, item_ids: list[str]) -> dict[str, str]:
        """Explain memory context items."""
        explanations: dict[str, str] = {}
        for iid in item_ids:
            explanations[iid] = f"Memory record {iid} -sourced from project memory store."
        return explanations

    def health(self) -> ProviderHealth:
        """Check memory provider health."""
        ws = self._get_workspace()
        available = ws is not None
        item_count = 0
        last = ""
        error = ""

        if available:
            try:
                from nous_runtime.project.memory import read_recent
                recent = read_recent(limit=100, workspace=ws)
                item_count = len(recent)
                if recent:
                    last = getattr(recent[0], "created_at", "")
            except Exception as exc:
                error = str(exc)
                available = False

        return ProviderHealth(
            source=ContextSource.MEMORY.value,
            available=available,
            item_count=item_count,
            last_collected_at=last,
            error=error,
        )



    @staticmethod
    def _summarise_record(rec: Any) -> str:
        """Produce a short summary of a memory record."""
        rt = getattr(rec, "record_type", "?")
        if rt == "event":
            return f"[Event] {getattr(rec, 'event_type', '')}: {getattr(rec, 'detail', '')}"
        elif rt == "fact":
            return f"[Fact] {getattr(rec, 'key', '')} = {getattr(rec, 'value', '')}"
        elif rt == "decision":
            return f"[Decision] {getattr(rec, 'question', '')} 鈫?{getattr(rec, 'answer', '')}"
        elif rt == "summary":
            return f"[Summary] {getattr(rec, 'title', '')}: {getattr(rec, 'content', '')}"
        elif rt == "experience":
            return f"[Experience] {getattr(rec, 'capability_id', '')} outcome={getattr(rec, 'outcome', '')}"
        return f"[{rt}] {getattr(rec, 'memory_id', '?')}"

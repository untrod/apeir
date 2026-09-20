"""Explicit TaskGraph integration points for retrieval context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from nous_runtime.retrieval.gateway import RetrievalGateway
from nous_runtime.retrieval.models import RetrievalQuery, RetrievalScope
from nous_runtime.retrieval.ranking import ContextPack, pack_context


@dataclass(frozen=True)
class TaskRetrievalContext:
    task_id: str
    query: str
    pack: ContextPack
    metadata: dict[str, Any]


class RetrievalInjectionMode(str, Enum):
    DISABLED = "disabled"
    EXPLICIT = "explicit"
    POLICY = "policy"


@dataclass(frozen=True)
class RetrievalContextDecision:
    enabled: bool
    mode: RetrievalInjectionMode
    reason: str
    query_id: str = ""
    selected_record_ids: tuple[str, ...] = ()


class TaskGraphRetrievalBridge:
    def __init__(self, gateway: RetrievalGateway, mode: RetrievalInjectionMode = RetrievalInjectionMode.EXPLICIT):
        self.gateway = gateway
        self.mode = mode

    def build_task_context(
        self,
        *,
        task_id: str,
        query_text: str,
        workspace_id: str,
        project_id: str,
        max_tokens: int = 1200,
    ) -> TaskRetrievalContext:
        decision = self.decide(task_id=task_id, query_text=query_text, explicit=True)
        if not decision.enabled:
            return TaskRetrievalContext(
                task_id=task_id,
                query=query_text,
                pack=pack_context([], max_tokens=max_tokens),
                metadata={"decision": decision},
            )
        query = RetrievalQuery(
            text=query_text,
            scope=RetrievalScope(workspace_id=workspace_id, project_ids=(project_id,)),
        )
        results = self.gateway.search(query)
        pack = pack_context(results, max_tokens=max_tokens)
        selected = tuple(item.record.record_id for item in results[: len(pack.items)])
        decision = RetrievalContextDecision(
            enabled=True,
            mode=self.mode,
            reason="task explicitly requested project memory",
            query_id=query.query_id,
            selected_record_ids=selected,
        )
        return TaskRetrievalContext(
            task_id=task_id,
            query=query_text,
            pack=pack,
            metadata={"result_count": len(results), "dropped": len(pack.dropped_record_ids), "decision": decision},
        )

    def decide(self, *, task_id: str, query_text: str, explicit: bool = False) -> RetrievalContextDecision:
        if self.mode == RetrievalInjectionMode.DISABLED:
            return RetrievalContextDecision(False, self.mode, "retrieval context injection is disabled")
        if self.mode == RetrievalInjectionMode.EXPLICIT and not explicit:
            return RetrievalContextDecision(False, self.mode, "task did not explicitly request retrieval context")
        return RetrievalContextDecision(True, self.mode, "retrieval context allowed by explicit request")

# -*- coding: utf-8 -*-
"""Experience Collector — auto-collects experiences from runtime sources.

Sources: Decision Runtime, Agent Runtime, Evaluation Runtime.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.schema import ExperienceSource
from nous_runtime.experience.store import ExperienceStore

_log = logging.getLogger("nous.experience.collector")


class ExperienceCollector:
    """Collects experiences from all runtime sources.

    Usage::

        collector = ExperienceCollector(workspace)
        experiences = collector.collect_from_evaluation(eval_record)
        for exp in experiences:
            store.save(exp)
    """

    def __init__(self, workspace: str = "", store: ExperienceStore | None = None):
        self._workspace = workspace
        self._store = store or ExperienceStore(workspace)


    # Collection from Evaluation


    def collect_from_evaluation(self, eval_record: Any) -> list[ExperienceRecord]:
        """Extract experience from an evaluation record."""
        experiences: list[ExperienceRecord] = []
        try:
            target_type = getattr(eval_record, "target_type", "")
            target_id = getattr(eval_record, "target_id", "")
            composite = getattr(eval_record, "composite_score", 0.0)
            passed = getattr(eval_record, "passed", False)
            issues = getattr(eval_record, "issues", ())
            recommendation = getattr(eval_record, "recommendation", "")

            context_hash = hashlib.sha256(f"{target_type}:{target_id}".encode()).hexdigest()[:16]

            lessons: list[str] = []
            if passed:
                lessons.append(f"Approach successful for {target_type}")
            if issues:
                for issue in issues[:3]:
                    lessons.append(f"Issue found: {issue}")

            experiences.append(ExperienceRecord(
                source_type=ExperienceSource.EVALUATION.value,
                task_type=target_type,
                task_summary=f"Evaluated {target_type}/{target_id}",
                context_hash=context_hash,
                action=f"evaluate_{target_type}",
                result="success" if passed else "failure",
                evaluation_score=composite,
                success=passed,
                failure_reason="; ".join(issues[:2]) if issues else "",
                lessons=tuple(lessons),
                confidence=getattr(eval_record, "confidence", 0.5),
                evaluation_id=getattr(eval_record, "id", ""),
                tags=(target_type, recommendation),
            ))
        except Exception as exc:
            _log.warning("Collect from evaluation failed: %s", exc)
        return experiences


    # Collection from Decision


    def collect_from_decision(self, decision: Any) -> list[ExperienceRecord]:
        """Extract experience from a runtime decision."""
        experiences: list[ExperienceRecord] = []
        try:
            dec_id = getattr(decision, "decision_id", "")
            goal = getattr(decision, "goal_summary", getattr(decision, "goal", ""))
            selected = getattr(decision, "selected_candidate", "")
            decision_type = getattr(decision, "decision_type", "")

            exp = ExperienceRecord(
                source_type=ExperienceSource.DECISION.value,
                task_type=str(decision_type),
                task_summary=str(goal)[:200],
                context_hash=hashlib.sha256(str(goal).encode()).hexdigest()[:16],
                action=f"decide_{decision_type}",
                result="success",
                success=True,
                lessons=(f"Selected candidate: {selected}",),
                confidence=0.7,
                decision_id=dec_id,
            )
            experiences.append(exp)
        except Exception as exc:
            _log.warning("Collect from decision failed: %s", exc)
        return experiences


    # Collection from Agent execution


    def collect_from_agent(self, agent_id: str, capability_id: str,
                           success: bool, error: str = "", duration_ms: int = 0) -> list[ExperienceRecord]:
        """Record an agent execution as experience."""
        lessons: list[str] = []
        if success:
            lessons.append(f"Agent {agent_id} succeeded on {capability_id}")
        else:
            lessons.append(f"Agent {agent_id} failed on {capability_id}: {error}")

        return [ExperienceRecord(
            source_type=ExperienceSource.AGENT.value,
            task_type=capability_id,
            task_summary=f"Execute {capability_id} via {agent_id}",
            context_hash=hashlib.sha256(f"{agent_id}:{capability_id}".encode()).hexdigest()[:16],
            action=f"execute_{capability_id}",
            agent_id=agent_id,
            capability_id=capability_id,
            result="success" if success else "failure",
            success=success,
            failure_reason=error,
            lessons=tuple(lessons),
            confidence=0.8 if success else 0.4,
            metadata={"duration_ms": duration_ms},
        )]


    # Bulk collect & persist


    def collect_and_persist(self, sources: list[str] | None = None) -> int:
        """Collect from all available sources and persist. Returns count saved."""
        count = 0
        sources = sources or ["evaluation", "decision"]

        if "evaluation" in sources:
            try:
                from nous_runtime.evaluation.history import EvaluationHistory
                history = EvaluationHistory(self._workspace)
                for record in history.list(limit=50):
                    for exp in self.collect_from_evaluation(record):
                        if self._store.save(exp):
                            count += 1
            except Exception as exc:
                _log.warning("Bulk collect from evaluation failed: %s", exc)

        if "decision" in sources:
            try:
                from nous_runtime.intelligence.store import JsonlDecisionStore
                from nous_runtime.project.workspace import find_workspace
                ws = self._workspace or find_workspace()
                if ws:
                    store = JsonlDecisionStore(ws)
                    for dec in store.list_decisions(limit=50):
                        for exp in self.collect_from_decision(dec):
                            if self._store.save(exp):
                                count += 1
            except Exception as exc:
                _log.warning("Bulk collect from decision failed: %s", exc)

        return count

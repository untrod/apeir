# -*- coding: utf-8 -*-
"""Recommendation Engine — user-facing suggestions based on experience."""

from __future__ import annotations

import logging

from nous_runtime.experience.models import Recommendation
from nous_runtime.experience.schema import RecommendationType
from nous_runtime.experience.similarity import SimilarityEngine
from nous_runtime.experience.store import ExperienceStore

_log = logging.getLogger("nous.experience.recommendation")


class RecommendationEngine:
    """Generates user-facing recommendations from experience data.

    Usage::

        engine = RecommendationEngine(store)
        recs = engine.recommend(task_description="deploy Jetson environment")
        for r in recs:
            print(f"{r.title} (confidence: {r.confidence:.2f})")
    """

    def __init__(self, store: ExperienceStore | None = None):
        self._store = store or ExperienceStore()
        self._similarity = SimilarityEngine(self._store)



    def recommend(self, task_description: str, limit: int = 10) -> list[Recommendation]:
        """Generate recommendations for a given task.

        Looks at similar past experiences and extracts:
          - Which agents worked best
          - Which approaches succeeded
          - What to watch out for
        """
        recommendations: list[Recommendation] = []

        # Find similar experiences
        similar = self._similarity.find_similar_tasks(task_description, limit=50)
        if not similar:
            return recommendations

        experiences = [exp for exp, _ in similar]

        # 1. Agent recommendation
        agent_rec = self._recommend_agent(experiences, task_description)
        if agent_rec:
            recommendations.append(agent_rec)

        # 2. Approach recommendation
        approach_rec = self._recommend_approach(experiences, task_description)
        if approach_rec:
            recommendations.append(approach_rec)

        # 3. Warning recommendation
        warning_rec = self._recommend_warnings(experiences, task_description)
        if warning_rec:
            recommendations.append(warning_rec)

        return recommendations[:limit]



    def _recommend_agent(self, experiences: list, task_desc: str) -> Recommendation | None:
        by_agent: dict[str, list] = {}
        for e in experiences:
            if e.agent_id:
                by_agent.setdefault(e.agent_id, []).append(e)

        if not by_agent:
            return None

        best_agent = ""
        best_score = 0.0
        best_count = 0
        for aid, exps in by_agent.items():
            if len(exps) < 2:
                continue
            sr = sum(1 for e in exps if e.success) / len(exps)
            if sr > best_score:
                best_score = sr
                best_agent = aid
                best_count = len(exps)

        if not best_agent:
            return None

        return Recommendation(
            recommendation_type=RecommendationType.AGENT.value,
            title=f"Recommended agent: {best_agent}",
            description=f"Based on {best_count} similar tasks, agent '{best_agent}' "
                        f"achieved {best_score:.0%} success rate.",
            suggested_agent=best_agent,
            confidence=min(0.90, 0.4 + best_score * 0.5),
            reason=f"Top performer on {best_count} similar tasks.",
            supporting_experiences=tuple(e.id for e in by_agent[best_agent][:5]),
        )

    def _recommend_approach(self, experiences: list, task_desc: str) -> Recommendation | None:
        """Recommend an approach based on successful experiences."""
        successes = [e for e in experiences if e.success and e.lessons]
        if not successes:
            return None

        # Gather lessons from successful experiences
        all_lessons: list[str] = []
        for e in successes[:10]:
            all_lessons.extend(e.lessons)

        if not all_lessons:
            return None

        top_lessons = all_lessons[:5]
        return Recommendation(
            recommendation_type=RecommendationType.APPROACH.value,
            title="Recommended approach",
            description=f"Based on {len(successes)} successful similar tasks.",
            suggested_approach="; ".join(top_lessons[:3]),
            confidence=0.75,
            reason=f"Derived from {len(successes)} successful experiences.",
            supporting_experiences=tuple(e.id for e in successes[:5]),
        )

    def _recommend_warnings(self, experiences: list, task_desc: str) -> Recommendation | None:
        """Generate warnings from past failures."""
        failures = [e for e in experiences if not e.success and e.failure_reason]
        if not failures:
            return None

        reasons = set(e.failure_reason[:100] for e in failures[:10] if e.failure_reason)
        if not reasons:
            return None

        return Recommendation(
            recommendation_type=RecommendationType.APPROACH.value,
            title="Common pitfalls to avoid",
            description=f"Past failures include: {'; '.join(list(reasons)[:3])}",
            confidence=0.70,
            reason=f"Observed in {len(failures)} similar failed tasks.",
            supporting_experiences=tuple(e.id for e in failures[:5]),
        )

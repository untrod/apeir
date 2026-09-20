# -*- coding: utf-8 -*-
"""Research Planner — generates structured research plans before web access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchPlan:
    plan_id: str = ""
    research_questions: list[str] = field(default_factory=list)
    required_source_types: list[str] = field(default_factory=lambda: ["academic", "documentation", "web"])
    freshness_requirements: dict[str, str] = field(default_factory=dict)
    primary_source_requirements: bool = True
    min_independent_sources: int = 3
    conflict_criteria: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=lambda: ["min_sources_reached", "all_questions_answered", "diminishing_returns"])
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    privacy_restrictions: list[str] = field(default_factory=list)
    max_sources: int = 20
    max_time_minutes: int = 30


class ResearchPlanner:
    """Generates structured research plans before any web access."""

    def plan(self, topic: str, requirements: dict[str, Any] | None = None) -> ResearchPlan:
        req = requirements or {}
        plan = ResearchPlan(
            plan_id=f"rplan_{uuid.uuid4().hex[:12]}",
            research_questions=self._generate_questions(topic),
            min_independent_sources=int(req.get("min_sources", 3)),
            freshness_requirements=req.get("freshness", {"web": "30d", "academic": "2y", "documentation": "latest"}),
            allowed_domains=req.get("allowed_domains", []),
            blocked_domains=req.get("blocked_domains", ["pinterest.com", "quora.com"]),
        )
        return plan

    def _generate_questions(self, topic: str) -> list[str]:
        return [
            f"What is the current state of {topic}?",
            f"What are the main approaches to {topic}?",
            f"What evidence supports each approach to {topic}?",
            f"What are the known limitations of {topic}?",
            f"Are there conflicting findings about {topic}?",
        ]

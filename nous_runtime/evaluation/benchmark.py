# -*- coding: utf-8 -*-
"""Agent Benchmark System — evaluate agent capabilities systematically.

Tracks: success rate, latency, cost, error type per task category.
Connects to Phase 2 Agent Runtime for agent profiles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any


_log = logging.getLogger("nous.evaluation.benchmark")



# Benchmark task


@dataclass(frozen=True)
class BenchmarkTask:
    """A single benchmark task definition."""
    task_id: str = ""
    category: str = ""           # coding, debugging, analysis, docs, security
    description: str = ""
    expected_outcome: str = ""   # What success looks like
    difficulty: str = "medium"   # easy, medium, hard
    time_limit_ms: int = 300_000
    metadata: dict[str, Any] = field(default_factory=dict)



# Benchmark result


@dataclass
class BenchmarkResult:
    """Result of running one benchmark task."""
    task_id: str = ""
    category: str = ""
    agent_id: str = ""
    success: bool = False
    latency_ms: int = 0
    cost_usd: float = 0.0
    error_type: str = ""         # Empty if success
    token_usage: int = 0
    score: float = 0.0           # 0.0–1.0
    notes: str = ""



# Agent Benchmark Profile


@dataclass
class AgentBenchmarkProfile:
    """Aggregated benchmark results for one agent."""
    agent_id: str = ""
    total_tasks: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    avg_token_usage: float = 0.0
    avg_score: float = 0.0

    # Per-category breakdown
    category_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Error distribution
    error_distribution: dict[str, int] = field(default_factory=dict)

    # Overall rating
    rating: str = ""             # excellent, good, fair, poor

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "success_count": self.success_count,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_cost_usd": self.avg_cost_usd,
            "avg_token_usage": self.avg_token_usage,
            "avg_score": self.avg_score,
            "category_results": dict(self.category_results),
            "error_distribution": dict(self.error_distribution),
            "rating": self.rating,
        }



# Benchmark Runner


BENCHMARK_CATEGORIES = ["coding", "debugging", "analysis", "documentation", "security"]


class BenchmarkRunner:
    """Runs benchmark tasks and builds agent profiles.

    Usage::

        runner = BenchmarkRunner()
        runner.add_task(BenchmarkTask(
            task_id="code_01", category="coding",
            description="Refactor a Python module",
        ))
        result = runner.run_task("code_01", agent_id="agent_claude")
        profile = runner.build_profile("agent_claude")
    """

    def __init__(self):
        self._tasks: dict[str, BenchmarkTask] = {}
        self._results: dict[str, list[BenchmarkResult]] = {}  # agent_id → results

    def add_task(self, task: BenchmarkTask) -> None:
        self._tasks[task.task_id] = task

    def add_tasks(self, tasks: list[BenchmarkTask]) -> None:
        for t in tasks:
            self._tasks[t.task_id] = t



    def record_result(self, result: BenchmarkResult) -> None:
        """Record a benchmark result for an agent."""
        self._results.setdefault(result.agent_id, []).append(result)



    def build_profile(self, agent_id: str) -> AgentBenchmarkProfile:
        """Build an aggregated benchmark profile for an agent."""
        results = self._results.get(agent_id, [])

        if not results:
            return AgentBenchmarkProfile(agent_id=agent_id, rating="unknown")

        total = len(results)
        successes = sum(1 for r in results if r.success)

        profile = AgentBenchmarkProfile(
            agent_id=agent_id,
            total_tasks=total,
            success_count=successes,
            success_rate=successes / max(total, 1),
            avg_latency_ms=sum(r.latency_ms for r in results) / max(total, 1),
            avg_cost_usd=sum(r.cost_usd for r in results) / max(total, 1),
            avg_token_usage=sum(r.token_usage for r in results) / max(total, 1),
            avg_score=sum(r.score for r in results) / max(total, 1),
        )

        # Per-category
        for cat in BENCHMARK_CATEGORIES:
            cat_results = [r for r in results if r.category == cat]
            if cat_results:
                profile.category_results[cat] = {
                    "count": len(cat_results),
                    "success_rate": sum(1 for r in cat_results if r.success) / len(cat_results),
                    "avg_score": sum(r.score for r in cat_results) / len(cat_results),
                    "avg_latency_ms": sum(r.latency_ms for r in cat_results) / len(cat_results),
                }

        # Error distribution
        for r in results:
            if r.error_type:
                profile.error_distribution[r.error_type] = \
                    profile.error_distribution.get(r.error_type, 0) + 1

        # Rating
        sr = profile.success_rate
        if sr >= 0.90:
            profile.rating = "excellent"
        elif sr >= 0.75:
            profile.rating = "good"
        elif sr >= 0.50:
            profile.rating = "fair"
        else:
            profile.rating = "poor"

        return profile



    def list_tasks(self) -> list[BenchmarkTask]:
        return list(self._tasks.values())

    def get_results(self, agent_id: str) -> list[BenchmarkResult]:
        return self._results.get(agent_id, [])



# Predefined benchmark suites


def coding_benchmark_suite() -> list[BenchmarkTask]:
    """Standard coding benchmark tasks."""
    return [
        BenchmarkTask(
            task_id="code_refactor", category="coding",
            description="Refactor a Python module to improve readability",
            expected_outcome="Clean, passing code with no functionality change",
            difficulty="medium",
        ),
        BenchmarkTask(
            task_id="code_add_feature", category="coding",
            description="Add a new feature with tests",
            expected_outcome="Feature implemented with passing tests",
            difficulty="medium",
        ),
        BenchmarkTask(
            task_id="code_fix_bug", category="debugging",
            description="Find and fix a bug in existing code",
            expected_outcome="Bug fixed, regression tests pass",
            difficulty="medium",
        ),
        BenchmarkTask(
            task_id="code_review", category="analysis",
            description="Review code for issues and suggest improvements",
            expected_outcome="Comprehensive review with actionable suggestions",
            difficulty="medium",
        ),
        BenchmarkTask(
            task_id="code_document", category="documentation",
            description="Write documentation for a public API",
            expected_outcome="Clear, complete API documentation",
            difficulty="easy",
        ),
        BenchmarkTask(
            task_id="code_security_audit", category="security",
            description="Audit code for security vulnerabilities",
            expected_outcome="All HIGH/CRITICAL issues identified",
            difficulty="hard",
        ),
    ]

# -*- coding: utf-8 -*-
"""Ablation Study — remove one component at a time and measure impact."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AblationResult:
    """Result of ablating one component."""
    component_name: str = ""
    full_score: float = 0.0
    ablated_score: float = 0.0
    impact: float = 0.0            # positive = component helps, negative = component hurts
    relative_impact_pct: float = 0.0
    significant: bool = False


@dataclass
class AblationStudy:
    """Complete ablation study across multiple components."""
    experiment_id: str = ""
    baseline_score: float = 0.0
    components: list[str] = field(default_factory=list)
    results: list[AblationResult] = field(default_factory=list)

    def most_important(self) -> list[AblationResult]:
        return sorted(self.results, key=lambda r: -r.impact)

    def harmful_components(self) -> list[AblationResult]:
        return [r for r in self.results if r.impact < -0.01]


class AblationRunner:
    """Runs ablation studies by removing one component at a time."""

    def run(self, experiment_id: str, components: list[str], evaluate_fn: Any) -> AblationStudy:
        """Run full ablation study."""
        full_score = evaluate_fn(components)
        study = AblationStudy(experiment_id=experiment_id, baseline_score=full_score, components=components)

        for i, comp in enumerate(components):
            reduced = [c for j, c in enumerate(components) if j != i]
            ablated_score = evaluate_fn(reduced)
            impact = full_score - ablated_score
            study.results.append(AblationResult(
                component_name=comp,
                full_score=full_score,
                ablated_score=ablated_score,
                impact=impact,
                relative_impact_pct=(impact / max(abs(full_score), 0.001)) * 100,
                significant=abs(impact) > 0.02,
            ))

        return study

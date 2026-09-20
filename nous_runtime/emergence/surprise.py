# -*- coding: utf-8 -*-
"""Surprise Detection — detects unexpected emergent behaviors.

Compares predicted vs actual outcomes. Detects: unexpectedly high quality,
unexpectedly low cost, unexpected cooperation, unexpected recovery,
abnormal metric combinations.

Must distinguish: data leakage, metric bugs, evaluation exploits,
random luck, genuine emergent behavior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class AnomalyRecord:
    """Record of a surprising/anomalous outcome."""
    anomaly_id: str = ""
    genome_id: str = ""
    prediction: dict[str, float] = field(default_factory=dict)
    actual: dict[str, float] = field(default_factory=dict)
    surprise_magnitude: float = 0.0      # z-score of deviation
    affected_dimensions: list[str] = field(default_factory=list)
    possible_explanations: list[str] = field(default_factory=list)
    classification: str = ""  # data_leakage, metric_bug, evaluation_exploit, random_luck, genuine_emergence
    status: str = "anomaly"  # anomaly, emergent_candidate, validated_discovery, rejected_artifact


class SurpriseDetector:
    """Detects surprising outcomes by comparing predictions vs actuals.

    Normalizes across dimensions and flags statistically significant deviations.
    """

    def __init__(self, surprise_threshold: float = 3.0) -> None:
        self.threshold = surprise_threshold
        self._history: list[dict[str, float]] = []  # historical prediction→actual pairs

    def detect(
        self,
        predicted: dict[str, float],
        actual: dict[str, float],
    ) -> AnomalyRecord | None:
        """Detect if actual outcomes are surprising given predictions."""
        deviations = {}
        max_z = 0.0
        affected = []

        for dim in set(predicted.keys()) | set(actual.keys()):
            p = predicted.get(dim, 0.0)
            a = actual.get(dim, 0.0)
            deviation = a - p

            # Estimate std from history
            hist_std = self._historical_std(dim)
            z = abs(deviation) / max(hist_std, 0.001)
            deviations[dim] = z

            if z > self.threshold:
                affected.append(dim)
                max_z = max(max_z, z)

        if not affected:
            return None

        # Classify the surprise
        classification = self._classify(predicted, actual, deviations)

        return AnomalyRecord(
            anomaly_id=f"anom_{hash(str(actual))}",
            prediction=predicted,
            actual=actual,
            surprise_magnitude=max_z,
            affected_dimensions=affected,
            possible_explanations=self._generate_explanations(classification, affected, deviations),
            classification=classification,
            status="anomaly",
        )

    def _historical_std(self, dimension: str) -> float:
        """Estimate standard deviation from history for a dimension."""
        values = [h.get(dimension, 0) for h in self._history[-100:] if dimension in h]
        if len(values) < 2:
            return 0.1  # default
        m = sum(values) / len(values)
        return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))

    def _classify(
        self,
        predicted: dict,
        actual: dict,
        deviations: dict,
    ) -> str:
        """Classify the type of surprise."""
        # If ALL metrics improved dramatically → possible data leakage
        all_improved = all(actual.get(k, 0) > predicted.get(k, 0) for k in predicted)
        max_dev = max(deviations.values())
        if all_improved and max_dev > 5:
            return "data_leakage"

        # If only one metric changed dramatically → possible metric bug
        high_dev_count = sum(1 for z in deviations.values() if z > self.threshold)
        if high_dev_count == 1 and max_dev > 4:
            return "metric_bug"

        # If quality improved but cost/latency unchanged → possible genuine
        quality_up = actual.get("quality", 0) > predicted.get("quality", 0) + 0.1
        cost_ok = abs(actual.get("cost", 0) - predicted.get("cost", 0)) < 0.05
        if quality_up and cost_ok:
            return "genuine_emergence"

        return "random_luck"

    def _generate_explanations(
        self,
        classification: str,
        affected: list[str],
        deviations: dict,
    ) -> list[str]:
        explanations = {
            "data_leakage": ["All metrics improved simultaneously — check for data leakage", "Verify test/train split integrity"],
            "metric_bug": ["Single metric anomaly — check metric computation for bugs", "Verify evaluation harness correctness"],
            "genuine_emergence": ["Quality improved without cost increase — possible genuine emergence", "Schedule replication gate"],
            "random_luck": ["Deviations within expected random variation", f"Affected: {', '.join(affected)}"],
        }
        return explanations.get(classification, [f"Unexpected deviation in {', '.join(affected)}"])

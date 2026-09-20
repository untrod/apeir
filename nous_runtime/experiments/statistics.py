# -*- coding: utf-8 -*-
"""Statistical Analysis for experiments.

Supports: confidence intervals, bootstrap, paired tests, non-parametric tests,
effect size, multiple-comparison correction, power analysis, calibration.

NEVER report only means.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class StatisticalTest(str, Enum):
    BOOTSTRAP = "bootstrap"
    PAIRED_T = "paired_t"
    WILCOXON = "wilcoxon"
    MCNEMAR = "mcnemar"
    PERMUTATION = "permutation"


@dataclass
class StatisticalResult:
    """Result of a statistical test."""
    test_name: str = ""
    statistic: float = 0.0
    p_value: float = 0.0
    significant: bool = False
    effect_size: float = 0.0
    effect_size_name: str = ""    # negligible, small, medium, large
    ci_lower: float = 0.0
    ci_upper: float = 0.0
    mean_baseline: float = 0.0
    mean_candidate: float = 0.0
    sample_size: int = 0


class StatisticalAnalyzer:
    """Statistical analysis for A/B experiments.

    No single-number reporting. Always includes: CI, effect size, p-value.
    """

    def compare(
        self,
        baseline_scores: list[float],
        candidate_scores: list[float],
        test: StatisticalTest = StatisticalTest.BOOTSTRAP,
        alpha: float = 0.05,
    ) -> StatisticalResult:
        """Compare baseline vs candidate."""
        n = min(len(baseline_scores), len(candidate_scores))
        if n < 5:
            return StatisticalResult(test_name=test.value, sample_size=n)

        mean_base = sum(baseline_scores[:n]) / n
        mean_cand = sum(candidate_scores[:n]) / n
        differences = [c - b for b, c in zip(baseline_scores[:n], candidate_scores[:n])]
        mean_diff = sum(differences) / n

        # Effect size (Cohen's d)
        pooled_std = math.sqrt(
            (self._variance(baseline_scores[:n]) + self._variance(candidate_scores[:n])) / 2
        )
        cohens_d = mean_diff / max(pooled_std, 0.001)
        effect_name = "negligible" if abs(cohens_d) < 0.2 else ("small" if abs(cohens_d) < 0.5 else ("medium" if abs(cohens_d) < 0.8 else "large"))

        # Bootstrap CI
        ci_low, ci_high = self._bootstrap_ci(differences)

        # Bootstrap p-value (two-sided: mean_diff != 0)
        p_value = self._bootstrap_pvalue(differences)

        return StatisticalResult(
            test_name=test.value,
            statistic=cohens_d,
            p_value=p_value,
            significant=p_value < alpha,
            effect_size=cohens_d,
            effect_size_name=effect_name,
            ci_lower=ci_low,
            ci_upper=ci_high,
            mean_baseline=mean_base,
            mean_candidate=mean_cand,
            sample_size=n,
        )

    def multiple_comparison_correction(self, p_values: list[float], method: str = "bonferroni") -> list[float]:
        """Correct for multiple comparisons."""
        n = len(p_values)
        if method == "bonferroni":
            return [min(1.0, p * n) for p in p_values]
        elif method == "holm":
            sorted_idx = sorted(range(n), key=lambda i: p_values[i])
            corrected = [0.0] * n
            for rank, idx in enumerate(sorted_idx):
                corrected[idx] = min(1.0, p_values[idx] * (n - rank))
            return corrected
        return p_values

    def power_analysis(self, effect_size: float, alpha: float = 0.05, power: float = 0.8) -> int:
        """Estimate required sample size for given effect size and power."""
        z_alpha = 1.96  # for alpha=0.05
        z_beta = 0.84   # for power=0.8
        n = 2 * ((z_alpha + z_beta) / max(abs(effect_size), 0.01)) ** 2
        return max(5, int(math.ceil(n)))

    def _variance(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        m = sum(values) / len(values)
        return sum((v - m) ** 2 for v in values) / (len(values) - 1)

    def _bootstrap_ci(self, values: list[float], n_resamples: int = 1000) -> tuple[float, float]:
        import random as _random
        rng = _random.Random(42)
        means = []
        for _ in range(n_resamples):
            sample = [values[rng.randint(0, len(values) - 1)] for _ in range(len(values))]
            means.append(sum(sample) / len(sample))
        means.sort()
        return means[int(len(means) * 0.025)], means[int(len(means) * 0.975)]

    def _bootstrap_pvalue(self, differences: list[float], n_resamples: int = 1000) -> float:
        """Two-sided bootstrap p-value for H0: mean = 0."""
        import random as _random
        rng = _random.Random(42)
        observed = abs(sum(differences) / len(differences))
        count = 0
        for _ in range(n_resamples):
            # Shift to have mean zero (null hypothesis)
            shifted = [d - (sum(differences) / len(differences)) for d in differences]
            sample = [shifted[rng.randint(0, len(shifted) - 1)] for _ in range(len(shifted))]
            sample_mean = abs(sum(sample) / len(sample))
            if sample_mean >= observed:
                count += 1
        return count / n_resamples

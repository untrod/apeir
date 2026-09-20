# -*- coding: utf-8 -*-
"""Experiment Fabric — A/B testing, shadow, canary, ablation, statistics, promotion.

Each experiment has: hypothesis, baseline, candidate, dataset, metrics,
seeds, environment, sample size, statistical test, acceptance threshold.

Promotion pipeline: PROPOSED → SANDBOX → BENCHMARKED → ABLATED →
REPLICATED → SHADOW → CANARY → APPROVED → PRODUCTION.
"""

from .registry import ExperimentRegistry, ExperimentSpec, ExperimentState
from .runner import ExperimentRunner, ExperimentResult
from .service import ExperimentService
from .statistics import StatisticalAnalyzer, StatisticalTest
from .promotion import PromotionPipeline, PromotionDecision
from .ablation import AblationRunner, AblationStudy, AblationResult
from .canary import CanaryController, CanaryConfig, CanaryResult

__all__ = [
    "ExperimentRegistry", "ExperimentSpec", "ExperimentState",
    "ExperimentRunner", "ExperimentResult",
    "ExperimentService",
    "StatisticalAnalyzer", "StatisticalTest",
    "PromotionPipeline", "PromotionDecision",
    "AblationRunner", "AblationStudy", "AblationResult",
    "CanaryController", "CanaryConfig", "CanaryResult",
]

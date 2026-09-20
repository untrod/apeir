# -*- coding: utf-8 -*-
"""Research Fabric — paper ingestion, hypothesis graph, claim-code-experiment binding.

Research output ALWAYS backed by EvidenceGraph and ExperimentRegistry.
NEVER auto-fabricate citations, experimental data, or statistical results.
"""

from .papers import PaperIngestion, ResearchCard
from .hypotheses import HypothesisGraph, Hypothesis, HypothesisState
from .binding import ClaimBinding, BindingRegistry

__all__ = [
    "PaperIngestion", "ResearchCard",
    "HypothesisGraph", "Hypothesis", "HypothesisState",
    "ClaimBinding", "BindingRegistry",
]

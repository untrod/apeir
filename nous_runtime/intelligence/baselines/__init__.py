# -*- coding: utf-8 -*-
"""Baseline algorithm implementations for Nous Execution Benchmark.

Every new algorithm MUST be compared against these baselines before promotion.
14 baselines covering: model selection, agent topology, node assignment,
verification strategy, and execution locality.
"""

from .registry import BaselineRegistry, BaselinePolicy

__all__ = [
    "BaselineRegistry",
    "BaselinePolicy",
]

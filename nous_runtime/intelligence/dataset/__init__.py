# -*- coding: utf-8 -*-
"""Intelligence Dataset Registry.

Manages versioned datasets for model training, evaluation, and benchmarking.
Training/experiment code MUST read datasets through this registry, not from
unregistered directories.

Dataset types: production, sanitized, benchmark, replay, shadow, experimental,
failed, counterfactual.
"""

from .models import DatasetRecord, DatasetType
from .registry import DatasetRegistry
from .builder import DatasetBuilder

__all__ = [
    "DatasetRecord",
    "DatasetType",
    "DatasetRegistry",
    "DatasetBuilder",
]

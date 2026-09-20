# -*- coding: utf-8 -*-
"""Emergence Lab — quality-diversity optimization, novelty search, surprise detection.

FULLY ISOLATED from production. Candidates represent complete strategies:
model combinations, agent topologies, task decompositions, prompts,
context policies, tool sequences, retrieval policies, verification policies,
recovery policies, hyperparameters.

Goal: NOT a single best solution, but a diverse archive of high-quality
strategies across different cost/risk/topology/behavior regions.
"""

from .genome import CandidateGenome, GenomeEncoder
from .population import Population, Lineage
from .quality_diversity import MAPElites, QDArchive, NoveltySearch
from .surprise import SurpriseDetector, AnomalyRecord
from .replication import ReplicationGate, ReplicationResult

__all__ = [
    "CandidateGenome", "GenomeEncoder",
    "Population", "Lineage",
    "MAPElites", "QDArchive", "NoveltySearch",
    "SurpriseDetector", "AnomalyRecord",
    "ReplicationGate", "ReplicationResult",
]

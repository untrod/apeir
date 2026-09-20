# -*- coding: utf-8 -*-
"""Quality-Diversity optimization — MAP-Elites, novelty search, QD archive.

Goal: NOT a single best genome, but a diverse archive of high-quality
genomes across different behavior regions.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from .genome import CandidateGenome


@dataclass
class QDArchive:
    """Archive of elite genomes organized by behavior descriptors."""
    bins: dict[tuple, CandidateGenome] = field(default_factory=dict)  # behavior_bin → best genome
    behavior_bounds: list[tuple[float, float]] = field(default_factory=list)  # per-dimension (min, max)
    bins_per_dimension: int = 10

    def add(self, genome: CandidateGenome) -> bool:
        """Add genome to archive. Returns True if it became elite in its bin."""
        if not genome.behavior_descriptor or len(genome.behavior_descriptor) != 6:
            return False

        bin_key = self._bin_key(genome.behavior_descriptor)
        existing = self.bins.get(bin_key)

        if existing is None or genome.fitness > existing.fitness:
            self.bins[bin_key] = genome
            return True
        return False

    def _bin_key(self, descriptor: list[float]) -> tuple:
        """Map continuous descriptor to discrete bin."""
        if not self.behavior_bounds:
            return tuple(0 for _ in descriptor)
        return tuple(
            min(self.bins_per_dimension - 1,
                int((d - lo) / max(hi - lo, 0.001) * self.bins_per_dimension))
            for d, (lo, hi) in zip(descriptor, self.behavior_bounds)
        )

    def coverage(self) -> float:
        """Fraction of bins that are filled."""
        max_bins = self.bins_per_dimension ** 6
        return len(self.bins) / max_bins if max_bins > 0 else 0

    def best(self) -> CandidateGenome | None:
        return max(self.bins.values(), key=lambda g: g.fitness) if self.bins else None

    def diversity_score(self) -> float:
        """Mean pairwise distance between archived genomes."""
        genomes = list(self.bins.values())
        if len(genomes) < 2:
            return 0.0
        distances = []
        for i in range(min(len(genomes), 50)):
            for j in range(i + 1, min(len(genomes), 50)):
                d = math.sqrt(sum(
                    (a - b) ** 2 for a, b in zip(genomes[i].behavior_descriptor, genomes[j].behavior_descriptor)
                ))
                distances.append(d)
        return sum(distances) / len(distances) if distances else 0.0


class MAPElites:
    """MAP-Elites quality-diversity algorithm.

    Maintains an archive of elite genomes across a 6-dimensional behavior space.
    Each iteration: select parent, mutate, evaluate, try to add to archive.
    """

    def __init__(self, bins_per_dimension: int = 10, population_size: int = 100) -> None:
        self.archive = QDArchive(bins_per_dimension=bins_per_dimension)
        self.population_size = population_size
        self.generation = 0

    def initialize(self, initial_population: list[CandidateGenome]) -> None:
        """Initialize the archive with a seed population."""
        for genome in initial_population:
            self.archive.add(genome)

    def step(self, evaluate_fn: Callable[[CandidateGenome], CandidateGenome]) -> int:
        """One iteration: select, mutate, evaluate, add. Returns additions count."""
        self.generation += 1
        additions = 0

        for _ in range(self.population_size):
            # Select random parent from archive
            elites = list(self.archive.bins.values())
            if not elites:
                continue
            parent = random.choice(elites)

            # Mutate
            child = parent.__class__.mutate(parent) if hasattr(parent.__class__, 'mutate') else None
            if child is None:
                from .genome import GenomeEncoder
                child = GenomeEncoder.mutate(parent)

            # Evaluate
            child = evaluate_fn(child)

            # Try to add
            if self.archive.add(child):
                additions += 1

        return additions

    def run(self, generations: int, evaluate_fn: Callable) -> QDArchive:
        """Run MAP-Elites for N generations."""
        for _ in range(generations):
            self.step(evaluate_fn)
        return self.archive


class NoveltySearch:
    """Novelty search — optimize for behavioral novelty, not fitness."""

    def __init__(self, archive_size: int = 100, k_nearest: int = 15) -> None:
        self.archive: list[CandidateGenome] = []
        self.archive_size = archive_size
        self.k = k_nearest

    def novelty_score(self, genome: CandidateGenome) -> float:
        """Compute novelty as mean distance to k-nearest neighbors."""
        if not self.archive:
            return 1.0
        distances = []
        for other in self.archive:
            if genome.behavior_descriptor and other.behavior_descriptor:
                d = math.sqrt(sum(
                    (a - b) ** 2 for a, b in zip(genome.behavior_descriptor, other.behavior_descriptor)
                ))
                distances.append(d)
        distances.sort()
        k = min(self.k, len(distances))
        return sum(distances[:k]) / k if k > 0 else 1.0

    def add(self, genome: CandidateGenome) -> None:
        self.archive.append(genome)
        if len(self.archive) > self.archive_size:
            # Remove least novel
            least = min(self.archive, key=lambda g: self.novelty_score(g))
            self.archive.remove(least)

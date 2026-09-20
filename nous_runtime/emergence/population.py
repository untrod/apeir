# -*- coding: utf-8 -*-
"""Population & Lineage management for emergence optimization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .genome import CandidateGenome


@dataclass
class Lineage:
    """Tracks the evolutionary lineage of a genome."""
    lineage_id: str = ""
    root_genome_id: str = ""
    generations: list[dict] = field(default_factory=list)  # [{generation, genome_id, mutation, fitness}]
    total_mutations: int = 0
    total_crossovers: int = 0
    best_fitness: float = 0.0
    best_genome_id: str = ""
    status: str = "active"  # active, extinct, merged


class Population:
    """Manages a population of genomes across generations."""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._genomes: dict[str, CandidateGenome] = {}
        self._lineages: dict[str, Lineage] = {}
        self._generation: int = 0
        self._by_generation: dict[int, list[str]] = {}

    def add(self, genome: CandidateGenome) -> str:
        """Add a genome to the population."""
        if len(self._genomes) >= self.max_size:
            self._prune_weakest()
        gid = genome.genome_id or f"genome_{uuid.uuid4().hex[:12]}"
        genome.genome_id = gid
        self._genomes[gid] = genome

        # Track by generation
        gen = genome.generation
        if gen not in self._by_generation:
            self._by_generation[gen] = []
        self._by_generation[gen].append(gid)

        # Create/update lineage
        if genome.parent_ids:
            parent_lineage = None
            for pid in genome.parent_ids:
                for lid, lin in self._lineages.items():
                    if lin.root_genome_id == pid or pid in [g["genome_id"] for g in lin.generations]:
                        parent_lineage = lin
                        break
            if parent_lineage:
                parent_lineage.generations.append({
                    "generation": genome.generation, "genome_id": gid,
                    "mutation": genome.mutation_type, "fitness": genome.fitness,
                })
                if genome.mutation_type == "mutation":
                    parent_lineage.total_mutations += 1
                elif genome.mutation_type == "crossover":
                    parent_lineage.total_crossovers += 1
                if genome.fitness > parent_lineage.best_fitness:
                    parent_lineage.best_fitness = genome.fitness
                    parent_lineage.best_genome_id = gid
            else:
                lin = Lineage(lineage_id=f"lin_{uuid.uuid4().hex[:8]}", root_genome_id=gid)
                lin.generations.append({"generation": genome.generation, "genome_id": gid, "mutation": genome.mutation_type, "fitness": genome.fitness})
                lin.best_fitness = genome.fitness
                lin.best_genome_id = gid
                self._lineages[lin.lineage_id] = lin
        else:
            lin = Lineage(lineage_id=f"lin_{uuid.uuid4().hex[:8]}", root_genome_id=gid)
            self._lineages[lin.lineage_id] = lin

        return gid

    def get(self, genome_id: str) -> CandidateGenome | None:
        return self._genomes.get(genome_id)

    def best(self) -> CandidateGenome | None:
        if not self._genomes:
            return None
        return max(self._genomes.values(), key=lambda g: g.fitness)

    def generation_size(self, gen: int) -> int:
        return len(self._by_generation.get(gen, []))

    def diversity(self) -> float:
        """Mean pairwise distance in behavior space."""
        genomes = list(self._genomes.values())[:100]
        if len(genomes) < 2:
            return 0.0
        import math
        dists = []
        for i in range(len(genomes)):
            for j in range(i + 1, len(genomes)):
                if genomes[i].behavior_descriptor and genomes[j].behavior_descriptor:
                    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(genomes[i].behavior_descriptor, genomes[j].behavior_descriptor)))
                    dists.append(d)
        return sum(dists) / len(dists) if dists else 0.0

    def _prune_weakest(self) -> None:
        """Remove the weakest genome."""
        if not self._genomes:
            return
        weakest = min(self._genomes.values(), key=lambda g: g.fitness)
        del self._genomes[weakest.genome_id]

    @property
    def size(self) -> int:
        return len(self._genomes)

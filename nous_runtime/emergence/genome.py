# -*- coding: utf-8 -*-
"""Candidate Genome — encoding of a complete strategy for QD optimization.

A genome encodes: model combination, agent topology, task decomposition,
prompts, context policy, tool sequence, retrieval/verification/recovery
policies, and hyperparameters.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass, field


@dataclass
class CandidateGenome:
    """Complete strategy encoding for emergence optimization."""
    genome_id: str = ""
    generation: int = 0

    # Strategy parameters
    model_combination: list[str] = field(default_factory=list)  # ordered model IDs
    agent_topology: list[str] = field(default_factory=list)     # role names
    task_decomposition: str = "sequential"  # sequential, parallel, hierarchical
    prompt_template_id: str = ""
    context_policy: str = "standard"        # standard, expanded, minimal
    tool_sequence: list[str] = field(default_factory=list)
    retrieval_policy: str = "standard"
    verification_policy: str = "standard"
    recovery_policy: str = "retry"

    # Hyperparameters
    temperature: float = 0.5
    max_tokens: int = 4096
    top_p: float = 0.9
    beam_width: int = 1

    # Performance
    fitness: float = 0.0
    behavior_descriptor: list[float] = field(default_factory=list)  # 6-dim: [quality, cost, latency, risk, novelty, reproducibility]
    novelty_score: float = 0.0
    reproducibility_score: float = 0.0

    # Lineage
    parent_ids: list[str] = field(default_factory=list)
    mutation_type: str = ""             # random_init, crossover, mutation, perturbation
    creation_reason: str = "random_init"

    def hash_short(self) -> str:
        d = {k: v for k, v in self.__dict__.items() if k not in ("genome_id", "fitness")}
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


class GenomeEncoder:
    """Encodes and decodes genomes for QD optimization."""

    BEHAVIOR_DIMENSIONS = ["quality", "cost", "latency", "risk", "novelty", "reproducibility"]

    @staticmethod
    def mutate(genome: CandidateGenome, mutation_rate: float = 0.1) -> CandidateGenome:
        """Create a mutated copy of a genome."""
        child = CandidateGenome(
            genome_id=f"genome_{uuid.uuid4().hex[:12]}",
            generation=genome.generation + 1,
            parent_ids=[genome.genome_id],
            mutation_type="mutation",
        )
        # Copy all fields
        for field_name in genome.__dataclass_fields__:
            if field_name not in ("genome_id", "generation", "parent_ids", "mutation_type", "fitness", "behavior_descriptor", "novelty_score"):
                setattr(child, field_name, getattr(genome, field_name))

        # Mutate with probability
        if random.random() < mutation_rate:
            child.temperature = max(0.0, min(1.0, genome.temperature + random.uniform(-0.2, 0.2)))
        if random.random() < mutation_rate:
            child.max_tokens = max(256, genome.max_tokens + random.choice([-512, 512, 1024]))
        if random.random() < mutation_rate and genome.tool_sequence:
            i = random.randint(0, len(genome.tool_sequence) - 1)
            new_tools = list(genome.tool_sequence)
            new_tools[i] = new_tools[i] + "_v2" if random.random() < 0.5 else new_tools[i]
            child.tool_sequence = new_tools

        return child

    @staticmethod
    def crossover(parent_a: CandidateGenome, parent_b: CandidateGenome) -> CandidateGenome:
        """Create a child via uniform crossover of two parents."""
        child = CandidateGenome(
            genome_id=f"genome_{uuid.uuid4().hex[:12]}",
            generation=max(parent_a.generation, parent_b.generation) + 1,
            parent_ids=[parent_a.genome_id, parent_b.genome_id],
            mutation_type="crossover",
        )
        # Uniform crossover for list fields
        child.model_combination = parent_a.model_combination if random.random() < 0.5 else parent_b.model_combination
        child.agent_topology = parent_a.agent_topology if random.random() < 0.5 else parent_b.agent_topology
        child.tool_sequence = parent_a.tool_sequence if random.random() < 0.5 else parent_b.tool_sequence
        # Interpolation for scalar fields
        child.temperature = (parent_a.temperature + parent_b.temperature) / 2
        child.max_tokens = int((parent_a.max_tokens + parent_b.max_tokens) / 2)
        return child

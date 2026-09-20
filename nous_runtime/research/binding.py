# -*- coding: utf-8 -*-
"""Claim–Code–Experiment Binding — every research claim must bind to code, data, experiment.

When code or data changes: experiment becomes stale, claim becomes stale,
dependent reports become stale. No floating claims.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class ClaimBinding:
    """Binding between a research claim and its supporting artifacts."""
    binding_id: str = ""
    claim_id: str = ""
    code_commit: str = ""          # git commit hash
    dataset_version: str = ""
    model_version: str = ""
    prompt_version: str = ""
    experiment_id: str = ""
    result_artifact_id: str = ""
    statistical_review: str = ""   # "passed", "failed", "pending"
    reviewer_decision: str = ""    # "accepted", "rejected", "revision_needed"
    status: str = "active"         # active, stale, superseded
    created_at: str = ""


class BindingRegistry:
    """Registry of claim-code-experiment bindings."""

    def __init__(self) -> None:
        self._bindings: dict[str, ClaimBinding] = {}

    def bind(self, binding: ClaimBinding) -> str:
        if not binding.binding_id:
            binding.binding_id = f"bind_{uuid.uuid4().hex[:12]}"
        self._bindings[binding.binding_id] = binding
        return binding.binding_id

    def get_by_claim(self, claim_id: str) -> list[ClaimBinding]:
        return [b for b in self._bindings.values() if b.claim_id == claim_id]

    def get_by_experiment(self, experiment_id: str) -> list[ClaimBinding]:
        return [b for b in self._bindings.values() if b.experiment_id == experiment_id]

    def mark_stale(self, code_commit: str) -> list[str]:
        """Mark all bindings with old code commit as stale."""
        stale = []
        for b in self._bindings.values():
            if b.code_commit and b.code_commit != code_commit:
                b.status = "stale"
                stale.append(b.binding_id)
        return stale

    def count(self) -> int:
        return len(self._bindings)

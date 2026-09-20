# -*- coding: utf-8 -*-
"""Hypothesis Graph — tracks research hypotheses, evidence, and experiments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class HypothesisState(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    TESTING = "testing"
    REFUTED = "refuted"
    ACCEPTED = "accepted"
    STALE = "stale"


@dataclass
class Hypothesis:
    """A research hypothesis."""
    hypothesis_id: str = ""
    text: str = ""
    parent_problem: str = ""
    competing_hypotheses: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)  # evidence IDs
    contradicting_evidence: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    required_experiments: list[str] = field(default_factory=list)  # experiment IDs
    confidence: float = 0.5
    state: HypothesisState = HypothesisState.PROPOSED


class HypothesisGraph:
    """Graph of research hypotheses with evidence links."""

    def __init__(self) -> None:
        self._hypotheses: dict[str, Hypothesis] = {}
        self._edges: list[tuple[str, str, str]] = []  # (from, to, relation)

    def propose(self, text: str, parent_problem: str = "") -> Hypothesis:
        h = Hypothesis(
            hypothesis_id=f"hyp_{uuid.uuid4().hex[:12]}",
            text=text,
            parent_problem=parent_problem,
        )
        self._hypotheses[h.hypothesis_id] = h
        return h

    def add_evidence(self, hypothesis_id: str, evidence_id: str, supports: bool = True) -> None:
        h = self._hypotheses.get(hypothesis_id)
        if h is None:
            return
        if supports:
            h.supporting_evidence.append(evidence_id)
        else:
            h.contradicting_evidence.append(evidence_id)
        self._update_state(hypothesis_id)

    def add_competing(self, hypothesis_id: str, competing_id: str) -> None:
        h = self._hypotheses.get(hypothesis_id)
        if h and competing_id not in h.competing_hypotheses:
            h.competing_hypotheses.append(competing_id)
            self._edges.append((hypothesis_id, competing_id, "competes_with"))

    def _update_state(self, hypothesis_id: str) -> None:
        h = self._hypotheses.get(hypothesis_id)
        if h is None:
            return
        if h.contradicting_evidence and not h.supporting_evidence:
            h.state = HypothesisState.REFUTED
        elif h.supporting_evidence and not h.contradicting_evidence:
            h.state = HypothesisState.SUPPORTED
            h.confidence = min(1.0, 0.5 + 0.1 * len(h.supporting_evidence))
        elif h.supporting_evidence and h.contradicting_evidence:
            h.state = HypothesisState.CONTRADICTED
        else:
            h.state = HypothesisState.PROPOSED

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        return self._hypotheses.get(hypothesis_id)

    def count(self) -> int:
        return len(self._hypotheses)

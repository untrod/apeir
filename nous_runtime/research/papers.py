# -*- coding: utf-8 -*-
"""Paper Ingestion — converts academic papers into structured Research Cards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchCard:
    """Structured research card extracted from an academic paper."""
    card_id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    publication: str = ""
    year: int = 0
    research_question: str = ""
    hypothesis: str = ""
    mathematical_formulation: str = ""
    assumptions: list[str] = field(default_factory=list)
    algorithm: str = ""
    dataset: str = ""
    benchmark: str = ""
    baselines: list[str] = field(default_factory=list)
    results: dict[str, float] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    code_availability: str = ""  # url or "unavailable"
    reproducibility_score: float = 0.0
    relation_to_nous: str = ""
    confidence: float = 0.5
    status: str = "ingested"  # ingested, reviewed, integrated, superseded


class PaperIngestion:
    """Ingests papers and creates structured Research Cards.

    In v1, this is semi-automated: structured fields extracted by LLM,
    validated by human reviewer against the paper.
    """

    def ingest(self, paper_data: dict[str, Any]) -> ResearchCard:
        """Create a research card from paper data."""
        card = ResearchCard(
            card_id=f"card_{uuid.uuid4().hex[:12]}",
            title=str(paper_data.get("title", "")),
            authors=paper_data.get("authors", []),
            publication=str(paper_data.get("publication", "")),
            year=int(paper_data.get("year", 0)),
            research_question=str(paper_data.get("research_question", "")),
            hypothesis=str(paper_data.get("hypothesis", "")),
            algorithm=str(paper_data.get("algorithm", "")),
            dataset=str(paper_data.get("dataset", "")),
            benchmark=str(paper_data.get("benchmark", "")),
            baselines=paper_data.get("baselines", []),
            limitations=paper_data.get("limitations", []),
            code_availability=str(paper_data.get("code_url", "")),
        )
        return card

    def validate(self, card: ResearchCard) -> list[str]:
        """Validate a research card for completeness."""
        issues = []
        if not card.title:
            issues.append("Missing title")
        if not card.research_question:
            issues.append("Missing research question")
        if not card.algorithm and not card.hypothesis:
            issues.append("Missing algorithm or hypothesis")
        if not card.authors:
            issues.append("Missing authors")
        return issues

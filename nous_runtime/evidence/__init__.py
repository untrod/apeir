# -*- coding: utf-8 -*-
"""Evidence Fabric — research planning, source registry, claim-evidence graph,
conflict detection, freshness tracking, prompt injection guard.

All web content is UNTRUSTED by default. Claims must be backed by evidence.
Conflicts must not silently disappear.
"""

from .claims import ClaimEvidenceGraph, Claim, Evidence, Relation, VerificationState
from .freshness import FreshnessTracker, FreshnessPolicy
from .injection_guard import InjectionGuard, InjectionCheckResult
from .source_registry import SourceRegistry, SourceRecord, SourceType, TrustTier
from .snapshots import SnapshotStore, ContentSnapshot
from .web_gateway import WebGateway, WebGatewayError, WebRequest, WebResponse
from .provenance import ProvenanceTracker, ProvenanceRecord
from .research_planner import ResearchPlanner, ResearchPlan
from .service import ResearchEvidenceService, ResearchServiceError

__all__ = [
    "ClaimEvidenceGraph", "Claim", "Evidence", "Relation", "VerificationState",
    "FreshnessTracker", "FreshnessPolicy",
    "InjectionGuard", "InjectionCheckResult",
    "SourceRegistry", "SourceRecord", "SourceType", "TrustTier",
    "SnapshotStore", "ContentSnapshot",
    "WebGateway", "WebGatewayError", "WebRequest", "WebResponse",
    "ProvenanceTracker", "ProvenanceRecord",
    "ResearchPlanner", "ResearchPlan",
    "ResearchEvidenceService", "ResearchServiceError",
]

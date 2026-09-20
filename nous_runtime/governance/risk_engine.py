# -*- coding: utf-8 -*-
"""Multi-dimensional risk assessment engine."""

from __future__ import annotations

from typing import Any

from nous_runtime.governance.contracts import (
    ActionProposal,
    AuthorizationContext,
    RiskEnvelope,
    _new_id,
    _utc_now,
)


def assess_risk(
    proposal: ActionProposal,
    context: AuthorizationContext,
    capability_manifest: dict[str, Any] | None = None,
) -> RiskEnvelope:
    """Compute a multi-dimensional RiskEnvelope for a proposal."""

    dims: dict[str, float | None] = {}

    # D1: Data sensitivity
    dims["data_sensitivity"] = _data_sensitivity(proposal.data_classification)

    # D2: Execution risk
    dims["execution_risk"] = _execution_risk(proposal, capability_manifest)

    # D3: External side-effect risk
    dims["external_side_effect_risk"] = _side_effect_risk(proposal)

    # D4: Financial risk
    dims["financial_risk"] = _financial_risk(proposal)

    # D5: Privilege risk
    dims["privilege_risk"] = _privilege_risk(proposal, capability_manifest)

    # D6: Availability risk
    dims["availability_risk"] = _availability_risk(proposal)

    # D7: Irreversibility
    dims["irreversibility"] = _irreversibility(proposal)

    # D8: Scope breadth
    dims["scope_breadth"] = _scope_breadth(proposal)

    # D9: Model uncertainty
    dims["model_uncertainty"] = _model_uncertainty(proposal)

    # D10: Provider uncertainty
    dims["provider_uncertainty"] = _provider_uncertainty(context)

    # D11: Recovery difficulty
    dims["recovery_difficulty"] = _recovery_difficulty(proposal)

    # D12: Privacy exposure
    dims["privacy_exposure"] = _privacy_exposure(proposal)

    # D13: Locality change
    dims["locality_change"] = _locality_change(proposal, context)

    # D14: Credential impact
    dims["credential_impact"] = _credential_impact(proposal)

    # D15: Deployment impact
    dims["deployment_impact"] = _deployment_impact(proposal)

    # Collect results
    sources = _build_sources(proposal, capability_manifest)
    unknown = tuple(name for name, val in dims.items() if val is None)
    known = [(name, val) for name, val in dims.items() if val is not None]

    if known:
        max_dim, max_val = max(known, key=lambda x: x[1])
    else:
        max_dim, max_val = "unknown", 1.0

    aggregate = _aggregate(dims, unknown)

    return RiskEnvelope(
        envelope_id=_new_id("re"),
        proposal_hash=proposal.proposal_hash,
        **dims,
        evidence_sources=tuple(sources),
        unknown_dimensions=unknown,
        assessed_at=_utc_now(),
        assessed_by="risk_engine",
        aggregate_risk_class=aggregate,
        max_dimension=max_dim,
        max_dimension_value=max_val,
    )


def _data_sensitivity(classification: str) -> float | None:
    mapping = {"public": 0.0, "internal": 0.3, "confidential": 0.6, "restricted": 0.9}
    return mapping.get(classification.lower(), None)


def _execution_risk(proposal: ActionProposal, manifest: dict | None) -> float | None:
    if manifest and manifest.get("risk_level"):
        mapping = {"low": 0.1, "medium": 0.4, "high": 0.7, "critical": 0.95}
        return mapping.get(str(manifest["risk_level"]).lower(), None)
    side_map = {"none": 0.0, "read_only": 0.1, "local_write": 0.4, "external_write": 0.7, "destructive": 0.95}
    if proposal.side_effect_class:
        return side_map.get(proposal.side_effect_class, None)
    if "shell" in proposal.capability_id or "exec" in proposal.capability_id:
        return 0.85
    if "file_write" in proposal.capability_id:
        return 0.5
    if "file_read" in proposal.capability_id or "echo" in proposal.capability_id:
        return 0.1
    return None


def _side_effect_risk(proposal: ActionProposal) -> float | None:
    mapping = {"none": 0.0, "read_only": 0.1, "local_write": 0.4, "external_write": 0.7, "destructive": 0.95}
    return mapping.get(proposal.side_effect_class, None)


def _financial_risk(proposal: ActionProposal) -> float | None:
    c = proposal.estimated_cost_usd
    if c <= 0:
        return 0.0
    if c < 0.01:
        return 0.1
    if c < 1.0:
        return 0.3
    if c < 100.0:
        return 0.6
    return 0.9


def _privilege_risk(proposal: ActionProposal, manifest: dict | None) -> float | None:
    if "sudo" in proposal.required_permissions or "admin" in proposal.required_permissions:
        return 0.9
    if "root" in proposal.required_permissions:
        return 1.0
    # v0.2.0: declared privileged flag forces approval-level risk
    if manifest and _manifest_privileged(manifest):
        return 0.7
    if manifest and manifest.get("required_privilege"):
        return {"user": 0.1, "elevated": 0.5, "admin": 0.9}.get(
            str(manifest["required_privilege"]).lower(), None
        )
    return 0.1  # Default: user-level


def _manifest_privileged(manifest: dict) -> bool:
    """Return True when the capability manifest declares privileged=True.

    Checks the top-level key first, then the metadata blob (which may be
    a dict or a JSON string depending on the registry layer).
    """
    if manifest.get("privileged"):
        return True
    meta = manifest.get("metadata")
    if isinstance(meta, str) and meta.strip():
        try:
            import json
            meta = json.loads(meta)
        except Exception:
            return False
    if isinstance(meta, dict):
        return bool(meta.get("privileged"))
    return False


def _availability_risk(proposal: ActionProposal) -> float | None:
    if proposal.capability_id in ("system.shutdown", "system.restart", "service.stop"):
        return 0.9
    if proposal.side_effect_class == "destructive":
        return 0.5
    return 0.0


def _irreversibility(proposal: ActionProposal) -> float | None:
    mapping = {"reversible": 0.0, "partially_reversible": 0.5, "irreversible": 0.95}
    return mapping.get(proposal.reversibility, None)


def _scope_breadth(proposal: ActionProposal) -> float | None:
    n = len(proposal.affected_resources)
    if n == 0:
        return 0.0
    if n == 1:
        return 0.1
    if n <= 5:
        return 0.3
    if n <= 50:
        return 0.6
    return 0.9


def _model_uncertainty(proposal: ActionProposal) -> float | None:
    """Return the declared model_uncertainty for this capability.

    v0.2.0: Reads from capability metadata first (declared value).
    Falls back to category-based defaults, then legacy prefix check.
    """
    # 1. Check capability's declared metadata (v0.2.0)
    declared = _get_capability_uncertainty(proposal.capability_id)
    if declared is not None:
        return declared

    # 2. Category-based defaults (v0.2.0)
    category_defaults = {
        "model": 0.5,
        "rag": 0.3,
        "agent": 0.6,
        "device": 0.0,
        "software": 0.0,
        "tool": 0.1,
        "notification": 0.0,
        "automation": 0.0,
        "connector": 0.3,
    }
    category = _get_capability_category(proposal.capability_id)
    if category in category_defaults:
        return category_defaults[category]

    # 3. v0.2.0: no prefix fallback.  Registered-but-uncategorized
    #    capabilities default to deterministic (0.0).  Unregistered
    #    capabilities are an unknown dimension (fail-safe: the gate
    #    already treats unregistered capabilities as high risk).
    if _capability_registered(proposal.capability_id):
        return 0.0
    return None


def _capability_registered(capability_id: str) -> bool:
    """Return True when the capability exists in the registry."""
    try:
        from nous_runtime.compat.capability import get_capability
        return bool(get_capability(capability_id))
    except Exception:
        return False


def _get_capability_uncertainty(capability_id: str) -> float | None:
    """Return declared model_uncertainty from capability metadata, or None."""
    try:
        from nous_runtime.compat.capability import get_capability
        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            meta = cap.get("metadata", {})
            if isinstance(meta, dict) and "model_uncertainty" in meta:
                return float(meta["model_uncertainty"])
    except Exception:
        pass
    return None


def _get_capability_category(capability_id: str) -> str:
    """Return the category of a registered capability."""
    try:
        from nous_runtime.compat.capability import get_capability
        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            return str(cap.get("category", ""))
    except Exception:
        pass
    return ""


def _provider_uncertainty(context: AuthorizationContext) -> float | None:
    if context.session_locality == "local":
        return 0.1
    if context.session_locality == "remote":
        return 0.5
    return None  # Unknown


def _recovery_difficulty(proposal: ActionProposal) -> float | None:
    if proposal.reversibility == "reversible":
        return 0.0
    if proposal.reversibility == "partially_reversible":
        return 0.5
    if proposal.reversibility == "irreversible":
        return 0.95
    return None


def _privacy_exposure(proposal: ActionProposal) -> float | None:
    mapping = {"public": 0.0, "internal": 0.2, "confidential": 0.6, "restricted": 0.95}
    return mapping.get(proposal.data_classification, None)


def _locality_change(proposal: ActionProposal, context: AuthorizationContext) -> float | None:
    if not proposal.target_node:
        return 0.0  # Local
    if context.session_locality == "local":
        return 0.3  # Local to local node
    return 0.7  # Remote


def _credential_impact(proposal: ActionProposal) -> float | None:
    if "credential" in proposal.required_permissions or "secret" in proposal.required_permissions:
        return 0.8
    if proposal.capability_id.startswith("credential."):
        return 0.9
    return 0.0


def _deployment_impact(proposal: ActionProposal) -> float | None:
    channel = getattr(proposal, "deployment_channel", "")
    if channel == "production":
        return 0.95
    if channel == "staging":
        return 0.5
    if channel == "test":
        return 0.1
    return 0.0


def _build_sources(proposal: ActionProposal, manifest: dict | None) -> list[str]:
    sources = ["action_proposal"]
    if manifest:
        sources.append("capability_manifest")
    return sources


def _aggregate(dims: dict[str, float | None], unknown: tuple[str, ...]) -> str:
    """Determine aggregate risk class. Uses ceiling, not average."""
    values = [v for v in dims.values() if v is not None]
    unknown_count = len(unknown)

    if not values:
        return "critical"  # All unknown

    max_val = max(values)

    # Critical: any dimension >= 0.9 OR >= 3 unknown
    if max_val >= 0.9 or unknown_count >= 3:
        return "critical"

    # High: any dimension >= 0.7 OR >= 2 unknown
    if max_val >= 0.7 or unknown_count >= 2:
        return "high"

    # Medium: any dimension >= 0.4 OR >= 1 unknown
    if max_val >= 0.4 or unknown_count >= 1:
        return "medium"

    return "low"

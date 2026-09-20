"""Research and governed network API adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response


def _workspace() -> Path:
    return Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()


def _service():
    from nous_runtime.evidence.service import ResearchEvidenceService
    return ResearchEvidenceService(_workspace())


def handle_research_network_status() -> dict[str, Any]:
    return ok_response(_service().status())


def handle_research_sources(params: dict[str, Any] | None = None) -> dict[str, Any]:
    values = params or {}
    try:
        return ok_response(_service().list_sources(limit=int(values.get("limit") or 100)))
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_source(source_id: str) -> dict[str, Any]:
    try:
        return ok_response(_service().get_source(source_id))
    except KeyError:
        return err_response("NOUS_NOT_FOUND", f"Research source not found: {source_id}")
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_search(body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        response = execute_runtime_capability("network.fetch", body, workspace_root=_workspace())
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))
    if not response.get("ok"):
        evidence = response.get("search_evidence") or {}
        return err_response(
            str(response.get("error_code") or "NOUS_NETWORK_FAILED"),
            str(response.get("error_message") or "The governed search failed."),
            {
                "request_id": response.get("request_id", ""),
                "run_id": response.get("run_id", ""),
                "source_id": evidence.get("source_id", ""),
            },
        )
    return ok_response(response)
def handle_research_fetch(body: dict[str, Any]) -> dict[str, Any]:
    try:
        from nous_runtime.capability.runtime_executor import execute_runtime_capability
        response = execute_runtime_capability("network.fetch", body, workspace_root=_workspace())
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))
    if not response.get("ok"):
        return err_response(
            str(response.get("error_code") or "NOUS_NETWORK_FAILED"),
            str(response.get("error_message") or "The network request failed."),
            {
                "request_id": response.get("request_id", ""),
                "run_id": response.get("run_id", ""),
            },
        )
    return ok_response(response)


def handle_research_claims(params: dict[str, Any] | None = None) -> dict[str, Any]:
    values = params or {}
    try:
        return ok_response(_service().list_claims(
            limit=int(values.get("limit") or 100),
            verification_state=str(values.get("verification_state") or ""),
        ))
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_claim_create(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return ok_response(_service().create_claim(body))
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_claim(claim_id: str) -> dict[str, Any]:
    try:
        return ok_response(_service().get_claim(claim_id))
    except KeyError:
        return err_response("NOUS_NOT_FOUND", f"Research claim not found: {claim_id}")
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_source_claims(source_id: str) -> dict[str, Any]:
    try:
        return ok_response(_service().claims_for_source(source_id))
    except KeyError:
        return err_response("NOUS_NOT_FOUND", f"Research source not found: {source_id}")
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_claim_evidence(
    claim_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    try:
        return ok_response(_service().attach_claim_evidence(claim_id, body))
    except KeyError:
        return err_response("NOUS_NOT_FOUND", f"Research claim not found: {claim_id}")
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_research_claim_verify(
    claim_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    try:
        return ok_response(_service().verify_claim(claim_id, body))
    except KeyError:
        return err_response("NOUS_NOT_FOUND", f"Research claim not found: {claim_id}")
    except (OSError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def ensure_network_capability() -> str:
    """Migrate the built-in network.fetch declaration into existing registries."""
    from nous_runtime.capability import register_capability

    return register_capability(
        "network.fetch",
        category="tool",
        provider="nous",
        description="Fetch a public HTTP resource through the governed Network Gateway",
        risk="high",
        timeout_ms=120000,
        max_retries=0,
        requires_auth=True,
        requires_device=False,
        executor_type="runtime",
        side_effect_class="external_write",
        reversibility="irreversible",
        model_uncertainty=0.0,
        idempotent=True,
        privileged=True,
        locality="remote",
        connection_type="ip",
        metadata={
            "service": "nous_runtime.evidence.web_gateway:WebGateway",
            "network_scope": "public_internet",
            "methods": ["GET", "HEAD", "POST"],
        },
    )


def ensure_claim_capability() -> str:
    """Register the governed local mutation capability for Claim state."""
    from nous_runtime.capability import register_capability

    return register_capability(
        "research.claim.manage",
        category="knowledge",
        provider="nous",
        description="Create and verify traceable claims over existing research evidence",
        risk="medium",
        timeout_ms=30000,
        max_retries=0,
        requires_auth=True,
        requires_device=False,
        executor_type="runtime",
        side_effect_class="local_write",
        reversibility="reversible",
        model_uncertainty=0.0,
        idempotent=False,
        privileged=True,
        locality="local",
        connection_type="none",
        metadata={
            "service": "nous_runtime.evidence.claims:ClaimEvidenceGraph",
            "event_authority": "EventStream",
            "contract_version": "1.0",
        },
    )


RESEARCH_ROUTES = {
    ("GET", "/api/v1/research/network/status"): handle_research_network_status,
    ("GET", "/api/v1/research/sources"): handle_research_sources,
    ("GET", "/api/v1/research/sources/{source_id}"): handle_research_source,
    ("GET", "/api/v1/research/sources/{source_id}/claims"): handle_research_source_claims,
    ("GET", "/api/v1/research/claims"): handle_research_claims,
    ("GET", "/api/v1/research/claims/{claim_id}"): handle_research_claim,
    ("POST", "/api/v1/research/claims"): handle_research_claim_create,
    ("POST", "/api/v1/research/claims/{claim_id}/evidence"): handle_research_claim_evidence,
    ("POST", "/api/v1/research/claims/{claim_id}/verify"): handle_research_claim_verify,
    ("POST", "/api/v1/research/search"): handle_research_search,
    ("POST", "/api/v1/research/fetch"): handle_research_fetch,
}

RESEARCH_GOVERNANCE = {
    ("POST", "/api/v1/research/search"): ("network.fetch", "external_write", "irreversible"),
    ("POST", "/api/v1/research/fetch"): ("network.fetch", "external_write", "irreversible"),
    ("POST", "/api/v1/research/claims"): ("research.claim.manage", "local_write", "reversible"),
    ("POST", "/api/v1/research/claims/{claim_id}/evidence"): ("research.claim.manage", "local_write", "reversible"),
    ("POST", "/api/v1/research/claims/{claim_id}/verify"): ("research.claim.manage", "local_write", "reversible"),
}

ensure_network_capability()

__all__ = ["RESEARCH_GOVERNANCE", "RESEARCH_ROUTES"]

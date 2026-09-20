"""Workspace-scoped research service over the governed WebGateway."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit


from nous_runtime.artifact import ArtifactManager, ArtifactRegistry
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.evidence.claims import ClaimEvidenceGraph, Relation, VerificationState
from nous_runtime.evidence.injection_guard import InjectionGuard
from nous_runtime.evidence.snapshots import SnapshotStore
from nous_runtime.evidence.source_registry import SourceRegistry
from nous_runtime.evidence.web_gateway import WebGateway, WebRequest, _body_hash, _safe_url
from nous_runtime.workspace.isolation import normalize_workspace_path

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_MAX_HEADER_REF = 64 * 1024
_MAX_BODY_REF = 1024 * 1024
_SEARCH_URL = "https://www.bing.com/search"
_MAX_SEARCH_RESULTS = 20


class ResearchServiceError(ValueError):
    """A bounded, user-actionable research request error."""


class ResearchEvidenceService:
    """Real web fetch, snapshot, source, and artifact closure."""

    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise ResearchServiceError("The active workspace does not exist.")
        evidence_root = self.root / ".nous" / "evidence"
        evidence_root.mkdir(parents=True, exist_ok=True)
        self.sources = SourceRegistry(evidence_root / "sources.json")
        self.snapshots = SnapshotStore(evidence_root / "snapshots")
        self.artifacts = ArtifactRegistry(self.root / ".nous" / "artifacts.jsonl")
        self.events = EventStream(str(self.root))
        self.claims = ClaimEvidenceGraph(
            evidence_root / 'claims.json', event_stream=self.events
        )
        self.gateway = WebGateway(
            InjectionGuard(),
            self.snapshots,
            self.sources,
            artifact_manager=ArtifactManager(self.artifacts),
            event_stream=self.events,
        )

    def fetch(self, values: dict[str, Any]) -> dict[str, Any]:
        request = self._request(values)
        response = self.gateway.fetch(request)
        result = response.to_dict()
        if response.ok and response.source_id:
            result["citation"] = self.citation_for_source(response.source_id)
        return result

    def search(self, values: dict[str, Any]) -> dict[str, Any]:
        query = str(values.get("query") or "").strip()
        if not query:
            raise ResearchServiceError("query is required.")
        if len(query) > 1000:
            raise ResearchServiceError("query exceeds 1000 characters.")
        max_results = max(1, min(int(values.get("max_results") or 10), _MAX_SEARCH_RESULTS))
        response = self.gateway.fetch(self._request(search_network_values(values)))
        evidence = response.to_dict()
        if not response.ok:
            return {
                "ok": False,
                "query": query,
                "results": [],
                "search_evidence": evidence,
                "error_code": response.error_code,
                "error_message": response.error_message,
                "request_id": response.request_id,
                "run_id": response.run_id,
            }
        if response.source_id:
            evidence["citation"] = self.citation_for_source(response.source_id)
        return {
            "ok": True,
            "query": query,
            "results": parse_search_results(response.content, limit=max_results),
            "search_evidence": evidence,
            "request_id": response.request_id,
            "run_id": response.run_id,
        }

    def citation_for_source(self, source_id: str) -> dict[str, Any]:
        source = self.sources.get(source_id)
        if source is None:
            raise KeyError(source_id)
        label = source.title or source.publisher or source.url
        retrieved = source.retrieved_at or source.retrieval_time
        return {
            "source_id": source.source_id,
            "title": source.title,
            "url": source.url,
            "publisher": source.publisher,
            "author": source.author,
            "publication_time": source.publication_time,
            "retrieved_at": retrieved,
            "content_hash": source.content_hash,
            "snapshot_artifact_id": source.snapshot_artifact_id,
            "formatted": f"{label}. {source.url} (retrieved {retrieved})",
        }


    def create_claim(self, values: dict[str, Any]) -> dict[str, Any]:
        """Create a Claim and deterministically associate existing evidence."""
        statement = str(values.get("statement") or values.get("text") or "").strip()
        if not statement:
            raise ResearchServiceError("statement is required.")
        if len(statement) > 20_000:
            raise ResearchServiceError("statement exceeds 20000 characters.")
        source_refs = _string_list(values.get("source_refs") or values.get("source_ids") or [])
        evidence_values = values.get("evidence") or []
        if not isinstance(evidence_values, list):
            raise ResearchServiceError("evidence must be an array.")
        plans = [
            self._validate_evidence_association(item)
            for item in evidence_values
        ]
        planned_sources = {item["source_id"] for item in plans if item["source_id"]}
        for source_id in source_refs:
            if self.sources.get(source_id) is None:
                raise ResearchServiceError(f"source not found: {source_id}")
            if source_id in planned_sources:
                continue
            snapshots = self.snapshots.list(source_id=source_id, limit=1)
            snapshot = snapshots[0] if snapshots else None
            source = self.sources.get(source_id)
            plans.append({
                "source_id": source_id,
                "snapshot_ref": snapshot.snapshot_id if snapshot else "",
                "artifact_ref": (
                    snapshot.artifact_id if snapshot and snapshot.artifact_id
                    else source.snapshot_artifact_id if source else ""
                ),
                "relation": Relation.SUPPORTS,
                "strength": float(values.get("association_strength") or 0.5),
                "description": "Deterministic association from source_refs.",
                "provenance": {"matcher": "source_ref_latest_snapshot_v1"},
            })
        claim = self.claims.add_claim(
            statement=statement,
            task_id=str(values.get("task_id") or ""),
            run_id=str(values.get("run_id") or ""),
            trace_id=str(values.get("trace_id") or ""),
            source_refs=source_refs,
            confidence=float(values.get("confidence") if values.get("confidence") is not None else 0.5),
            created_by=str(values.get("created_by") or "research.claim.service"),
            provenance={
                "association_method": "deterministic_reference_matcher_v1",
                **dict(values.get("provenance") or {}),
            },
        )
        for item in plans:
            self.claims.add_evidence(claim.claim_id, **item)
        return self.get_claim(claim.claim_id)

    def list_claims(
        self,
        *,
        limit: int = 100,
        verification_state: str = "",
    ) -> dict[str, Any]:
        claims = self.claims.list_claims(
            verification_state=verification_state or None,
            limit=limit,
        )
        return {
            "claims": [claim.to_dict() for claim in claims],
            "total": len(claims),
            "summary": self.claims.summary(),
        }

    def get_claim(self, claim_id: str) -> dict[str, Any]:
        trace = self.claims.trace_claim(claim_id)
        sources: list[dict[str, Any]] = []
        for source_id in trace["source_refs"]:
            source = self.sources.get(source_id)
            if source is not None:
                sources.append({
                    **source.to_dict(),
                    "citation": self.citation_for_source(source_id),
                })
        snapshots = [
            snapshot.to_dict()
            for snapshot_id in trace["snapshot_refs"]
            if (snapshot := self.snapshots.get(snapshot_id)) is not None
        ]
        artifacts = [
            artifact.to_dict()
            for artifact_id in trace["artifact_refs"]
            if (artifact := self.artifacts.get(artifact_id)) is not None
        ]
        return {
            **trace,
            "sources": sources,
            "snapshots": snapshots,
            "artifacts": artifacts,
            "trace_complete": all(
                (
                    bool(evidence.get("source_id"))
                    and (
                        not evidence.get("snapshot_ref")
                        or any(
                            item["snapshot_id"] == evidence["snapshot_ref"]
                            for item in snapshots
                        )
                    )
                )
                or (
                    bool(evidence.get("artifact_ref"))
                    and any(
                        item["id"] == evidence["artifact_ref"]
                        for item in artifacts
                    )
                )
                for evidence in trace["evidence"]
            ),
        }

    def claims_for_source(self, source_id: str) -> dict[str, Any]:
        if self.sources.get(source_id) is None:
            raise KeyError(source_id)
        return self.claims.trace_source(source_id)

    def attach_claim_evidence(
        self,
        claim_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        association = self._validate_evidence_association(values)
        self.claims.add_evidence(claim_id, **association)
        return self.get_claim(claim_id)

    def verify_claim(
        self,
        claim_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        requested = str(values.get("verification_state") or "").strip()
        if requested:
            try:
                state = VerificationState(requested)
            except ValueError as exc:
                raise ResearchServiceError(
                    f"unsupported verification_state: {requested}"
                ) from exc
        else:
            state = None
        evidence = self.claims.get_evidence_for(claim_id)
        supports = [item for item in evidence if item.relation == Relation.SUPPORTS]
        contradicts = [item for item in evidence if item.relation == Relation.CONTRADICTS]
        if supports and contradicts:
            supporting = sum(item.strength for item in supports)
            contradicting = sum(item.strength for item in contradicts)
            calculated_state = (
                VerificationState.CONFLICTED
                if contradicting >= supporting
                else VerificationState.PARTIALLY_SUPPORTED
            )
        elif contradicts:
            calculated_state = VerificationState.REJECTED
        elif supports:
            calculated_state = (
                VerificationState.SUPPORTED
                if max(item.strength for item in supports) >= 0.5
                else VerificationState.PARTIALLY_SUPPORTED
            )
        else:
            calculated_state = VerificationState.UNVERIFIED
        if state is not None and state != calculated_state:
            raise ResearchServiceError(
                "verification_state does not match the associated evidence."
            )
        self.claims.verify_claim(
            claim_id,
            calculated_state,
            verifier=str(values.get("verifier") or "research.claim.verifier"),
            provenance=dict(values.get("provenance") or {}),
        )
        return self.get_claim(claim_id)

    def _validate_evidence_association(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise ResearchServiceError("each evidence item must be an object.")
        source_id = str(values.get("source_id") or "").strip()
        snapshot_ref = str(
            values.get("snapshot_ref") or values.get("snapshot_id") or ""
        ).strip()
        artifact_ref = str(
            values.get("artifact_ref") or values.get("artifact_id") or ""
        ).strip()
        if not source_id and not artifact_ref:
            raise ResearchServiceError(
                "evidence source_id or artifact_ref is required."
            )
        if source_id and self.sources.get(source_id) is None:
            raise ResearchServiceError(f"source not found: {source_id}")
        if snapshot_ref:
            if not source_id:
                raise ResearchServiceError(
                    "snapshot_ref requires a source_id."
                )
            snapshot = self.snapshots.get(snapshot_ref)
            if snapshot is None:
                raise ResearchServiceError(f"snapshot not found: {snapshot_ref}")
            if snapshot.source_id != source_id:
                raise ResearchServiceError(
                    "snapshot_ref does not belong to source_id."
                )
            if not artifact_ref:
                artifact_ref = snapshot.artifact_id
        if artifact_ref and self.artifacts.get(artifact_ref) is None:
            raise ResearchServiceError(f"artifact not found: {artifact_ref}")
        relation_value = str(values.get("relation") or Relation.SUPPORTS.value)
        try:
            relation = Relation(relation_value)
        except ValueError as exc:
            raise ResearchServiceError(
                f"unsupported evidence relation: {relation_value}"
            ) from exc
        return {
            "source_id": source_id,
            "snapshot_ref": snapshot_ref,
            "artifact_ref": artifact_ref,
            "relation": relation,
            "strength": float(
                values.get("strength")
                if values.get("strength") is not None
                else 0.5
            ),
            "description": str(values.get("description") or ""),
            "provenance": dict(values.get("provenance") or {}),
        }

    def status(self) -> dict[str, Any]:
        return {
            "gateway": "governed",
            "available": True,
            "network_scope": "public_internet",
            "methods": ["GET", "HEAD", "POST"],
            "max_response_bytes": WebGateway.MAX_CONTENT_SIZE,
            "max_request_body_bytes": WebGateway.MAX_REQUEST_BODY,
            "credential_boundary": "reference_only",
            "redirect_revalidation": True,
            "dns_pinning": True,
            "compressed_responses": "blocked",
            "total_timeout_budget": True,
            "cooperative_cancellation": True,
            "idempotent_retries": {"maximum": 2, "methods": ["GET", "HEAD"]},
            "destination_rate_limit_per_minute": 120,
            "source_count": self.sources.count(),
            "snapshot_count": len(self.snapshots.list(limit=1000)),
            "artifact_count": len(self.artifacts.list()),
            "claim_count": self.claims.summary()["total_claims"],
            "claim_evidence_count": self.claims.summary()["total_evidence"],
            "claim_contract": "1.0",
            "claim_event_authority": "EventStream",
            "evidence_level": "integrated-host",
        }

    def list_sources(self, *, limit: int = 100) -> dict[str, Any]:
        records = [record.to_dict() for record in self.sources.query(limit=limit)]
        return {"sources": records, "total": len(records)}

    def get_source(self, source_id: str) -> dict[str, Any]:
        source = self.sources.get(source_id)
        if source is None:
            raise KeyError(source_id)
        snapshots = [item.to_dict() for item in self.snapshots.list(source_id=source_id)]
        artifact = self.artifacts.get(source.snapshot_artifact_id) if source.snapshot_artifact_id else None
        return {
            "source": source.to_dict(),
            "snapshots": snapshots,
            "artifact": artifact.to_dict() if artifact else None,
            "citation": self.citation_for_source(source_id),
        }

    def _request(self, values: dict[str, Any]) -> WebRequest:
        request_id = str(values.get("request_id") or f"netreq_{network_run_id(values).rsplit('-', 1)[-1]}").strip()
        if not _REQUEST_ID.fullmatch(request_id):
            raise ResearchServiceError("request_id contains unsupported characters.")
        method = str(values.get("method") or "GET").strip().upper()
        inline_headers = values.get("headers") or {}
        if not isinstance(inline_headers, dict):
            raise ResearchServiceError("headers must be an object.")
        headers = {str(key): str(value) for key, value in inline_headers.items()}
        headers_ref = str(values.get("headers_ref") or "").strip()
        if headers_ref:
            referenced = self._read_reference(headers_ref, max_bytes=_MAX_HEADER_REF)
            try:
                referenced_headers = json.loads(referenced.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ResearchServiceError("headers_ref must point to a UTF-8 JSON object.") from exc
            if not isinstance(referenced_headers, dict):
                raise ResearchServiceError("headers_ref must point to a JSON object.")
            headers = {**{str(key): str(value) for key, value in referenced_headers.items()}, **headers}
        body_ref = str(values.get("body_ref") or "").strip()
        has_inline_body = "body" in values or "json" in values
        if body_ref and has_inline_body:
            raise ResearchServiceError("Use either an inline body or body_ref, not both.")
        if body_ref:
            body: Any = self._read_reference(body_ref, max_bytes=_MAX_BODY_REF)
        elif "json" in values:
            body = values.get("json")
        else:
            body = values.get("body")
        return WebRequest(
            request_id=request_id,
            method=method,
            url=str(values.get("url") or "").strip(),
            headers=headers,
            body=body,
            headers_ref=headers_ref,
            body_ref=body_ref,
            timeout_seconds=int(values.get("timeout_seconds") or 30),
            max_response_bytes=int(values.get("max_response_bytes") or 1_048_576),
            credential_ref=str(values.get("credential_ref") or "").strip(),
            network_scope=str(values.get("network_scope") or "public_internet").strip(),
            task_id=str(values.get("task_id") or f"research.fetch:{request_id}").strip(),
            run_id=network_run_id(values),
            trace_id=str(values.get("trace_id") or "").strip(),
            approval_requirement="approved",
            max_redirects=int(values.get("max_redirects") if values.get("max_redirects") is not None else 5),
            max_retries=int(values.get("max_retries") or 0),
            retry_backoff_ms=int(values.get("retry_backoff_ms") if values.get("retry_backoff_ms") is not None else 100),
        )

    def _read_reference(self, relative: str, *, max_bytes: int) -> bytes:
        try:
            target = normalize_workspace_path(str(self.root), relative)
        except PermissionError as exc:
            raise ResearchServiceError("Reference path escapes the active workspace.") from exc
        if not target.is_file():
            raise ResearchServiceError("Referenced workspace file does not exist.")
        if target.stat().st_size > max_bytes:
            raise ResearchServiceError("Referenced workspace file exceeds the allowed size.")
        return target.read_bytes()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        raise ResearchServiceError("reference list must be an array of strings.")
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))

def network_run_id(values: dict[str, Any]) -> str:
    explicit = str(values.get("run_id") or "").strip()
    if explicit:
        if not _REQUEST_ID.fullmatch(explicit):
            raise ResearchServiceError("run_id contains unsupported characters.")
        return explicit
    request_id = str(values.get("request_id") or "").strip()
    if request_id and _REQUEST_ID.fullmatch(request_id):
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16]
    else:
        canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"network-fetch-{digest}"


def search_network_values(values: dict[str, Any]) -> dict[str, Any]:
    """Translate a search request into the exact governed HTTP operation."""
    query = str(values.get("query") or "").strip()
    if not query:
        raise ResearchServiceError("query is required.")
    if len(query) > 1000:
        raise ResearchServiceError("query exceeds 1000 characters.")
    request_id = str(values.get("request_id") or "").strip()
    result = {
        "request_id": request_id,
        "method": "GET",
        "url": _SEARCH_URL + "?" + urlencode({"q": query}),
        "headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"},
        "body": None,
        "network_scope": "public_internet",
        "max_response_bytes": max(
            1,
            min(
                int(values.get("max_response_bytes") or 1_048_576),
                WebGateway.MAX_CONTENT_SIZE,
            ),
        ),
        "timeout_seconds": max(
            1,
            min(int(values.get("timeout_seconds") or 30), 120),
        ),
        "max_redirects": 5,
        "max_retries": max(0, min(int(values.get("max_retries") if values.get("max_retries") is not None else 1), 2)),
        "retry_backoff_ms": max(0, min(int(values.get("retry_backoff_ms") if values.get("retry_backoff_ms") is not None else 100), 2_000)),
        "task_id": str(values.get("task_id") or f"research.search:{request_id}"),
    }
    for key in ("run_id", "trace_id"):
        if values.get(key):
            result[key] = values[key]
    return result


class _SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture = ""
        self._capture_tag = ""
        self._text: list[str] = []
        self._bing_result = False
        self._bing_h2 = False
        self._bing_caption = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "li" and "b_algo" in classes:
            if self._current:
                self._commit()
            self._current = {"url": "", "title": "", "snippet": ""}
            self._bing_result = True
            return
        if self._bing_result and tag == "h2":
            self._bing_h2 = True
            return
        if self._bing_result and tag == "div" and "b_caption" in classes:
            self._bing_caption = True
            return
        if self._bing_result and self._bing_h2 and tag == "a" and self._current:
            self._current["url"] = _search_result_url(values.get("href", ""))
            self._begin_capture("title", tag)
            return
        if self._bing_result and self._bing_caption and tag == "p":
            self._begin_capture("snippet", tag)
            return
        if tag == "a" and "result__a" in classes:
            if self._current:
                self._commit()
            self._current = {
                "url": _search_result_url(values.get("href", "")),
                "title": "",
                "snippet": "",
            }
            self._begin_capture("title", tag)
        elif self._current and (
            "result__snippet" in classes or "result-snippet" in classes
        ):
            self._begin_capture("snippet", tag)

    def handle_data(self, data: str) -> None:
        if self._current and self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current and self._capture and tag == self._capture_tag:
            value = " ".join("".join(self._text).split())
            if value:
                self._current[self._capture] = value
            self._capture = ""
            self._capture_tag = ""
            self._text = []
        if self._bing_result and tag == "h2":
            self._bing_h2 = False
        elif self._bing_result and tag == "div" and self._bing_caption:
            self._bing_caption = False
        elif self._bing_result and tag == "li":
            self._commit()
            self._bing_result = False

    def close(self) -> None:
        super().close()
        if self._current:
            self._commit()

    def _begin_capture(self, field: str, tag: str) -> None:
        self._capture = field
        self._capture_tag = tag
        self._text = []

    def _commit(self) -> None:
        if (
            self._current
            and self._current.get("url")
            and self._current.get("title")
        ):
            self.results.append(self._current)
        self._current = None
        self._capture = ""
        self._capture_tag = ""
        self._text = []

def _search_result_url(value: str) -> str:
    candidate = html.unescape(str(value or "")).strip()
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    parts = urlsplit(candidate)
    if (
        (parts.hostname or "").lower().endswith("duckduckgo.com")
        and parts.path.startswith("/l/")
    ):
        candidate = (parse_qs(parts.query).get("uddg") or [""])[0]
        parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return ""
    return candidate


def parse_search_results(
    content: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    parser = _SearchResultParser()
    parser.feed(str(content or ""))
    parser.close()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parser.results:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        results.append({"rank": len(results) + 1, **item})
        if len(results) >= max(1, min(int(limit), _MAX_SEARCH_RESULTS)):
            break
    return results
def safe_request_summary(values: dict[str, Any]) -> dict[str, Any]:
    body = values.get("json") if "json" in values else values.get("body")
    return {
        "request_id": str(values.get("request_id") or ""),
        "method": str(values.get("method") or "GET").upper(),
        "url": _safe_url(str(values.get("url") or "")),
        "credential_ref": str(values.get("credential_ref") or ""),
        "network_scope": str(values.get("network_scope") or "public_internet"),
        "max_response_bytes": int(values.get("max_response_bytes") or 1_048_576),
        "max_retries": int(values.get("max_retries") or 0),
        "retry_backoff_ms": int(values.get("retry_backoff_ms") if values.get("retry_backoff_ms") is not None else 100),
        "body_sha256": _body_hash(body),
        "body_ref": str(values.get("body_ref") or ""),
        "headers_ref": str(values.get("headers_ref") or ""),
    }


def record_network_governance_event(
    values: dict[str, Any],
    event_type: str,
    *,
    approval_request_id: str = "",
    decision_id: str = "",
    proposal_hash: str = "",
) -> str:
    """Append approval lifecycle to the canonical EventStream only."""
    root = Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    stream = EventStream(str(root))
    run_id = network_run_id(values)
    summary = safe_request_summary(values)
    task_id = str(values.get("task_id") or f"research.fetch:{summary['request_id'] or run_id}")
    if stream.get_run(run_id) is None:
        stream.create_run(
            run_id,
            task_id=task_id,
            total_steps=1,
            metadata={"authority": "EventStream", "operation": "network.fetch"},
        )
        stream.emit_state_change(run_id, RunState.CREATED, task_id=task_id, request_id=summary["request_id"])
    existing = {event.event_type for event in stream.load_events(run_id)}
    if "network.requested" not in existing:
        stream.emit(RunEvent(
            run_id=run_id,
            task_id=task_id,
            event_type="network.requested",
            actor="governance.gate",
            payload=summary,
        ))
    if event_type not in existing:
        payload = {
            "request_id": summary["request_id"],
            "approval_request_id": approval_request_id,
            "decision_id": decision_id,
            "proposal_hash": proposal_hash,
        }
        stream.emit(RunEvent(
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            actor="governance.gate",
            payload={key: value for key, value in payload.items() if value},
        ))
    return run_id


__all__ = [
    "ResearchEvidenceService",
    "ResearchServiceError",
    "network_run_id",
    "parse_search_results",
    "record_network_governance_event",
    "safe_request_summary",
    "search_network_values",
]

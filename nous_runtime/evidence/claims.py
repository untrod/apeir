# -*- coding: utf-8 -*-
"""Persistent Claim-Evidence graph over the canonical EventStream.

This module is the P14 authority for claims and their evidence associations. It
persists graph state atomically, but lifecycle history remains in EventStream;
there is deliberately no parallel Claim event store.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from nous_runtime.locking import file_lock


class Relation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"
    VERIFIED_BY = "verified_by"
    SUPERSEDES = "supersedes"
    STALE_DUE_TO = "stale_due_to"
    DEPENDS_ON = "depends_on"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"


@dataclass
class Claim:
    """A traceable professional statement associated with durable evidence."""

    claim_id: str = ""
    statement: str = ""
    task_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    snapshot_refs: tuple[str, ...] = ()
    confidence: float = 0.0
    created_by: str = "runtime"
    created_at: str = ""
    verification_state: VerificationState = VerificationState.UNVERIFIED
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.statement = str(self.statement or "").strip()
        self.evidence_refs = _unique(self.evidence_refs)
        self.source_refs = _unique(self.source_refs)
        self.snapshot_refs = _unique(self.snapshot_refs)
        self.confidence = max(0.0, min(float(self.confidence), 1.0))
        if not isinstance(self.verification_state, VerificationState):
            self.verification_state = VerificationState(str(self.verification_state))
        self.provenance = dict(self.provenance or {})

    @property
    def text(self) -> str:
        """Compatibility alias for the pre-P14 in-memory model."""
        return self.statement

    @text.setter
    def text(self, value: str) -> None:
        self.statement = str(value or "").strip()

    @property
    def source_id(self) -> str:
        """Compatibility alias for a claim's first source."""
        return self.source_refs[0] if self.source_refs else ""

    @source_id.setter
    def source_id(self, value: str) -> None:
        self.source_refs = _unique((value, *self.source_refs)) if value else self.source_refs

    @property
    def status(self) -> str:
        """Pre-P14 weighted compatibility status.

        Canonical callers must use verification_state, which always exposes a
        conflict when both supporting and contradicting evidence exist.
        """
        legacy = getattr(self, "_legacy_status", "")
        if legacy:
            return legacy
        if self.verification_state in {VerificationState.CONFLICTED, VerificationState.REJECTED}:
            return "contradicted"
        return self.verification_state.value

    @status.setter
    def status(self, value: str) -> None:
        self._legacy_status = str(value or "unverified")

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["verification_state"] = self.verification_state.value
        values["evidence_refs"] = list(self.evidence_refs)
        values["source_refs"] = list(self.source_refs)
        values["snapshot_refs"] = list(self.snapshot_refs)
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "Claim":
        data = dict(values or {})
        if not data.get("statement") and data.get("text"):
            data["statement"] = data["text"]
        if not data.get("source_refs") and data.get("source_id"):
            data["source_refs"] = [data["source_id"]]
        state = data.get("verification_state") or data.get("status") or "unverified"
        if state in {"contradicted", "stale"}:
            state = "conflicted" if state == "contradicted" else "unverified"
        data["verification_state"] = VerificationState(str(state))
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class Evidence:
    """A typed association from a Claim to Source/Snapshot/Artifact provenance."""

    evidence_id: str = ""
    claim_id: str = ""
    source_id: str = ""
    relation: Relation = Relation.SUPPORTS
    strength: float = 0.0
    description: str = ""
    snapshot_ref: str = ""
    artifact_ref: str = ""
    created_at: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.relation, Relation):
            self.relation = Relation(str(self.relation))
        self.strength = max(0.0, min(float(self.strength), 1.0))
        self.provenance = dict(self.provenance or {})

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["relation"] = self.relation.value
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "Evidence":
        data = dict(values or {})
        data["relation"] = Relation(str(data.get("relation") or Relation.SUPPORTS.value))
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in allowed})


class ClaimEvidenceGraph:
    """Thread-safe, optionally persistent Claim/Evidence graph.

    The JSON file is a materialized graph state. Claim lifecycle and decisions
    are emitted only to the supplied canonical EventStream.
    """

    def __init__(
        self,
        storage_path: str | Path = "",
        *,
        event_stream: Any | None = None,
    ) -> None:
        self._claims: dict[str, Claim] = {}
        self._evidence: dict[str, Evidence] = {}
        self._edges: list[tuple[str, str, Relation]] = []
        self._lock = threading.RLock()
        self._path = Path(storage_path).expanduser().resolve() if storage_path else None
        self._events = event_stream
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def add_claim(
        self,
        text: str = "",
        source_id: str = "",
        confidence: float = 0.5,
        *,
        statement: str = "",
        task_id: str = "",
        run_id: str = "",
        trace_id: str = "",
        evidence_refs: Iterable[str] = (),
        source_refs: Iterable[str] = (),
        snapshot_refs: Iterable[str] = (),
        created_by: str = "runtime",
        provenance: dict[str, Any] | None = None,
        claim_id: str = "",
    ) -> Claim:
        value = str(statement or text or "").strip()
        if not value:
            raise ValueError("claim statement is required")
        sources = _unique((source_id, *tuple(source_refs))) if source_id else _unique(source_refs)
        claim_identifier = str(claim_id or f"claim_{uuid.uuid4().hex[:12]}")
        suffix = claim_identifier.removeprefix("claim_")
        claim = Claim(
            claim_id=claim_identifier,
            statement=value,
            task_id=str(task_id or f"research.claim:{claim_identifier}"),
            run_id=str(run_id or f"claim-{suffix}"),
            trace_id=str(trace_id or f"trace-{suffix}"),
            evidence_refs=_unique(evidence_refs),
            source_refs=sources,
            snapshot_refs=_unique(snapshot_refs),
            confidence=confidence,
            created_by=str(created_by or "runtime"),
            created_at=_utc_now(),
            provenance=dict(provenance or {}),
        )
        with self._lock:
            if claim.claim_id in self._claims:
                raise ValueError(f"claim already exists: {claim.claim_id}")
            self._claims[claim.claim_id] = claim
            self._persist()
        self._emit(claim, "claim.created", {
            "claim_id": claim.claim_id,
            "verification_state": claim.verification_state.value,
            "confidence": claim.confidence,
            "source_refs": list(claim.source_refs),
            "snapshot_refs": list(claim.snapshot_refs),
        })
        return claim

    def add_evidence(
        self,
        claim_id: str,
        source_id: str,
        relation: Relation | str,
        strength: float = 0.5,
        *,
        snapshot_ref: str = "",
        artifact_ref: str = "",
        description: str = "",
        evidence_id: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> Evidence:
        relation_value = relation if isinstance(relation, Relation) else Relation(str(relation))
        with self._lock:
            claim = self._claims.get(str(claim_id))
            if claim is None:
                raise KeyError(claim_id)
            evidence = Evidence(
                evidence_id=str(evidence_id or f"ev_{uuid.uuid4().hex[:12]}"),
                claim_id=claim.claim_id,
                source_id=str(source_id or ""),
                relation=relation_value,
                strength=strength,
                description=str(description or ""),
                snapshot_ref=str(snapshot_ref or ""),
                artifact_ref=str(artifact_ref or ""),
                created_at=_utc_now(),
                provenance=dict(provenance or {}),
            )
            if evidence.evidence_id in self._evidence:
                raise ValueError(f"evidence already exists: {evidence.evidence_id}")
            self._evidence[evidence.evidence_id] = evidence
            self._edges.append((claim.claim_id, evidence.evidence_id, evidence.relation))
            claim.evidence_refs = _unique((*claim.evidence_refs, evidence.evidence_id))
            if evidence.source_id:
                claim.source_refs = _unique((*claim.source_refs, evidence.source_id))
            if evidence.snapshot_ref:
                claim.snapshot_refs = _unique((*claim.snapshot_refs, evidence.snapshot_ref))
            previous = claim.verification_state
            claim.verification_state = self._calculate_state(claim.claim_id)
            claim.status = self._compatibility_state(claim.claim_id)
            self._persist()
        self._emit(claim, "claim.evidence_attached", {
            "claim_id": claim.claim_id,
            "evidence_id": evidence.evidence_id,
            "source_id": evidence.source_id,
            "snapshot_ref": evidence.snapshot_ref,
            "artifact_ref": evidence.artifact_ref,
            "relation": evidence.relation.value,
            "strength": evidence.strength,
        })
        if claim.verification_state != previous:
            self._emit_verification(claim)
        return evidence

    def verify_claim(
        self,
        claim_id: str,
        verification_state: VerificationState | str | None = None,
        *,
        verifier: str = "runtime.verifier",
        provenance: dict[str, Any] | None = None,
    ) -> Claim:
        with self._lock:
            claim = self._claims.get(str(claim_id))
            if claim is None:
                raise KeyError(claim_id)
            calculated = self._calculate_state(claim.claim_id)
            requested = (
                verification_state
                if isinstance(verification_state, VerificationState)
                else VerificationState(str(verification_state))
                if verification_state
                else calculated
            )
            claim.verification_state = requested
            claim.provenance["last_verifier"] = str(verifier or "runtime.verifier")
            claim.provenance["verified_at"] = _utc_now()
            if provenance:
                claim.provenance.update(dict(provenance))
            self._persist()
        self._emit_verification(claim)
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        with self._lock:
            return self._claims.get(str(claim_id))

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        with self._lock:
            return self._evidence.get(str(evidence_id))

    def get_evidence_for(self, claim_id: str) -> list[Evidence]:
        with self._lock:
            claim = self._claims.get(str(claim_id))
            refs = set(claim.evidence_refs if claim else ())
            return [item for key, item in self._evidence.items() if key in refs]

    def get_claims_for_source(self, source_id: str) -> list[Claim]:
        with self._lock:
            return [
                claim
                for claim in self._claims.values()
                if str(source_id) in claim.source_refs
            ]

    def list_claims(
        self,
        *,
        verification_state: VerificationState | str | None = None,
        limit: int = 200,
    ) -> list[Claim]:
        with self._lock:
            claims = list(self._claims.values())
        if verification_state:
            state = (
                verification_state
                if isinstance(verification_state, VerificationState)
                else VerificationState(str(verification_state))
            )
            claims = [claim for claim in claims if claim.verification_state == state]
        claims.sort(key=lambda claim: claim.created_at, reverse=True)
        return claims[: max(1, min(int(limit), 1000))]

    def trace_claim(self, claim_id: str) -> dict[str, Any]:
        claim = self.get_claim(claim_id)
        if claim is None:
            raise KeyError(claim_id)
        evidence = self.get_evidence_for(claim_id)
        return {
            "claim": claim.to_dict(),
            "evidence": [item.to_dict() for item in evidence],
            "source_refs": list(claim.source_refs),
            "snapshot_refs": list(claim.snapshot_refs),
            "artifact_refs": list(_unique(
                item.artifact_ref for item in evidence if item.artifact_ref
            )),
        }

    def trace_source(self, source_id: str) -> dict[str, Any]:
        claims = self.get_claims_for_source(source_id)
        evidence = [
            item
            for claim in claims
            for item in self.get_evidence_for(claim.claim_id)
            if item.source_id == source_id
        ]
        return {
            "source_id": str(source_id),
            "evidence": [item.to_dict() for item in evidence],
            "claims": [claim.to_dict() for claim in claims],
        }

    def get_conflicts(self) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for claim in self.list_claims(limit=1000):
            evidence = self.get_evidence_for(claim.claim_id)
            supports = [item for item in evidence if item.relation == Relation.SUPPORTS]
            contradicts = [item for item in evidence if item.relation == Relation.CONTRADICTS]
            if (
                supports
                and contradicts
                and sum(item.strength for item in contradicts)
                >= sum(item.strength for item in supports)
            ):
                conflicts.append({
                    "claim_id": claim.claim_id,
                    "text": claim.statement,
                    "supporting_count": len(supports),
                    "contradicting_count": len(contradicts),
                })
        return conflicts

    def mark_stale(self, source_id: str) -> list[str]:
        stale: list[str] = []
        with self._lock:
            for claim in self._claims.values():
                if str(source_id) in claim.source_refs:
                    claim.verification_state = VerificationState.UNVERIFIED
                    claim.provenance["stale"] = True
                    claim.provenance["stale_source_id"] = str(source_id)
                    stale.append(claim.claim_id)
            self._persist()
        return stale

    def summary(self) -> dict[str, Any]:
        claims = self.list_claims(limit=1000)
        counts = {
            state.value: sum(1 for claim in claims if claim.verification_state == state)
            for state in VerificationState
        }
        return {
            "total_claims": len(claims),
            "total_evidence": len(self._evidence),
            **counts,
            "contradicted": counts["conflicted"] + counts["rejected"],
            "stale": sum(1 for claim in claims if claim.provenance.get("stale")),
            "conflicts": len(self.get_conflicts()),
        }

    def _compatibility_state(self, claim_id: str) -> str:
        evidence = self.get_evidence_for(claim_id)
        supporting = sum(
            item.strength for item in evidence if item.relation == Relation.SUPPORTS
        )
        contradicting = sum(
            item.strength for item in evidence if item.relation == Relation.CONTRADICTS
        )
        if supporting and supporting >= contradicting:
            return "supported"
        if contradicting:
            return "contradicted"
        return "unverified"
    def _calculate_state(self, claim_id: str) -> VerificationState:
        evidence = self.get_evidence_for(claim_id)
        supports = [item for item in evidence if item.relation == Relation.SUPPORTS]
        contradicts = [item for item in evidence if item.relation == Relation.CONTRADICTS]
        if supports and contradicts:
            supporting = sum(item.strength for item in supports)
            contradicting = sum(item.strength for item in contradicts)
            return (
                VerificationState.CONFLICTED
                if contradicting >= supporting
                else VerificationState.PARTIALLY_SUPPORTED
            )
        if contradicts:
            return VerificationState.REJECTED
        if supports:
            strongest = max(item.strength for item in supports)
            return (
                VerificationState.SUPPORTED
                if strongest >= 0.5
                else VerificationState.PARTIALLY_SUPPORTED
            )
        return VerificationState.UNVERIFIED

    def _emit_verification(self, claim: Claim) -> None:
        state = claim.verification_state
        event_type = {
            VerificationState.CONFLICTED: "claim.conflicted",
            VerificationState.REJECTED: "claim.rejected",
        }.get(state, "claim.verified")
        self._emit(claim, event_type, {
            "claim_id": claim.claim_id,
            "verification_state": state.value,
            "confidence": claim.confidence,
            "evidence_refs": list(claim.evidence_refs),
        })

    def _emit(self, claim: Claim, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        from nous_runtime.events import RunEvent

        run_id = claim.run_id or f"claim-{claim.claim_id.removeprefix('claim_')}"
        task_id = claim.task_id or f"research.claim:{claim.claim_id}"
        enriched = dict(payload)
        if claim.trace_id:
            enriched["trace_id"] = claim.trace_id
        self._events.emit(RunEvent(
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            actor=claim.created_by or "runtime",
            payload=enriched,
        ))

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            with file_lock(str(self._path) + ".lock"):
                values = json.loads(self._path.read_text(encoding="utf-8"))
            for value in values.get("claims", []):
                if isinstance(value, dict):
                    claim = Claim.from_dict(value)
                    if claim.claim_id:
                        self._claims[claim.claim_id] = claim
            for value in values.get("evidence", []):
                if isinstance(value, dict):
                    evidence = Evidence.from_dict(value)
                    if evidence.evidence_id and evidence.claim_id in self._claims:
                        self._evidence[evidence.evidence_id] = evidence
                        self._edges.append((evidence.claim_id, evidence.evidence_id, evidence.relation))
        except (OSError, ValueError, TypeError):
            self._claims.clear()
            self._evidence.clear()
            self._edges.clear()

    def _persist(self) -> None:
        if self._path is None:
            return
        payload = {
            "schema_version": "1.0",
            "authority": "ClaimEvidenceGraph",
            "event_authority": "EventStream",
            "claims": [claim.to_dict() for claim in self._claims.values()],
            "evidence": [item.to_dict() for item in self._evidence.values()],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=".claims-", dir=self._path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            with file_lock(str(self._path) + ".lock"):
                os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


__all__ = [
    "Claim",
    "ClaimEvidenceGraph",
    "Evidence",
    "Relation",
    "VerificationState",
]

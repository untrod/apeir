# -*- coding: utf-8 -*-
"""
Canonical governance contracts for B1 authorization foundation.

All contracts are immutable (frozen dataclasses), versioned, and support
deterministic serialization and hashing. No secrets are persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.schema_registry import GOVERNANCE_SCHEMA_VERSION as SCHEMA_VERSION


# Helpers

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{_uuid.uuid4().hex[:12]}"


def _deterministic_json(obj: Any) -> str:
    """Serialize to JSON with sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize parameters for deterministic hashing."""
    result: dict[str, Any] = {}
    for key in sorted(params):
        if key.startswith("_"):
            continue
        val = params[key]
        if val is None:
            result[key] = None
        elif isinstance(val, bool):
            result[key] = val
        elif isinstance(val, int):
            result[key] = val
        elif isinstance(val, float):
            result[key] = round(val, 6)
        elif isinstance(val, str):
            result[key] = val.strip()
        elif isinstance(val, (list, tuple)):
            result[key] = [_normalize_scalar(v) for v in val]
        elif isinstance(val, dict):
            result[key] = _normalize_params(val)
        else:
            result[key] = str(val)
    return result


def _normalize_scalar(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (bool, int)):
        return val
    if isinstance(val, float):
        return round(val, 6)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        return _normalize_params(val)
    return str(val)


def _redact_secrets(d: dict[str, Any]) -> dict[str, Any]:
    """Replace sensitive values with <REDACTED>."""
    SENSITIVE = {"api_key", "authorization", "cookie", "password", "private_key",
                  "secret", "token", "signing_key", "credential"}
    result: dict[str, Any] = {}
    for k, v in d.items():
        if any(s in k.lower() for s in SENSITIVE):
            result[k] = "<REDACTED>"
        elif isinstance(v, dict):
            result[k] = _redact_secrets(v)
        elif isinstance(v, (list, tuple)):
            result[k] = [_redact_secrets(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


# Contracts

@dataclass(frozen=True)
class AuthorizationContext:
    """Immutable context established before authorization evaluation."""
    context_id: str = field(default_factory=lambda: _new_id("ctx"))
    subject_type: str = ""           # "user" | "node" | "service" | "automation"
    subject_id: str = ""
    subject_claims: tuple[dict[str, Any], ...] = ()
    authn_method: str = ""           # "cli_os_user" | "api_token" | "node_key" | "pairing_code"
    authn_confidence: float = 0.0
    session_id: str = ""
    session_started: str = ""
    session_device: str = ""
    session_locality: str = "local"  # "local" | "remote" | "unknown"
    request_id: str = field(default_factory=lambda: _new_id("req"))
    requested_at: str = field(default_factory=_utc_now)
    schema_version: str = SCHEMA_VERSION
    runtime_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id, "subject_type": self.subject_type,
            "subject_id": self.subject_id, "subject_claims": list(self.subject_claims),
            "authn_method": self.authn_method, "authn_confidence": self.authn_confidence,
            "session_id": self.session_id, "session_started": self.session_started,
            "session_device": self.session_device, "session_locality": self.session_locality,
            "request_id": self.request_id, "requested_at": self.requested_at,
            "schema_version": self.schema_version, "runtime_version": self.runtime_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuthorizationContext":
        return cls(
            context_id=d.get("context_id", ""), subject_type=d.get("subject_type", ""),
            subject_id=d.get("subject_id", ""),
            subject_claims=tuple(d.get("subject_claims") or ()),
            authn_method=d.get("authn_method", ""),
            authn_confidence=float(d.get("authn_confidence", 0.0)),
            session_id=d.get("session_id", ""),
            session_started=d.get("session_started", ""),
            session_device=d.get("session_device", ""),
            session_locality=d.get("session_locality", "local"),
            request_id=d.get("request_id", ""), requested_at=d.get("requested_at", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            runtime_version=d.get("runtime_version", ""),
        )


@dataclass(frozen=True)
class ActionProposal:
    """Immutable, hash-bound description of what the runtime wants to execute."""
    proposal_id: str = field(default_factory=lambda: _new_id("ap"))
    proposal_hash: str = ""
    action_id: str = field(default_factory=lambda: _new_id("act"))
    action_type: str = ""            # "capability.execute" | "workspace.mutate" | ...
    capability_id: str = ""
    provider_id: str = ""
    model_id: str = ""
    agent_id: str = ""
    deployment_channel: str = ""
    locality: str = ""
    parameter_hash: str = ""
    parameter_summary: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    target_node: str = ""
    target_workspace: str = ""
    target_project: str = ""
    target_work_item: str = ""
    affected_resources: tuple[str, ...] = ()
    data_classification: str = "internal"  # "public"|"internal"|"confidential"|"restricted"
    external_recipients: tuple[str, ...] = ()
    estimated_cost_usd: float = 0.0
    estimated_duration_ms: int = 0
    side_effect_class: str = "unknown"  # "none"|"read_only"|"local_write"|"external_write"|"destructive"
    reversibility: str = "unknown"      # "reversible"|"partially_reversible"|"irreversible"
    retry_behavior: str = "unknown"     # "idempotent"|"safe_with_key"|"unsafe"
    required_permissions: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    created_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.proposal_hash:
            object.__setattr__(self, "proposal_hash", self._compute_hash())

    def _compute_hash(self) -> str:
        """SHA-256 over canonical JSON of all authorization-relevant fields."""
        fields = {
            "action_type": self.action_type,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "agent_id": self.agent_id,
            "deployment_channel": self.deployment_channel,
            "locality": self.locality,
            "parameter_hash": self.parameter_hash or _sha256(
                _deterministic_json(_normalize_params(self.params))
            ),
            "target_node": self.target_node,
            "target_workspace": self.target_workspace,
            "target_project": self.target_project,
            "target_work_item": self.target_work_item,
            "affected_resources": sorted(self.affected_resources),
            "data_classification": self.data_classification,
            "external_recipients": sorted(self.external_recipients),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "estimated_duration_ms": self.estimated_duration_ms,
            "side_effect_class": self.side_effect_class,
            "reversibility": self.reversibility,
            "retry_behavior": self.retry_behavior,
            "required_permissions": sorted(self.required_permissions),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "schema_version": self.schema_version,
        }
        return _sha256(_deterministic_json(fields))

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id, "proposal_hash": self.proposal_hash,
            "action_id": self.action_id, "action_type": self.action_type,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "agent_id": self.agent_id,
            "deployment_channel": self.deployment_channel,
            "locality": self.locality,
            "parameter_hash": self.parameter_hash,
            "parameter_summary": self.parameter_summary,
            "target_node": self.target_node, "target_workspace": self.target_workspace,
            "target_project": self.target_project, "target_work_item": self.target_work_item,
            "affected_resources": list(self.affected_resources),
            "data_classification": self.data_classification,
            "external_recipients": list(self.external_recipients),
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_duration_ms": self.estimated_duration_ms,
            "side_effect_class": self.side_effect_class,
            "reversibility": self.reversibility,
            "retry_behavior": self.retry_behavior,
            "required_permissions": list(self.required_permissions),
            "evidence_references": list(self.evidence_references),
            "created_at": self.created_at, "expires_at": self.expires_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionProposal":
        return cls(
            proposal_id=d.get("proposal_id", ""),
            proposal_hash=d.get("proposal_hash", ""),
            action_id=d.get("action_id", ""),
            action_type=d.get("action_type", ""),
            capability_id=d.get("capability_id", ""),
            provider_id=d.get("provider_id", ""),
            model_id=d.get("model_id", ""),
            agent_id=d.get("agent_id", ""),
            deployment_channel=d.get("deployment_channel", ""),
            locality=d.get("locality", ""),
            parameter_hash=d.get("parameter_hash", ""),
            parameter_summary=d.get("parameter_summary", ""),
            target_node=d.get("target_node", ""),
            target_workspace=d.get("target_workspace", ""),
            target_project=d.get("target_project", ""),
            target_work_item=d.get("target_work_item", ""),
            affected_resources=tuple(d.get("affected_resources") or ()),
            data_classification=d.get("data_classification", "internal"),
            external_recipients=tuple(d.get("external_recipients") or ()),
            estimated_cost_usd=float(d.get("estimated_cost_usd", 0.0)),
            estimated_duration_ms=int(d.get("estimated_duration_ms", 0)),
            side_effect_class=d.get("side_effect_class", "unknown"),
            reversibility=d.get("reversibility", "unknown"),
            retry_behavior=d.get("retry_behavior", "unknown"),
            required_permissions=tuple(d.get("required_permissions") or ()),
            evidence_references=tuple(d.get("evidence_references") or ()),
            created_at=d.get("created_at", ""),
            expires_at=d.get("expires_at", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ApprovalScope:
    """Exact boundaries of what was approved."""
    action_id: str = ""
    proposal_hash: str = ""
    project_id: str = ""
    milestone_id: str = ""
    work_item_id: str = ""
    task_id: str = ""
    capability_id: str = ""
    allowed_capabilities: tuple[str, ...] = ()
    provider_id: str = ""
    allowed_providers: tuple[str, ...] = ()
    model_id: str = ""
    allowed_models: tuple[str, ...] = ()
    agent_id: str = ""
    node_id: str = ""
    workspace_path: str = ""
    allowed_files: tuple[str, ...] = ()
    allowed_directories: tuple[str, ...] = ()
    denied_files: tuple[str, ...] = ()
    denied_directories: tuple[str, ...] = ()
    data_classification: str = ""
    external_recipients: tuple[str, ...] = ()
    cost_ceiling_usd: float = 0.0
    token_ceiling: int = 0
    execution_time_ceiling_ms: int = 0
    max_attempts: int = 1
    max_uses: int = 1
    valid_from: str = ""
    valid_until: str = ""
    allowed_side_effect_classes: tuple[str, ...] = ()
    deployment_channel: str = ""

    def is_subset_of(self, other: "ApprovalScope") -> bool:
        """True if self is equal to or narrower than other in every dimension."""
        checks = [
            _str_subset(self.action_id, other.action_id),
            _str_subset(self.proposal_hash, other.proposal_hash),
            _str_subset(self.project_id, other.project_id),
            _str_subset(self.capability_id, other.capability_id),
            _tuple_subset(self.allowed_capabilities, other.allowed_capabilities),
            _str_subset(self.provider_id, other.provider_id),
            _tuple_subset(self.allowed_providers, other.allowed_providers),
            _str_subset(self.model_id, other.model_id),
            _tuple_subset(self.allowed_models, other.allowed_models),
            _str_subset(self.node_id, other.node_id),
            _path_subset(self.workspace_path, other.workspace_path),
            _tuple_subset(self.allowed_files, other.allowed_files),
            _tuple_subset(self.allowed_directories, other.allowed_directories),
            _class_subset(self.data_classification, other.data_classification),
            _tuple_subset(self.external_recipients, other.external_recipients),
            _num_subset(self.cost_ceiling_usd, other.cost_ceiling_usd, "lte"),
            _num_subset(self.token_ceiling, other.token_ceiling, "lte"),
            _num_subset(self.execution_time_ceiling_ms, other.execution_time_ceiling_ms, "lte"),
            _num_subset(self.max_attempts, other.max_attempts, "lte"),
            _num_subset(self.max_uses, other.max_uses, "lte"),
            _tuple_subset(self.allowed_side_effect_classes, other.allowed_side_effect_classes),
            _str_subset(self.deployment_channel, other.deployment_channel),
        ]
        return all(checks)

    @classmethod
    def from_proposal(cls, proposal: ActionProposal) -> "ApprovalScope":
        """Build a scope that exactly matches a proposal."""
        return cls(
            action_id=proposal.action_id,
            proposal_hash=proposal.proposal_hash,
            project_id=proposal.target_project,
            work_item_id=proposal.target_work_item,
            capability_id=proposal.capability_id,
            workspace_path=proposal.target_workspace,
            node_id=proposal.target_node,
            allowed_files=proposal.affected_resources,
            data_classification=proposal.data_classification,
            external_recipients=proposal.external_recipients,
            cost_ceiling_usd=proposal.estimated_cost_usd,
            execution_time_ceiling_ms=proposal.estimated_duration_ms,
            max_uses=1,
            allowed_side_effect_classes=(proposal.side_effect_class,) if proposal.side_effect_class else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id, "proposal_hash": self.proposal_hash,
            "project_id": self.project_id, "milestone_id": self.milestone_id,
            "work_item_id": self.work_item_id, "task_id": self.task_id,
            "capability_id": self.capability_id,
            "allowed_capabilities": list(self.allowed_capabilities),
            "provider_id": self.provider_id, "allowed_providers": list(self.allowed_providers),
            "model_id": self.model_id, "allowed_models": list(self.allowed_models),
            "agent_id": self.agent_id, "node_id": self.node_id,
            "workspace_path": self.workspace_path,
            "allowed_files": list(self.allowed_files),
            "allowed_directories": list(self.allowed_directories),
            "denied_files": list(self.denied_files),
            "denied_directories": list(self.denied_directories),
            "data_classification": self.data_classification,
            "external_recipients": list(self.external_recipients),
            "cost_ceiling_usd": self.cost_ceiling_usd,
            "token_ceiling": self.token_ceiling,
            "execution_time_ceiling_ms": self.execution_time_ceiling_ms,
            "max_attempts": self.max_attempts, "max_uses": self.max_uses,
            "valid_from": self.valid_from, "valid_until": self.valid_until,
            "allowed_side_effect_classes": list(self.allowed_side_effect_classes),
            "deployment_channel": self.deployment_channel,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ApprovalScope":
        return cls(
            action_id=d.get("action_id", ""), proposal_hash=d.get("proposal_hash", ""),
            project_id=d.get("project_id", ""), milestone_id=d.get("milestone_id", ""),
            work_item_id=d.get("work_item_id", ""), task_id=d.get("task_id", ""),
            capability_id=d.get("capability_id", ""),
            allowed_capabilities=tuple(d.get("allowed_capabilities") or ()),
            provider_id=d.get("provider_id", ""),
            allowed_providers=tuple(d.get("allowed_providers") or ()),
            model_id=d.get("model_id", ""),
            allowed_models=tuple(d.get("allowed_models") or ()),
            agent_id=d.get("agent_id", ""), node_id=d.get("node_id", ""),
            workspace_path=d.get("workspace_path", ""),
            allowed_files=tuple(d.get("allowed_files") or ()),
            allowed_directories=tuple(d.get("allowed_directories") or ()),
            denied_files=tuple(d.get("denied_files") or ()),
            denied_directories=tuple(d.get("denied_directories") or ()),
            data_classification=d.get("data_classification", ""),
            external_recipients=tuple(d.get("external_recipients") or ()),
            cost_ceiling_usd=float(d.get("cost_ceiling_usd", 0.0)),
            token_ceiling=int(d.get("token_ceiling", 0)),
            execution_time_ceiling_ms=int(d.get("execution_time_ceiling_ms", 0)),
            max_attempts=int(d.get("max_attempts", 1)),
            max_uses=int(d.get("max_uses", 1)),
            valid_from=d.get("valid_from", ""), valid_until=d.get("valid_until", ""),
            allowed_side_effect_classes=tuple(d.get("allowed_side_effect_classes") or ()),
            deployment_channel=d.get("deployment_channel", ""),
        )


@dataclass(frozen=True)
class RiskEnvelope:
    """Multi-dimensional risk assessment."""
    envelope_id: str = field(default_factory=lambda: _new_id("re"))
    proposal_hash: str = ""
    data_sensitivity: float | None = None
    execution_risk: float | None = None
    external_side_effect_risk: float | None = None
    financial_risk: float | None = None
    privilege_risk: float | None = None
    availability_risk: float | None = None
    irreversibility: float | None = None
    scope_breadth: float | None = None
    model_uncertainty: float | None = None
    provider_uncertainty: float | None = None
    recovery_difficulty: float | None = None
    privacy_exposure: float | None = None
    locality_change: float | None = None
    credential_impact: float | None = None
    deployment_impact: float | None = None
    evidence_sources: tuple[str, ...] = ()
    unknown_dimensions: tuple[str, ...] = ()
    assessed_at: str = field(default_factory=_utc_now)
    assessed_by: str = "risk_engine"
    aggregate_risk_class: str = "medium"
    max_dimension: str = ""
    max_dimension_value: float = 0.0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id, "proposal_hash": self.proposal_hash,
            "data_sensitivity": self.data_sensitivity,
            "execution_risk": self.execution_risk,
            "external_side_effect_risk": self.external_side_effect_risk,
            "financial_risk": self.financial_risk,
            "privilege_risk": self.privilege_risk,
            "availability_risk": self.availability_risk,
            "irreversibility": self.irreversibility,
            "scope_breadth": self.scope_breadth,
            "model_uncertainty": self.model_uncertainty,
            "provider_uncertainty": self.provider_uncertainty,
            "recovery_difficulty": self.recovery_difficulty,
            "privacy_exposure": self.privacy_exposure,
            "locality_change": self.locality_change,
            "credential_impact": self.credential_impact,
            "deployment_impact": self.deployment_impact,
            "evidence_sources": list(self.evidence_sources),
            "unknown_dimensions": list(self.unknown_dimensions),
            "assessed_at": self.assessed_at, "assessed_by": self.assessed_by,
            "aggregate_risk_class": self.aggregate_risk_class,
            "max_dimension": self.max_dimension,
            "max_dimension_value": self.max_dimension_value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RiskEnvelope":
        return cls(
            envelope_id=d.get("envelope_id", ""),
            proposal_hash=d.get("proposal_hash", ""),
            data_sensitivity=d.get("data_sensitivity"),
            execution_risk=d.get("execution_risk"),
            external_side_effect_risk=d.get("external_side_effect_risk"),
            financial_risk=d.get("financial_risk"),
            privilege_risk=d.get("privilege_risk"),
            availability_risk=d.get("availability_risk"),
            irreversibility=d.get("irreversibility"),
            scope_breadth=d.get("scope_breadth"),
            model_uncertainty=d.get("model_uncertainty"),
            provider_uncertainty=d.get("provider_uncertainty"),
            recovery_difficulty=d.get("recovery_difficulty"),
            privacy_exposure=d.get("privacy_exposure"),
            locality_change=d.get("locality_change"),
            credential_impact=d.get("credential_impact"),
            deployment_impact=d.get("deployment_impact"),
            evidence_sources=tuple(d.get("evidence_sources") or ()),
            unknown_dimensions=tuple(d.get("unknown_dimensions") or ()),
            assessed_at=d.get("assessed_at", ""), assessed_by=d.get("assessed_by", "risk_engine"),
            aggregate_risk_class=d.get("aggregate_risk_class", "medium"),
            max_dimension=d.get("max_dimension", ""),
            max_dimension_value=float(d.get("max_dimension_value", 0.0)),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class AuthorizationDecision:
    """Immutable decision produced by the Execution Authorization Gate."""
    decision_id: str = field(default_factory=lambda: _new_id("ad"))
    proposal_hash: str = ""
    context_id: str = ""
    action_mode: str = "DENY"  # EXECUTE | RECOMMEND | ASK_APPROVAL | ESCALATE | DENY
    allowed: bool = False
    reason_code: str = ""
    reason_message: str = ""
    rule_class: str = ""       # NON_OVERRIDABLE | ADMIN_OVERRIDABLE | USER_APPROVABLE | AUTONOMOUS_ALLOWED
    policy_id: str = ""
    constitution_rule: str = ""
    risk_envelope: RiskEnvelope | None = None
    lease_id: str = ""
    delegation_id: str = ""
    decided_at: str = field(default_factory=_utc_now)
    decision_ttl: int = 60
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id, "proposal_hash": self.proposal_hash,
            "context_id": self.context_id, "action_mode": self.action_mode,
            "allowed": self.allowed, "reason_code": self.reason_code,
            "reason_message": self.reason_message, "rule_class": self.rule_class,
            "policy_id": self.policy_id, "constitution_rule": self.constitution_rule,
            "risk_envelope": self.risk_envelope.to_dict() if self.risk_envelope else None,
            "lease_id": self.lease_id, "delegation_id": self.delegation_id,
            "decided_at": self.decided_at, "decision_ttl": self.decision_ttl,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuthorizationDecision":
        re_dict = d.get("risk_envelope")
        return cls(
            decision_id=d.get("decision_id", ""),
            proposal_hash=d.get("proposal_hash", ""),
            context_id=d.get("context_id", ""),
            action_mode=d.get("action_mode", "DENY"),
            allowed=bool(d.get("allowed", False)),
            reason_code=d.get("reason_code", ""),
            reason_message=d.get("reason_message", ""),
            rule_class=d.get("rule_class", ""),
            policy_id=d.get("policy_id", ""),
            constitution_rule=d.get("constitution_rule", ""),
            risk_envelope=RiskEnvelope.from_dict(re_dict) if re_dict else None,
            lease_id=d.get("lease_id", ""),
            delegation_id=d.get("delegation_id", ""),
            decided_at=d.get("decided_at", ""),
            decision_ttl=int(d.get("decision_ttl", 60)),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ApprovalRequest:
    """Request for human approval of an ActionProposal."""
    request_id: str = field(default_factory=lambda: _new_id("apr"))
    proposal_hash: str = ""
    summary: str = ""
    risk_summary: str = ""
    scope_summary: str = ""
    status: str = "CREATED"  # CREATED → PENDING → APPROVED | DENIED | MODIFIED | EXPIRED | CANCELLED | SUPERSEDED
    requested_by: str = ""
    requested_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    priority: str = "normal"
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "proposal_hash": self.proposal_hash,
            "summary": self.summary, "risk_summary": self.risk_summary,
            "scope_summary": self.scope_summary, "status": self.status,
            "requested_by": self.requested_by, "requested_at": self.requested_at,
            "expires_at": self.expires_at, "priority": self.priority,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ApprovalRequest":
        return cls(
            request_id=d.get("request_id", ""), proposal_hash=d.get("proposal_hash", ""),
            summary=d.get("summary", ""), risk_summary=d.get("risk_summary", ""),
            scope_summary=d.get("scope_summary", ""), status=d.get("status", "CREATED"),
            requested_by=d.get("requested_by", ""), requested_at=d.get("requested_at", ""),
            expires_at=d.get("expires_at", ""), priority=d.get("priority", "normal"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ApprovalResponse:
    """Human response to an ApprovalRequest."""
    response_id: str = field(default_factory=lambda: _new_id("aprsp"))
    request_id: str = ""
    proposal_hash: str = ""
    decision: str = ""           # APPROVED | DENIED | MODIFIED
    scope: ApprovalScope | None = None
    approver_id: str = ""
    approver_method: str = "cli"
    reason: str = ""
    responded_at: str = field(default_factory=_utc_now)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id, "request_id": self.request_id,
            "proposal_hash": self.proposal_hash, "decision": self.decision,
            "scope": self.scope.to_dict() if self.scope else None,
            "approver_id": self.approver_id, "approver_method": self.approver_method,
            "reason": self.reason, "responded_at": self.responded_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ApprovalResponse":
        scope_dict = d.get("scope")
        return cls(
            response_id=d.get("response_id", ""), request_id=d.get("request_id", ""),
            proposal_hash=d.get("proposal_hash", ""), decision=d.get("decision", ""),
            scope=ApprovalScope.from_dict(scope_dict) if scope_dict else None,
            approver_id=d.get("approver_id", ""),
            approver_method=d.get("approver_method", "cli"),
            reason=d.get("reason", ""), responded_at=d.get("responded_at", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class AuthorizationLease:
    """Mutable lease issued after approval, consumed by execution."""
    lease_id: str = field(default_factory=lambda: _new_id("al"))
    proposal_hash: str = ""
    approval_id: str = ""
    subject_id: str = ""
    scope: ApprovalScope | None = None
    max_uses: int = 1
    remaining_uses: int = 1
    issued_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    status: str = "ACTIVE"  # ACTIVE | EXHAUSTED | EXPIRED | REVOKED | INVALIDATED
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id, "proposal_hash": self.proposal_hash,
            "approval_id": self.approval_id, "subject_id": self.subject_id,
            "scope": self.scope.to_dict() if self.scope else None,
            "max_uses": self.max_uses, "remaining_uses": self.remaining_uses,
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "status": self.status, "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuthorizationLease":
        scope_dict = d.get("scope")
        return cls(
            lease_id=d.get("lease_id", ""), proposal_hash=d.get("proposal_hash", ""),
            approval_id=d.get("approval_id", ""), subject_id=d.get("subject_id", ""),
            scope=ApprovalScope.from_dict(scope_dict) if scope_dict else None,
            max_uses=int(d.get("max_uses", 1)),
            remaining_uses=int(d.get("remaining_uses", 1)),
            issued_at=d.get("issued_at", ""), expires_at=d.get("expires_at", ""),
            status=d.get("status", "ACTIVE"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class DelegationConstraint:
    """A single constraint on a delegation."""
    constraint_type: str = ""    # "budget" | "time" | "node" | "workspace" | "cost" | "token"
    operator: str = "lte"
    value: Any = None
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_type": self.constraint_type, "operator": self.operator,
            "value": self.value, "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DelegationConstraint":
        return cls(
            constraint_type=d.get("constraint_type", ""),
            operator=d.get("operator", "lte"),
            value=d.get("value"), unit=d.get("unit", ""),
        )


@dataclass(frozen=True)
class DelegationGrant:
    """Immutable delegation from a principal to a delegate."""
    grant_id: str = field(default_factory=lambda: _new_id("dg"))
    issuer_id: str = ""
    subject_id: str = ""
    scope: ApprovalScope | None = None
    permitted_capabilities: tuple[str, ...] = ()
    denied_capabilities: tuple[str, ...] = ()
    constraints: tuple[DelegationConstraint, ...] = ()
    max_uses: int = 1
    used_count: int = 0
    issued_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    allow_sub_delegation: bool = False
    max_sub_delegation_depth: int = 0
    status: str = "DRAFT"  # DRAFT | ACTIVE | SUSPENDED | EXPIRED | REVOKED | EXHAUSTED
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id, "issuer_id": self.issuer_id,
            "subject_id": self.subject_id,
            "scope": self.scope.to_dict() if self.scope else None,
            "permitted_capabilities": list(self.permitted_capabilities),
            "denied_capabilities": list(self.denied_capabilities),
            "constraints": [c.to_dict() for c in self.constraints],
            "max_uses": self.max_uses, "used_count": self.used_count,
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "allow_sub_delegation": self.allow_sub_delegation,
            "max_sub_delegation_depth": self.max_sub_delegation_depth,
            "status": self.status, "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DelegationGrant":
        scope_dict = d.get("scope")
        return cls(
            grant_id=d.get("grant_id", ""), issuer_id=d.get("issuer_id", ""),
            subject_id=d.get("subject_id", ""),
            scope=ApprovalScope.from_dict(scope_dict) if scope_dict else None,
            permitted_capabilities=tuple(d.get("permitted_capabilities") or ()),
            denied_capabilities=tuple(d.get("denied_capabilities") or ()),
            constraints=tuple(DelegationConstraint.from_dict(c) for c in (d.get("constraints") or ())),
            max_uses=int(d.get("max_uses", 1)), used_count=int(d.get("used_count", 0)),
            issued_at=d.get("issued_at", ""), expires_at=d.get("expires_at", ""),
            allow_sub_delegation=bool(d.get("allow_sub_delegation", False)),
            max_sub_delegation_depth=int(d.get("max_sub_delegation_depth", 0)),
            status=d.get("status", "DRAFT"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class RevocationRecord:
    """Immutable record of a revocation."""
    revocation_id: str = field(default_factory=lambda: _new_id("rev"))
    target_type: str = ""        # "lease" | "delegation" | "credential"
    target_id: str = ""
    revoked_by: str = ""
    reason: str = ""
    revoked_at: str = field(default_factory=_utc_now)
    cascaded_from: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "revocation_id": self.revocation_id, "target_type": self.target_type,
            "target_id": self.target_id, "revoked_by": self.revoked_by,
            "reason": self.reason, "revoked_at": self.revoked_at,
            "cascaded_from": self.cascaded_from, "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RevocationRecord":
        return cls(
            revocation_id=d.get("revocation_id", ""),
            target_type=d.get("target_type", ""), target_id=d.get("target_id", ""),
            revoked_by=d.get("revoked_by", ""), reason=d.get("reason", ""),
            revoked_at=d.get("revoked_at", ""), cascaded_from=d.get("cascaded_from", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class EscalationRecord:
    """Immutable record of an escalation."""
    escalation_id: str = field(default_factory=lambda: _new_id("esc"))
    proposal_hash: str = ""
    reason_code: str = ""
    reason_message: str = ""
    escalated_at: str = field(default_factory=_utc_now)
    resolved_by: str = ""
    resolution: str = ""
    resolved_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id, "proposal_hash": self.proposal_hash,
            "reason_code": self.reason_code, "reason_message": self.reason_message,
            "escalated_at": self.escalated_at, "resolved_by": self.resolved_by,
            "resolution": self.resolution, "resolved_at": self.resolved_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EscalationRecord":
        return cls(
            escalation_id=d.get("escalation_id", ""),
            proposal_hash=d.get("proposal_hash", ""),
            reason_code=d.get("reason_code", ""),
            reason_message=d.get("reason_message", ""),
            escalated_at=d.get("escalated_at", ""), resolved_by=d.get("resolved_by", ""),
            resolution=d.get("resolution", ""), resolved_at=d.get("resolved_at", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class RiskAssessment:
    """Record of a single risk evaluation."""
    assessment_id: str = field(default_factory=lambda: _new_id("ra"))
    proposal_hash: str = ""
    envelope: RiskEnvelope | None = None
    assessed_at: str = field(default_factory=_utc_now)
    assessed_by: str = "risk_engine"
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id, "proposal_hash": self.proposal_hash,
            "envelope": self.envelope.to_dict() if self.envelope else None,
            "assessed_at": self.assessed_at, "assessed_by": self.assessed_by,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RiskAssessment":
        env_dict = d.get("envelope")
        return cls(
            assessment_id=d.get("assessment_id", ""),
            proposal_hash=d.get("proposal_hash", ""),
            envelope=RiskEnvelope.from_dict(env_dict) if env_dict else None,
            assessed_at=d.get("assessed_at", ""), assessed_by=d.get("assessed_by", "risk_engine"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class AuthorizationEvidenceBundle:
    """Immutable audit evidence for an authorization decision."""
    bundle_id: str = field(default_factory=lambda: _new_id("aeb"))
    decision_id: str = ""
    proposal_hash: str = ""
    event_type: str = "authorization_decision"
    evidence: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=_utc_now)
    previous_audit_hash: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _redact_secrets({
            "bundle_id": self.bundle_id, "decision_id": self.decision_id,
            "proposal_hash": self.proposal_hash, "event_type": self.event_type,
            "evidence": self.evidence, "recorded_at": self.recorded_at,
            "previous_audit_hash": self.previous_audit_hash,
            "schema_version": self.schema_version,
        })

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuthorizationEvidenceBundle":
        return cls(
            bundle_id=d.get("bundle_id", ""), decision_id=d.get("decision_id", ""),
            proposal_hash=d.get("proposal_hash", ""),
            event_type=d.get("event_type", "authorization_decision"),
            evidence=d.get("evidence") or {},
            recorded_at=d.get("recorded_at", ""),
            previous_audit_hash=d.get("previous_audit_hash", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


# Scope Helpers

def _str_subset(a: str, b: str) -> bool:
    """a is subset of b if a is empty or equal to b."""
    return a == "" or a == b


def _tuple_subset(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Every element of a is in b, or a is empty."""
    if not a:
        return True
    if not b:
        return False
    b_set = set(b)
    return all(item in b_set for item in a)


def _path_subset(a: str, b: str) -> bool:
    """a is subset of b when it is equal to b or below b as a path."""
    if not a:
        return True
    if not b:
        return False
    try:
        a_path = Path(a).expanduser().resolve(strict=False)
        b_path = Path(b).expanduser().resolve(strict=False)
        if os.name == "nt":
            a_key = os.path.normcase(str(a_path))
            b_key = os.path.normcase(str(b_path))
            return a_key == b_key or a_key.startswith(b_key.rstrip("\\/") + os.sep)
        return a_path == b_path or b_path in a_path.parents
    except (OSError, RuntimeError, ValueError):
        a_norm = os.path.normcase(os.path.normpath(a))
        b_norm = os.path.normcase(os.path.normpath(b))
        return a_norm == b_norm or a_norm.startswith(b_norm.rstrip("\\/") + os.sep)


def _class_subset(a: str, b: str) -> bool:
    """Data classification subset check."""
    if not a:
        return True
    if not b:
        return False
    order = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    return order.get(a, 99) <= order.get(b, 99)


def _num_subset(a: float | int, b: float | int, op: str) -> bool:
    """Numeric subset check. Lower ceilings are narrower; zero is restrictive."""
    if op == "lte":
        return a <= b
    if op == "gte":
        return a >= b
    return a == b

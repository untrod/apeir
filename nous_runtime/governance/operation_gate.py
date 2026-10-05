"""Operation admission methods of the canonical ExecutionAuthorizationGate."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from nous_runtime.governance.contracts import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalScope,
    AuthorizationContext,
    RevocationRecord,
    _new_id,
    _utc_now,
)
from nous_runtime.governance.operation_contracts import (
    CapabilityGrant,
    GovernanceDecision,
    GovernanceRequest,
    GrantScope,
)
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.governance.constitution import evaluate_constitution
from nous_runtime.governance.contracts import ActionProposal
from nous_runtime.governance.permission import PermissionRequest


class OperationAuthorizationMixin:
    """Extend the gate; reuse its Store, Broker, Capability and audit authorities."""

    def capability_inputs(self, capability_id: str) -> dict:
        contracts = {c.capability_id: c for c in self.operation_contracts.list_all()}
        contract = contracts.get(capability_id)
        if contract is None:
            return {}
        return {
            "risk": contract.risk_level.upper(),
            "side_effect_class": contract.side_effect_class,
            "idempotency": contract.idempotency.value,
            "verification_method": contract.verification_method.value,
            "observation_method": contract.observation_method,
            "required_permissions": list(contract.required_permissions),
        }

    def register_operation(self, request: GovernanceRequest) -> str:
        """Persist immutable bindings before approval or dispatch."""
        if redact_sensitive_data(request.to_dict()) != request.to_dict():
            raise ValueError("Credential material is not an Operation input")
        if not all(
            (
                request.operation_id,
                request.work_id,
                request.subject_id,
                request.capability_id,
                request.resource_id,
            )
        ):
            raise ValueError("Operation governance binding is incomplete")
        if request.operation_id != request.work_id:
            raise ValueError("Operation and Work identity differ")
        with self.store.operation_transaction() as db:
            prior = db.execute(
                "SELECT authorization_id FROM governance_operations "
                "WHERE operation_id=?",
                (request.operation_id,),
            ).fetchone()
            if prior and prior[0] != request.authorization_id:
                raise PermissionError("Operation authorization binding changed")
            db.execute(
                "INSERT OR IGNORE INTO governance_operations VALUES (?, ?, ?)",
                (
                    request.authorization_id,
                    request.operation_id,
                    json.dumps(request.to_dict(), sort_keys=True),
                ),
            )
        return request.authorization_id

    def get_operation_request(self, authorization_id: str) -> GovernanceRequest:
        with self.store.operation_transaction() as db:
            row = db.execute(
                "SELECT request_json FROM governance_operations "
                "WHERE authorization_id=?",
                (authorization_id,),
            ).fetchone()
            if row is None:
                raise PermissionError("Unknown Operation authorization")
            request = GovernanceRequest.from_dict(json.loads(row[0]))
            if request.authorization_id != authorization_id:
                raise PermissionError("Operation authorization was altered")
            return request

    @staticmethod
    def _evidence(request: GovernanceRequest, **extra) -> dict:
        return {
            **request.to_dict(),
            "authorization_id": request.authorization_id,
            **extra,
        }

    @staticmethod
    def _revoked(db, target_id: str) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM governance_revocations WHERE target_id=?", (target_id,)
            ).fetchone()
            is not None
        )

    def _matching_grant(self, db, request: GovernanceRequest, *, admitted=False):
        rows = db.execute(
            "SELECT * FROM governance_leases WHERE subject_id=?", (request.subject_id,)
        ).fetchall()
        for row in rows:
            grant = json.loads(row["lease_json"])
            if not grant.get("operation_governance"):
                continue
            if (
                row["status"]
                not in ({"ACTIVE", "EXHAUSTED"} if admitted else {"ACTIVE"})
                or not row["expires_at"]
                or row["expires_at"] <= _utc_now()
                or self._revoked(db, row["lease_id"])
                or grant.get("capability_id") != request.capability_id
                or (grant.get("node_id") and grant["node_id"] != request.node_id)
            ):
                continue
            scope = grant.get("scope_kind")
            matches = {
                "ONCE": row["proposal_hash"] == request.authorization_id,
                "WORK": grant.get("work_id") == request.work_id,
                "SESSION": bool(request.agent_session_id)
                and grant.get("agent_session_id") == request.agent_session_id,
                "RESOURCE": grant.get("resource_id") == request.resource_id,
                "CAPABILITY": True,
            }.get(scope, False)
            if scope in {"ONCE", "WORK", "SESSION"}:
                matches = matches and grant.get("resource_id") == request.resource_id
            prior = db.execute(
                "SELECT 1 FROM governance_lease_consumption "
                "WHERE lease_id=? AND execution_id=?",
                (row["lease_id"], request.authorization_id),
            ).fetchone()
            if matches and (bool(prior) if admitted else row["remaining_uses"] > 0):
                return row
        return None

    def _evaluate_operation(self, db, request, *, admitted=False):
        current = self.capability_inputs(request.capability_id)
        proposal = ActionProposal(
            action_type="capability.execute",
            capability_id=request.capability_id,
            agent_id=request.subject_id,
            target_work_item=request.work_id,
            affected_resources=(request.resource_id,),
            side_effect_class=current.get("side_effect_class", "unknown"),
        )
        context = AuthorizationContext(
            subject_type="agent", subject_id=request.subject_id
        )
        if evaluate_constitution(proposal, context):
            return GovernanceDecision.DENY, None
        if not current or current.get("risk") not in {
            "LOW",
            "READ_ONLY",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            return GovernanceDecision.DENY, None
        if current != request.capability_inputs:
            return GovernanceDecision.UNKNOWN, None
        required = current["required_permissions"]
        if required and self.permission_engine is None:
            return GovernanceDecision.UNKNOWN, None
        if self.permission_engine is not None:
            for permission in ["capability.execute", *required]:
                if not self.permission_engine.check(
                    PermissionRequest(
                        request.subject_id,
                        permission,
                        request.resource_id,
                        {
                            "subject_type": "agent",
                            "capability_id": request.capability_id,
                        },
                    )
                ).allowed:
                    return GovernanceDecision.DENY, None
        if current["risk"] == "CRITICAL" or current["side_effect_class"] not in {
            "none",
            "read_only",
            "local_write",
            "external_write",
        }:
            return GovernanceDecision.DENY, None
        if self._revoked(db, request.resource_id):
            return GovernanceDecision.DENY, None
        approval = db.execute(
            "SELECT status,expires_at FROM governance_approval_requests WHERE request_id=?",
            ("apr_" + request.authorization_id[4:],),
        ).fetchone()
        if approval and approval[1] <= _utc_now():
            return GovernanceDecision.DENY, None
        if approval and approval[0] in {"DENIED", "EXPIRED", "CANCELLED"}:
            return GovernanceDecision.DENY, None
        policy = self.operation_policy
        if (
            policy
            and policy.capability_id == request.capability_id
            and policy.auto_approve_read_only
            and policy.scope == "policy_controlled"
            and current["risk"] in {"LOW", "READ_ONLY"}
            and current["side_effect_class"] in {"none", "read_only"}
            and current["idempotency"] == "idempotent"
        ):
            return GovernanceDecision.ALLOW, None
        if current["side_effect_class"] not in {"none", "read_only"} and (
            not current["observation_method"]
            or current["verification_method"] == "none"
        ):
            return GovernanceDecision.UNKNOWN, None
        grant = self._matching_grant(db, request, admitted=admitted)
        if approval and approval[0] == "APPROVED" and not grant:
            return GovernanceDecision.DENY, None
        return (
            (GovernanceDecision.ALLOW, grant)
            if grant
            else (GovernanceDecision.REQUIRE_APPROVAL, None)
        )

    def evaluate_operation(self, authorization_id: str) -> GovernanceDecision:
        try:
            request = self.get_operation_request(authorization_id)
            with self.store.operation_transaction() as db:
                verdict, grant = self._evaluate_operation(db, request)
                evidence = self._evidence(
                    request,
                    verdict=verdict.value,
                    grant_id=grant["lease_id"] if grant else "",
                    policy_id=self.operation_policy.policy_id
                    if self.operation_policy
                    else "",
                )
                self.store.append_operation_audit(db, "policy.evaluated", evidence)
                self.store.append_operation_audit(db, "authorization.decided", evidence)
                return verdict
        except (
            OSError,
            ValueError,
            RuntimeError,
            TypeError,
            AttributeError,
            KeyError,
            sqlite3.Error,
        ):
            return GovernanceDecision.UNKNOWN

    def _require_human(self, context: AuthorizationContext, request: GovernanceRequest):
        from nous_runtime.governance.cli import _build_context, _is_local_owner_context
        from nous_runtime.governance.permission import PermissionRequest

        owner = _build_context()
        valid = (
            _is_local_owner_context(context)
            and context.subject_type == "user"
            and context.subject_id != request.subject_id
            and context.subject_id == owner.subject_id
            and context.authn_method == "cli_os_user"
            and context.authn_confidence >= 0.8
            and context.session_locality == "local"
        )
        if self.permission_engine is not None:
            valid = (
                valid
                and self.permission_engine.check(
                    PermissionRequest(
                        context.subject_id,
                        "governance.approve",
                        request.resource_id,
                        {"subject_type": context.subject_type},
                    )
                ).allowed
            )
        if not valid:
            with self.store.operation_transaction() as db:
                self.store.append_operation_audit(
                    db,
                    "authority.rejected",
                    self._evidence(
                        request,
                        actor_id=context.subject_id,
                        actor_type=context.subject_type,
                        authorization_context_id=context.context_id,
                    ),
                )
            raise PermissionError(
                "Only the authenticated local human owner can grant authority"
            )

    def _request_operation_approval(self, authorization_id: str) -> ApprovalRequest:
        request = self.get_operation_request(authorization_id)
        approval_id = "apr_" + authorization_id[4:]
        with self.store.operation_transaction() as db:
            prior = db.execute(
                "SELECT request_json FROM governance_approval_requests "
                "WHERE request_id=?",
                (approval_id,),
            ).fetchone()
            if prior:
                return ApprovalRequest.from_dict(json.loads(prior[0]))
            approval = ApprovalRequest(
                request_id=approval_id,
                proposal_hash=authorization_id,
                summary=f"{request.capability_id}: {request.resource_id}",
                risk_summary=request.capability_inputs.get("risk", "UNKNOWN"),
                scope_summary="Approve Once for the exact original Operation",
                status="PENDING",
                requested_by=request.subject_id,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            )
            value = {
                **approval.to_dict(),
                "operation_governance": True,
                "governance_request_id": authorization_id,
                "run_id": request.workflow_run_id,
                "task_id": request.work_id,
                "bindings": self._evidence(request),
            }
            db.execute(
                "INSERT INTO governance_approval_requests "
                "(request_id,proposal_hash,status,requested_by,expires_at,requested_at,request_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    approval_id,
                    authorization_id,
                    "PENDING",
                    request.subject_id,
                    approval.expires_at,
                    approval.requested_at,
                    json.dumps(value),
                ),
            )
            self.store.append_operation_audit(
                db,
                "approval.requested",
                self._evidence(request, approval_id=approval_id),
            )
            return approval

    @staticmethod
    def _insert_grant(db, grant):
        value = grant.to_dict()
        db.execute(
            "INSERT INTO governance_leases "
            "(lease_id,proposal_hash,approval_id,subject_id,scope_json,max_uses,remaining_uses,issued_at,expires_at,status,lease_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                grant.lease_id,
                grant.proposal_hash,
                grant.approval_id,
                grant.subject_id,
                json.dumps(value["scope"]),
                grant.max_uses,
                grant.remaining_uses,
                grant.issued_at,
                grant.expires_at,
                grant.status,
                json.dumps(value),
            ),
        )

    def issue_operation_grant(
        self,
        authorization_id,
        context,
        *,
        scope=GrantScope.ONCE,
        max_uses=1,
        validity_seconds=3600,
    ):
        request = self.get_operation_request(authorization_id)
        self._require_human(context, request)
        scope = GrantScope(scope)
        if not 0 < validity_seconds <= 86400 or not 0 < max_uses <= 1000:
            raise ValueError("Grant duration and uses must be explicitly bounded")
        if scope is GrantScope.ONCE and max_uses != 1:
            raise ValueError("ONCE grants have exactly one use")
        grant = CapabilityGrant(
            proposal_hash=authorization_id,
            subject_id=request.subject_id,
            scope=ApprovalScope(
                proposal_hash=authorization_id, capability_id=request.capability_id
            ),
            scope_kind=scope.value,
            capability_id=request.capability_id,
            resource_id=request.resource_id,
            work_id=request.work_id,
            agent_session_id=request.agent_session_id,
            node_id=request.node_id,
            authorized_by=context.subject_id,
            max_uses=max_uses,
            remaining_uses=max_uses,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=validity_seconds)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        with self.store.operation_transaction() as db:
            if self._revoked(db, request.resource_id):
                raise PermissionError("Resource remains revoked")
            self._insert_grant(db, grant)
            self.store.append_operation_audit(
                db,
                "grant.issued",
                self._evidence(
                    request,
                    grant_id=grant.lease_id,
                    scope=scope.value,
                    actor_id=context.subject_id,
                    authorization_context_id=context.context_id,
                ),
            )
        return grant

    def _respond_operation_approval(self, request_id, context, *, approve):
        record = self.store.get_approval_request(request_id)
        if not record or not record.get("operation_governance"):
            raise ValueError("Not an Operation approval request")
        request = self.get_operation_request(record["governance_request_id"])
        self._require_human(context, request)
        response = ApprovalResponse(
            request_id=request_id,
            proposal_hash=request.authorization_id,
            decision="APPROVED" if approve else "DENIED",
            approver_id=context.subject_id,
            approver_method=context.authn_method,
            scope=ApprovalScope(proposal_hash=request.authorization_id, max_uses=1),
        )
        with self.store.operation_transaction() as db:
            row = db.execute(
                "SELECT status,expires_at FROM governance_approval_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row[0] != "PENDING" or row[1] <= _utc_now():
                raise PermissionError("Approval is no longer pending or has expired")
            if self._revoked(db, request.resource_id):
                raise PermissionError("Resource remains revoked")
            grant = CapabilityGrant(
                proposal_hash=request.authorization_id,
                approval_id=response.response_id,
                subject_id=request.subject_id,
                scope=response.scope,
                capability_id=request.capability_id,
                resource_id=request.resource_id,
                work_id=request.work_id,
                agent_session_id=request.agent_session_id,
                node_id=request.node_id,
                authorized_by=context.subject_id,
                expires_at=row[1],
            )
            if approve:
                self._insert_grant(db, grant)
                self.store.append_operation_audit(
                    db,
                    "grant.issued",
                    self._evidence(
                        request,
                        grant_id=grant.lease_id,
                        scope="ONCE",
                        actor_id=context.subject_id,
                        authorization_context_id=context.context_id,
                    ),
                )
            record["status"] = response.decision
            db.execute(
                "UPDATE governance_approval_requests SET status=?,request_json=? WHERE request_id=?",
                (response.decision, json.dumps(record), request_id),
            )
            db.execute(
                "INSERT INTO governance_approval_responses "
                "(response_id,request_id,proposal_hash,decision,approver_id,response_json) VALUES(?,?,?,?,?,?)",
                (
                    response.response_id,
                    request_id,
                    request.authorization_id,
                    response.decision,
                    context.subject_id,
                    json.dumps(response.to_dict()),
                ),
            )
            self.store.append_operation_audit(
                db,
                "approval.decided",
                self._evidence(
                    request,
                    approval_id=request_id,
                    decision=response.decision,
                    actor_id=context.subject_id,
                    authorization_context_id=context.context_id,
                ),
            )
        return response

    def revoke_operation_authority(
        self, authorization_id, context, *, grant_id="", resource=False
    ):
        request = self.get_operation_request(authorization_id)
        self._require_human(context, request)
        target = request.resource_id if resource else grant_id
        if not target:
            raise ValueError("Revocation target required")
        revocation = RevocationRecord(
            target_type="resource" if resource else "lease",
            target_id=target,
            revoked_by=context.subject_id,
        )
        with self.store.operation_transaction() as db:
            if not resource:
                db.execute(
                    "UPDATE governance_leases SET status='REVOKED' WHERE lease_id=?",
                    (target,),
                )
            db.execute(
                "INSERT INTO governance_revocations (revocation_id,target_type,target_id,revoked_by,revocation_json) VALUES(?,?,?,?,?)",
                (
                    revocation.revocation_id,
                    revocation.target_type,
                    target,
                    context.subject_id,
                    json.dumps(revocation.to_dict()),
                ),
            )
            self.store.append_operation_audit(
                db,
                "resource.revoked" if resource else "grant.revoked",
                self._evidence(
                    request,
                    target_id=target,
                    actor_id=context.subject_id,
                    authorization_context_id=context.context_id,
                ),
            )

    def record_operation_evidence(self, authorization_id, event_type, **evidence):
        request = self.get_operation_request(authorization_id)
        with self.store.operation_transaction() as db:
            self.store.append_operation_audit(
                db, event_type, self._evidence(request, **evidence)
            )

    @contextmanager
    def admit_operation(self, authorization_id, *, resource_check):
        """Revalidate at the effect boundary; reserve one use before execution.

        The existing Node EXECUTING journal is persisted before this call.
        A second write transaction serializes effect admission with revocation.
        A crash never licenses replay of an incomplete Node journal.
        """
        request = self.get_operation_request(authorization_id)
        with self.store.operation_transaction() as db:
            verdict, grant = self._evaluate_operation(db, request)
            prior_admission = db.execute(
                "SELECT 1 FROM governance_lease_consumption WHERE execution_id=?",
                (authorization_id,),
            ).fetchone()
            if prior_admission:
                raise PermissionError("An admitted Operation cannot execute again")
            if verdict is not GovernanceDecision.ALLOW or not resource_check():
                self.store.append_operation_audit(
                    db,
                    "execution.denied",
                    self._evidence(request, verdict=verdict.value),
                )
                db.commit()
                raise PermissionError("Operation execution is not authorized")
            if grant:
                grant_id = grant["lease_id"]
                prior = db.execute(
                    "SELECT 1 FROM governance_lease_consumption WHERE lease_id=? AND execution_id=?",
                    (grant_id, authorization_id),
                ).fetchone()
                if prior:
                    raise PermissionError("An admitted Operation cannot execute again")
                remaining = grant["remaining_uses"] - 1
                grant_value = json.loads(grant["lease_json"])
                grant_value.update(
                    remaining_uses=remaining,
                    status="ACTIVE" if remaining else "EXHAUSTED",
                )
                db.execute(
                    "UPDATE governance_leases SET remaining_uses=?,status=?,lease_json=? WHERE lease_id=?",
                    (
                        remaining,
                        grant_value["status"],
                        json.dumps(grant_value),
                        grant_id,
                    ),
                )
                db.execute(
                    "INSERT INTO governance_lease_consumption VALUES(?,?,?,?,?)",
                    (_new_id("use"), grant_id, authorization_id, _utc_now(), remaining),
                )
            self.store.append_operation_audit(
                db,
                "execution.admitted",
                self._evidence(request, grant_id=grant["lease_id"] if grant else ""),
            )
            db.commit()
            db.execute("BEGIN IMMEDIATE")

            def revalidate():
                verdict, _ = self._evaluate_operation(db, request, admitted=True)
                if verdict is not GovernanceDecision.ALLOW or not resource_check():
                    self.store.append_operation_audit(
                        db,
                        "execution.denied",
                        self._evidence(
                            request, verdict=verdict.value, phase="before_effect"
                        ),
                    )
                    db.commit()
                    raise PermissionError(
                        "Authorization changed immediately before effect"
                    )

            revalidate()
            yield revalidate

# -*- coding: utf-8 -*-
"""GovernanceStore — SQLite persistence for all B1 governance state."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.governance.store")



@contextmanager
def _db_connect(db_path: str, readonly: bool = False):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


class GovernanceStore:
    """SQLite-backed store for governance records.

    Per-workspace store at .nous/governance.db.
    """

    def __init__(self, workspace_path: str | Path = ""):
        if workspace_path:
            self.db_path = str(Path(workspace_path) / "governance.db")
        else:
            self.db_path = str(Path(os.getcwd()) / ".nous" / "governance.db")
        self._lock = threading.RLock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.executescript("""
                        CREATE TABLE IF NOT EXISTS governance_proposals (
                            proposal_id TEXT PRIMARY KEY,
                            proposal_hash TEXT NOT NULL UNIQUE,
                            action_type TEXT NOT NULL DEFAULT '',
                            capability_id TEXT NOT NULL DEFAULT '',
                            parameter_hash TEXT NOT NULL DEFAULT '',
                            parameter_summary TEXT NOT NULL DEFAULT '',
                            target_node TEXT NOT NULL DEFAULT '',
                            target_workspace TEXT NOT NULL DEFAULT '',
                            data_classification TEXT NOT NULL DEFAULT 'internal',
                            side_effect_class TEXT NOT NULL DEFAULT 'unknown',
                            reversibility TEXT NOT NULL DEFAULT 'unknown',
                            created_at TEXT NOT NULL DEFAULT '',
                            expires_at TEXT NOT NULL DEFAULT '',
                            proposal_json TEXT NOT NULL DEFAULT '{}'
                        );
                        CREATE INDEX IF NOT EXISTS idx_proposals_hash ON governance_proposals(proposal_hash);

                        CREATE TABLE IF NOT EXISTS governance_decisions (
                            decision_id TEXT PRIMARY KEY,
                            proposal_hash TEXT NOT NULL,
                            context_id TEXT NOT NULL DEFAULT '',
                            action_mode TEXT NOT NULL DEFAULT 'DENY',
                            allowed INTEGER NOT NULL DEFAULT 0,
                            reason_code TEXT NOT NULL DEFAULT '',
                            reason_message TEXT NOT NULL DEFAULT '',
                            rule_class TEXT NOT NULL DEFAULT '',
                            policy_id TEXT NOT NULL DEFAULT '',
                            constitution_rule TEXT NOT NULL DEFAULT '',
                            risk_json TEXT,
                            lease_id TEXT NOT NULL DEFAULT '',
                            delegation_id TEXT NOT NULL DEFAULT '',
                            decided_at TEXT NOT NULL DEFAULT '',
                            decision_ttl INTEGER NOT NULL DEFAULT 60,
                            decision_json TEXT NOT NULL DEFAULT '{}'
                        );
                        CREATE INDEX IF NOT EXISTS idx_decisions_lease ON governance_decisions(lease_id);

                        CREATE TABLE IF NOT EXISTS governance_approval_requests (
                            request_id TEXT PRIMARY KEY,
                            proposal_hash TEXT NOT NULL,
                            summary TEXT NOT NULL DEFAULT '',
                            risk_summary TEXT NOT NULL DEFAULT '',
                            scope_summary TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT 'CREATED',
                            requested_by TEXT NOT NULL DEFAULT '',
                            requested_at TEXT NOT NULL DEFAULT '',
                            expires_at TEXT NOT NULL DEFAULT '',
                            priority TEXT NOT NULL DEFAULT 'normal',
                            request_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS governance_approval_responses (
                            response_id TEXT PRIMARY KEY,
                            request_id TEXT NOT NULL,
                            proposal_hash TEXT NOT NULL,
                            decision TEXT NOT NULL DEFAULT '',
                            scope_json TEXT,
                            approver_id TEXT NOT NULL DEFAULT '',
                            approver_method TEXT NOT NULL DEFAULT 'cli',
                            reason TEXT NOT NULL DEFAULT '',
                            responded_at TEXT NOT NULL DEFAULT '',
                            response_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS governance_leases (
                            lease_id TEXT PRIMARY KEY,
                            proposal_hash TEXT NOT NULL,
                            approval_id TEXT NOT NULL DEFAULT '',
                            subject_id TEXT NOT NULL DEFAULT '',
                            scope_json TEXT,
                            max_uses INTEGER NOT NULL DEFAULT 1,
                            remaining_uses INTEGER NOT NULL DEFAULT 1,
                            issued_at TEXT NOT NULL DEFAULT '',
                            expires_at TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT 'ACTIVE',
                            lease_json TEXT NOT NULL DEFAULT '{}'
                        );
                        CREATE INDEX IF NOT EXISTS idx_leases_subject ON governance_leases(subject_id, status);
                        CREATE INDEX IF NOT EXISTS idx_leases_proposal ON governance_leases(proposal_hash, status);

                        CREATE TABLE IF NOT EXISTS governance_lease_consumption (
                            log_id TEXT PRIMARY KEY,
                            lease_id TEXT NOT NULL,
                            execution_id TEXT NOT NULL,
                            consumed_at TEXT NOT NULL DEFAULT '',
                            remaining_after INTEGER NOT NULL DEFAULT 0
                        );
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_consumption_dedup
                            ON governance_lease_consumption(lease_id, execution_id);

                        CREATE TABLE IF NOT EXISTS governance_delegations (
                            grant_id TEXT PRIMARY KEY,
                            issuer_id TEXT NOT NULL DEFAULT '',
                            subject_id TEXT NOT NULL DEFAULT '',
                            scope_json TEXT,
                            permitted_capabilities_json TEXT NOT NULL DEFAULT '[]',
                            denied_capabilities_json TEXT NOT NULL DEFAULT '[]',
                            constraints_json TEXT NOT NULL DEFAULT '[]',
                            max_uses INTEGER NOT NULL DEFAULT 1,
                            used_count INTEGER NOT NULL DEFAULT 0,
                            issued_at TEXT NOT NULL DEFAULT '',
                            expires_at TEXT NOT NULL DEFAULT '',
                            allow_sub_delegation INTEGER NOT NULL DEFAULT 0,
                            status TEXT NOT NULL DEFAULT 'DRAFT',
                            grant_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS governance_revocations (
                            revocation_id TEXT PRIMARY KEY,
                            target_type TEXT NOT NULL DEFAULT '',
                            target_id TEXT NOT NULL,
                            revoked_by TEXT NOT NULL DEFAULT '',
                            reason TEXT NOT NULL DEFAULT '',
                            revoked_at TEXT NOT NULL DEFAULT '',
                            cascaded_from TEXT NOT NULL DEFAULT '',
                            revocation_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS governance_escalations (
                            escalation_id TEXT PRIMARY KEY,
                            proposal_hash TEXT NOT NULL DEFAULT '',
                            reason_code TEXT NOT NULL DEFAULT '',
                            reason_message TEXT NOT NULL DEFAULT '',
                            escalated_at TEXT NOT NULL DEFAULT '',
                            resolved_by TEXT NOT NULL DEFAULT '',
                            resolution TEXT NOT NULL DEFAULT '',
                            resolved_at TEXT NOT NULL DEFAULT '',
                            escalation_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS governance_audit (
                            audit_id TEXT PRIMARY KEY,
                            event_type TEXT NOT NULL DEFAULT '',
                            decision_id TEXT NOT NULL DEFAULT '',
                            proposal_hash TEXT NOT NULL DEFAULT '',
                            evidence_json TEXT NOT NULL DEFAULT '{}',
                            recorded_at TEXT NOT NULL DEFAULT '',
                            previous_audit_hash TEXT NOT NULL DEFAULT ''
                        );
                    """)
            except Exception as e:
                _log.warning("Failed to create governance tables: %s", e)

    # Proposal

    def save_proposal(self, proposal_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR IGNORE INTO governance_proposals
                           (proposal_id, proposal_hash, action_type, capability_id,
                            parameter_hash, parameter_summary, target_node,
                            target_workspace, data_classification, side_effect_class,
                            reversibility, created_at, expires_at, proposal_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (proposal_dict["proposal_id"], proposal_dict["proposal_hash"],
                         proposal_dict.get("action_type", ""),
                         proposal_dict.get("capability_id", ""),
                         proposal_dict.get("parameter_hash", ""),
                         proposal_dict.get("parameter_summary", ""),
                         proposal_dict.get("target_node", ""),
                         proposal_dict.get("target_workspace", ""),
                         proposal_dict.get("data_classification", "internal"),
                         proposal_dict.get("side_effect_class", "unknown"),
                         proposal_dict.get("reversibility", "unknown"),
                         proposal_dict.get("created_at", ""),
                         proposal_dict.get("expires_at", ""),
                         json.dumps(proposal_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_proposal: %s", e)
                return False

    def get_proposal(self, proposal_hash: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT proposal_json FROM governance_proposals WHERE proposal_hash = ?",
                        (proposal_hash,),
                    ).fetchone()
                    if row:
                        return json.loads(row[0])
            except Exception:
                pass
        return None

    # Decision

    def save_decision(self, decision_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR IGNORE INTO governance_decisions
                           (decision_id, proposal_hash, context_id, action_mode, allowed,
                            reason_code, reason_message, rule_class, policy_id,
                            constitution_rule, risk_json, lease_id, delegation_id,
                            decided_at, decision_ttl, decision_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (decision_dict["decision_id"], decision_dict["proposal_hash"],
                         decision_dict.get("context_id", ""),
                         decision_dict.get("action_mode", "DENY"),
                         int(decision_dict.get("allowed", False)),
                         decision_dict.get("reason_code", ""),
                         decision_dict.get("reason_message", ""),
                         decision_dict.get("rule_class", ""),
                         decision_dict.get("policy_id", ""),
                         decision_dict.get("constitution_rule", ""),
                         json.dumps(decision_dict.get("risk_envelope")),
                         decision_dict.get("lease_id", ""),
                         decision_dict.get("delegation_id", ""),
                         decision_dict.get("decided_at", ""),
                         int(decision_dict.get("decision_ttl", 60)),
                         json.dumps(decision_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_decision: %s", e)
                return False

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT decision_json FROM governance_decisions WHERE decision_id = ?",
                        (decision_id,),
                    ).fetchone()
                    if row:
                        return json.loads(row[0])
            except Exception:
                pass
        return None

    # Approval Requests

    def save_approval_request(self, request_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO governance_approval_requests
                           (request_id, proposal_hash, summary, risk_summary,
                            scope_summary, status, requested_by, requested_at,
                            expires_at, priority, request_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (request_dict["request_id"], request_dict["proposal_hash"],
                         request_dict.get("summary", ""),
                         request_dict.get("risk_summary", ""),
                         request_dict.get("scope_summary", ""),
                         request_dict.get("status", "CREATED"),
                         request_dict.get("requested_by", ""),
                         request_dict.get("requested_at", ""),
                         request_dict.get("expires_at", ""),
                         request_dict.get("priority", "normal"),
                         json.dumps(request_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_approval_request: %s", e)
                return False

    def get_approval_request(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT status, request_json FROM governance_approval_requests WHERE request_id = ?",
                        (request_id,),
                    ).fetchone()
                    if row:
                        data = json.loads(row["request_json"])
                        data["status"] = row["status"]
                        return data
            except Exception:
                pass
        return None

    def update_approval_status(self, request_id: str, status: str) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        "UPDATE governance_approval_requests SET status = ? WHERE request_id = ?",
                        (status, request_id),
                    )
                return True
            except Exception:
                return False

    def expire_approval(self, request_id: str) -> bool:
        """Atomically expire one still-pending approval request."""
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    updated = db.execute(
                        "UPDATE governance_approval_requests SET status = 'EXPIRED' "
                        "WHERE request_id = ? AND status = 'PENDING'",
                        (request_id,),
                    )
                    return updated.rowcount == 1
            except Exception:
                return False

    def resolve_approval(
        self,
        request_id: str,
        *,
        expected_status: str,
        new_status: str,
        response_dict: dict[str, Any],
        lease_dict: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically record one terminal response and optional authorization lease."""
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute("BEGIN IMMEDIATE")
                    updated = db.execute(
                        "UPDATE governance_approval_requests SET status = ? "
                        "WHERE request_id = ? AND status = ?",
                        (new_status, request_id, expected_status),
                    )
                    if updated.rowcount != 1:
                        db.execute("ROLLBACK")
                        return False
                    db.execute(
                        """INSERT INTO governance_approval_responses
                           (response_id, request_id, proposal_hash, decision,
                            scope_json, approver_id, approver_method, reason,
                            responded_at, response_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            response_dict["response_id"],
                            response_dict["request_id"],
                            response_dict["proposal_hash"],
                            response_dict["decision"],
                            json.dumps(response_dict.get("scope")),
                            response_dict.get("approver_id", ""),
                            response_dict.get("approver_method", "cli"),
                            response_dict.get("reason", ""),
                            response_dict.get("responded_at", ""),
                            json.dumps(response_dict),
                        ),
                    )
                    if lease_dict is not None:
                        db.execute(
                            """INSERT INTO governance_leases
                               (lease_id, proposal_hash, approval_id, subject_id,
                                scope_json, max_uses, remaining_uses, issued_at,
                                expires_at, status, lease_json)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                lease_dict["lease_id"],
                                lease_dict["proposal_hash"],
                                lease_dict.get("approval_id", ""),
                                lease_dict.get("subject_id", ""),
                                json.dumps(lease_dict.get("scope")),
                                int(lease_dict.get("max_uses", 1)),
                                int(lease_dict.get("remaining_uses", 1)),
                                lease_dict.get("issued_at", ""),
                                lease_dict.get("expires_at", ""),
                                lease_dict.get("status", "ACTIVE"),
                                json.dumps(lease_dict),
                            ),
                        )
                    db.execute("COMMIT")
                return True
            except Exception as e:
                _log.warning("resolve_approval: %s", e)
                return False

    def list_pending_approvals(self, subject_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    if subject_id:
                        rows = db.execute(
                            "SELECT request_json FROM governance_approval_requests "
                            "WHERE status = 'PENDING' AND requested_by = ? ORDER BY requested_at DESC",
                            (subject_id,),
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT request_json FROM governance_approval_requests "
                            "WHERE status = 'PENDING' ORDER BY requested_at DESC"
                        ).fetchall()
                    return [json.loads(r[0]) for r in rows]
            except Exception:
                return []

    # Approval Responses

    def save_approval_response(self, response_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR IGNORE INTO governance_approval_responses
                           (response_id, request_id, proposal_hash, decision,
                            scope_json, approver_id, approver_method, reason,
                            responded_at, response_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (response_dict["response_id"], response_dict["request_id"],
                         response_dict["proposal_hash"], response_dict["decision"],
                         json.dumps(response_dict.get("scope")),
                         response_dict.get("approver_id", ""),
                         response_dict.get("approver_method", "cli"),
                         response_dict.get("reason", ""),
                         response_dict.get("responded_at", ""),
                         json.dumps(response_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_approval_response: %s", e)
                return False

    # Leases

    def save_lease(self, lease_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO governance_leases
                           (lease_id, proposal_hash, approval_id, subject_id,
                            scope_json, max_uses, remaining_uses, issued_at,
                            expires_at, status, lease_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (lease_dict["lease_id"], lease_dict["proposal_hash"],
                         lease_dict.get("approval_id", ""),
                         lease_dict.get("subject_id", ""),
                         json.dumps(lease_dict.get("scope")),
                         int(lease_dict.get("max_uses", 1)),
                         int(lease_dict.get("remaining_uses", 1)),
                         lease_dict.get("issued_at", ""),
                         lease_dict.get("expires_at", ""),
                         lease_dict.get("status", "ACTIVE"),
                         json.dumps(lease_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_lease: %s", e)
                return False

    def get_lease(self, lease_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT remaining_uses, status, lease_json FROM governance_leases WHERE lease_id = ?",
                        (lease_id,),
                    ).fetchone()
                    if row:
                        data = json.loads(row["lease_json"])
                        data["remaining_uses"] = row["remaining_uses"]
                        data["status"] = row["status"]
                        return data
            except Exception:
                pass
        return None

    def get_active_lease_for_proposal(self, proposal_hash: str, subject_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT remaining_uses, status, lease_json FROM governance_leases "
                        "WHERE proposal_hash = ? AND subject_id = ? AND status = 'ACTIVE' "
                        "AND remaining_uses > 0 LIMIT 1",
                        (proposal_hash, subject_id),
                    ).fetchone()
                    if row:
                        data = json.loads(row["lease_json"])
                        data["remaining_uses"] = row["remaining_uses"]
                        data["status"] = row["status"]
                        return data
            except Exception:
                pass
        return None

    def consume_lease(self, lease_id: str, execution_id: str) -> tuple[bool, int]:
        """Atomically consume one lease use. Returns (success, remaining_after)."""
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute("BEGIN IMMEDIATE")
                    prior = db.execute(
                        "SELECT remaining_after FROM governance_lease_consumption "
                        "WHERE lease_id = ? AND execution_id = ?",
                        (lease_id, execution_id),
                    ).fetchone()
                    if prior:
                        db.execute("COMMIT")
                        return True, int(prior["remaining_after"])

                    row = db.execute(
                        "SELECT remaining_uses, status, expires_at FROM governance_leases WHERE lease_id = ?",
                        (lease_id,),
                    ).fetchone()
                    if not row:
                        db.execute("ROLLBACK")
                        return False, 0
                    remaining, status, expires_at = row
                    if status != "ACTIVE" or remaining <= 0:
                        db.execute("ROLLBACK")
                        return False, remaining

                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if expires_at and expires_at <= now:
                        db.execute(
                            "UPDATE governance_leases SET status = 'EXPIRED' WHERE lease_id = ?",
                            (lease_id,),
                        )
                        db.execute("COMMIT")
                        return False, remaining

                    new_remaining = remaining - 1
                    new_status = "EXHAUSTED" if new_remaining == 0 else "ACTIVE"
                    db.execute(
                        "UPDATE governance_leases SET remaining_uses = ?, status = ? WHERE lease_id = ?",
                        (new_remaining, new_status, lease_id),
                    )
                    import uuid as _uuid
                    log_id = f"lcl_{_uuid.uuid4().hex[:12]}"
                    db.execute(
                        "INSERT OR IGNORE INTO governance_lease_consumption "
                        "(log_id, lease_id, execution_id, consumed_at, remaining_after) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (log_id, lease_id, execution_id, now, new_remaining),
                    )
                    db.execute("COMMIT")
                    return True, new_remaining
            except Exception as e:
                _log.warning("consume_lease: %s", e)
                try:
                    db.execute("ROLLBACK")
                except Exception:
                    pass
                return False, 0

    def update_lease_status(self, lease_id: str, status: str) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        "UPDATE governance_leases SET status = ? WHERE lease_id = ?",
                        (status, lease_id),
                    )
                return True
            except Exception:
                return False

    def list_active_leases(self, subject_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    if subject_id:
                        rows = db.execute(
                            "SELECT lease_json FROM governance_leases "
                            "WHERE status = 'ACTIVE' AND subject_id = ? ORDER BY issued_at DESC",
                            (subject_id,),
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT lease_json FROM governance_leases "
                            "WHERE status = 'ACTIVE' ORDER BY issued_at DESC"
                        ).fetchall()
                    return [json.loads(r[0]) for r in rows]
            except Exception:
                return []

    # Delegations

    def save_delegation(self, grant_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR REPLACE INTO governance_delegations
                           (grant_id, issuer_id, subject_id, scope_json,
                            permitted_capabilities_json, denied_capabilities_json,
                            constraints_json, max_uses, used_count, issued_at,
                            expires_at, allow_sub_delegation, status, grant_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (grant_dict["grant_id"], grant_dict.get("issuer_id", ""),
                         grant_dict.get("subject_id", ""),
                         json.dumps(grant_dict.get("scope")),
                         json.dumps(grant_dict.get("permitted_capabilities", [])),
                         json.dumps(grant_dict.get("denied_capabilities", [])),
                         json.dumps(grant_dict.get("constraints", [])),
                         int(grant_dict.get("max_uses", 1)),
                         int(grant_dict.get("used_count", 0)),
                         grant_dict.get("issued_at", ""),
                         grant_dict.get("expires_at", ""),
                         int(grant_dict.get("allow_sub_delegation", False)),
                         grant_dict.get("status", "DRAFT"),
                         json.dumps(grant_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_delegation: %s", e)
                return False

    def get_delegation(self, grant_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT grant_json FROM governance_delegations WHERE grant_id = ?",
                        (grant_id,),
                    ).fetchone()
                    if row:
                        return json.loads(row[0])
            except Exception:
                pass
        return None

    def list_active_delegations(self, subject_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    if subject_id:
                        rows = db.execute(
                            "SELECT grant_json FROM governance_delegations "
                            "WHERE status = 'ACTIVE' AND subject_id = ? ORDER BY issued_at DESC",
                            (subject_id,),
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT grant_json FROM governance_delegations "
                            "WHERE status = 'ACTIVE' ORDER BY issued_at DESC"
                        ).fetchall()
                    return [json.loads(r[0]) for r in rows]
            except Exception:
                return []

    def update_delegation_status(self, grant_id: str, status: str) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        "UPDATE governance_delegations SET status = ? WHERE grant_id = ?",
                        (status, grant_id),
                    )
                return True
            except Exception:
                return False

    # Revocations

    def save_revocation(self, rev_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """INSERT OR IGNORE INTO governance_revocations
                           (revocation_id, target_type, target_id, revoked_by,
                            reason, revoked_at, cascaded_from, revocation_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (rev_dict["revocation_id"], rev_dict.get("target_type", ""),
                         rev_dict["target_id"], rev_dict.get("revoked_by", ""),
                         rev_dict.get("reason", ""), rev_dict.get("revoked_at", ""),
                         rev_dict.get("cascaded_from", ""), json.dumps(rev_dict)),
                    )
                return True
            except Exception:
                return False

    # Audit

    def save_audit(self, audit_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    prev = db.execute(
                        "SELECT * FROM governance_audit ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                    prev_hash = self._audit_row_hash(prev) if prev else ""
                    db.execute(
                        """INSERT INTO governance_audit
                           (audit_id, event_type, decision_id, proposal_hash,
                            evidence_json, recorded_at, previous_audit_hash)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (audit_dict["bundle_id"], audit_dict.get("event_type", ""),
                         audit_dict.get("decision_id", ""),
                         audit_dict.get("proposal_hash", ""),
                         json.dumps(audit_dict.get("evidence", {})),
                         audit_dict.get("recorded_at", ""),
                         prev_hash),
                    )
                return True
            except Exception as e:
                _log.warning("save_audit: %s", e)
                return False

    def verify_audit_chain(self) -> bool:
        """Verify append order and content hashes for governance audit evidence."""
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    rows = db.execute(
                        "SELECT * FROM governance_audit ORDER BY rowid ASC"
                    ).fetchall()
                expected = ""
                for row in rows:
                    if str(row["previous_audit_hash"] or "") != expected:
                        return False
                    expected = self._audit_row_hash(row)
                return True
            except Exception as exc:
                _log.warning("verify_audit_chain: %s", exc)
                return False

    @staticmethod
    def _audit_row_hash(row: Any) -> str:
        payload = {key: row[key] for key in row.keys()}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get_audit_for_decision(self, decision_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    row = db.execute(
                        "SELECT evidence_json, recorded_at, previous_audit_hash "
                        "FROM governance_audit WHERE decision_id = ? LIMIT 1",
                        (decision_id,),
                    ).fetchone()
                    if row:
                        return {
                            "evidence": json.loads(row[0]),
                            "recorded_at": row[1],
                            "previous_audit_hash": row[2],
                        }
            except Exception:
                pass
        return None

    # Approval Policies

    def save_approval_policy(self, policy_dict: dict[str, Any]) -> bool:
        with self._lock:
            try:
                with _db_connect(self.db_path) as db:
                    db.execute(
                        """CREATE TABLE IF NOT EXISTS governance_approval_policies (
                            policy_id TEXT PRIMARY KEY,
                            agent_id TEXT NOT NULL DEFAULT '',
                            capability_id TEXT NOT NULL DEFAULT '',
                            scope TEXT NOT NULL DEFAULT 'ask_per_command',
                            max_auto_approve_risk TEXT NOT NULL DEFAULT 'low',
                            auto_approve_read_only INTEGER NOT NULL DEFAULT 0,
                            auto_approve_tests INTEGER NOT NULL DEFAULT 0,
                            max_daily_approvals INTEGER NOT NULL DEFAULT 50,
                            require_confirmation_for_policy_change INTEGER NOT NULL DEFAULT 1,
                            created_at TEXT NOT NULL DEFAULT '',
                            updated_at TEXT NOT NULL DEFAULT '',
                            policy_json TEXT NOT NULL DEFAULT '{}'
                        )"""
                    )
                    db.execute(
                        """INSERT OR REPLACE INTO governance_approval_policies
                           (policy_id, agent_id, capability_id, scope,
                            max_auto_approve_risk, auto_approve_read_only,
                            auto_approve_tests, max_daily_approvals,
                            require_confirmation_for_policy_change,
                            created_at, updated_at, policy_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (policy_dict["policy_id"],
                         policy_dict.get("agent_id", ""),
                         policy_dict.get("capability_id", ""),
                         policy_dict.get("scope", "ask_per_command"),
                         policy_dict.get("max_auto_approve_risk", "low"),
                         int(policy_dict.get("auto_approve_read_only", False)),
                         int(policy_dict.get("auto_approve_tests", False)),
                         int(policy_dict.get("max_daily_approvals", 50)),
                         int(policy_dict.get("require_confirmation_for_policy_change", True)),
                         policy_dict.get("created_at", ""),
                         policy_dict.get("updated_at", ""),
                         json.dumps(policy_dict)),
                    )
                return True
            except Exception as e:
                _log.warning("save_approval_policy: %s", e)
                return False

    def get_approval_policy(self, agent_id: str, capability_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            try:
                with _db_connect(self.db_path, readonly=True) as db:
                    if capability_id:
                        row = db.execute(
                            "SELECT policy_json FROM governance_approval_policies "
                            "WHERE agent_id = ? AND capability_id = ? LIMIT 1",
                            (agent_id, capability_id),
                        ).fetchone()
                    else:
                        row = db.execute(
                            "SELECT policy_json FROM governance_approval_policies "
                            "WHERE agent_id = ? AND capability_id = '' LIMIT 1",
                            (agent_id,),
                        ).fetchone()
                    if row:
                        return json.loads(row[0])
            except Exception:
                pass
        return None

    def close(self) -> None:
        """Close is a no-op for SQLite via compat.db (connection per operation)."""
        pass

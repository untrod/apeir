"""Unified operations views and thin governed controls over canonical stores."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from nous_runtime.agent.coordination import AgentSessionCoordinator
from nous_runtime.agent.session import AgentSessionStore
from nous_runtime.api.responses import ok_response
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.control_plane.human_sessions import (
    get_human_auth,
    human_permission,
    is_human_session_context,
)
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.events.models import RunEvent
from nous_runtime.events.stream import EventStream
from nous_runtime.governance import get_gate, GovernanceRequest
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.credentials import CredentialBroker
from nous_runtime.node_runtime.distributed_work import (
    DistributedWorkStore,
    DistributedWorkState,
)
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.reality.contracts import DeviceLifecycle
from nous_runtime.reality.registry import DeviceRegistry
from nous_runtime.skills import SkillRegistry, SkillToolRuntime
from nous_runtime.workflow.runtime import WorkflowRuntime
from nous_runtime.workflow.store import WorkflowStore


class OperationsPlane:
    """A projection and adapter, never a second state or execution authority."""

    def __init__(
        self,
        root=".",
        *,
        gate=None,
        controller_state=None,
        device_state=None,
        controller=None,
        health_loader=None,
        workflow_handlers=None,
        workflow_handler_policies=None,
    ):
        self.root = Path(root).resolve()
        self.gate = gate or get_gate()
        self.controller_state = Path(
            controller_state or self.root / ".nous" / "relay"
        ).resolve()
        self.device_state = Path(
            device_state or self.root / ".nous" / "reality"
        ).resolve()
        self.live_controller = controller
        self.health_loader = health_loader
        self.workflow_handlers = dict(workflow_handlers or {})
        self.workflow_handler_policies = dict(workflow_handler_policies or {})

    def skills(self):
        """Read the one existing workspace registry, without background egress."""
        registry = SkillRegistry(self.root)
        records = registry.list(include_disabled=True, include_catalogs=False)
        records.extend(registry.catalog_records(local_only=True))
        return [
            item.summary()
            | {
                "skill_key": item.provider
                + ":"
                + item.skill_id
                + (
                    ":"
                    + hashlib.sha256(
                        str(item.metadata["catalog_source"]).encode()
                    ).hexdigest()[:16]
                    if item.provider == "catalog"
                    else ""
                ),
                "source": item.source,
                "catalog_source": str(item.metadata.get("catalog_source") or ""),
                "package_source": item.source if item.provider == "catalog" else "",
                "compatibility": str(
                    item.metadata.get("compatibility") or "unspecified"
                ),
                "dependencies": list(item.metadata.get("dependencies") or ()),
                "installable": item.provider == "catalog",
            }
            for item in records
        ], registry.diagnostics

    def controller(self):
        if self.live_controller is not None:
            return self.live_controller
        if not (self.controller_state / "identity.ed25519.pem").is_file():
            raise RuntimeError("Controller identity has not been provisioned")
        return NodeRelayServer(
            state_dir=self.controller_state,
            artifact_store=ContentAddressedArtifactStore(
                self.controller_state / "artifacts"
            ),
        )

    def snapshot(self):
        errors = []

        def load(component, call, fallback):
            try:
                return call()
            except Exception as exc:
                errors.append(
                    {
                        "component": component,
                        "status": "UNKNOWN",
                        "error_type": type(exc).__name__,
                    }
                )
                return fallback

        works = load(
            "works",
            lambda: [
                work.to_dict()
                for work in DistributedWorkStore(self.controller_state).list()
            ][:500],
            [],
        )
        agents = load(
            "agents",
            lambda: [item.to_dict() for item in AgentSessionStore(self.root).list()][
                :500
            ],
            [],
        )
        workflows = load(
            "workflows",
            lambda: [
                WorkflowStore._run_dict(item)
                for item in WorkflowStore(self.root).list_runs(limit=500)
            ],
            [],
        )
        devices = load(
            "devices",
            lambda: [
                item.to_dict() for item in DeviceRegistry(self.device_state).list()
            ][:500],
            [],
        )
        controller = load(
            "controller", lambda: self.controller().controller_status(), {}
        )
        nodes = controller.get("nodes", [])
        pairings = (
            load("pairings", lambda: self.controller().list_pairings(), [])
            if controller
            else []
        )
        skills, skill_diagnostics = load("skills", self.skills, ([], []))
        broker = ApprovalBroker(self.gate.store)
        approvals = load(
            "approvals", lambda: broker.list_operation_approvals(gate=self.gate), []
        )
        with self.gate.store.operation_transaction() as db:
            grants = [
                json.loads(row["lease_json"])
                | {"status": row["status"], "remaining_uses": row["remaining_uses"]}
                for row in db.execute(
                    "SELECT * FROM governance_leases ORDER BY rowid DESC LIMIT 500"
                )
            ]
            leases = [
                json.loads(row["lease_json"])
                | {"status": row["status"], "expires_at": row["expires_at"]}
                for row in db.execute(
                    "SELECT * FROM governance_credential_leases ORDER BY rowid DESC LIMIT 500"
                )
            ]
            activity = [
                dict(row) | {"evidence": json.loads(row["evidence_json"])}
                for row in db.execute(
                    "SELECT rowid AS sequence,* FROM governance_audit ORDER BY rowid DESC LIMIT 500"
                )
            ]
        for item in grants + leases:
            expiry = item.get("expires_at")
            try:
                expired = (
                    (expiry <= time.time())
                    if isinstance(expiry, (int, float))
                    else datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                    <= datetime.now(timezone.utc)
                )
            except (ValueError, TypeError):
                expired = True
            item["effective_status"] = (
                "EXPIRED" if item["status"] == "ACTIVE" and expired else item["status"]
            )
        artifacts = []
        for path in dict.fromkeys(
            (self.controller_state / "artifacts", self.root / ".nous" / "artifacts")
        ):
            if (path / "index.json").exists():
                store = ContentAddressedArtifactStore(path)
                artifacts.extend(
                    load(
                        "artifacts",
                        lambda: [
                            item.to_dict()
                            | {
                                "integrity": "MATCH"
                                if store.verify(item.digest)
                                else "MISMATCH"
                            }
                            for item in store.list()[:500]
                        ],
                        [],
                    )
                )
        evidence = [
            {
                "work_id": work["work_id"],
                "operation_id": work["work_id"],
                "state": work["state"],
                "receipt": work.get("result_summary", {}).get(
                    "remote_execution_receipt"
                ),
                "effect_verification": work.get("effect_verification", {}),
                "evidence_refs": work.get("evidence_refs", []),
            }
            for work in works
        ]
        incidents = [
            {
                "incident_id": "incident_"
                + hashlib.sha256(
                    (work["work_id"] + work.get("updated_at", "")).encode()
                ).hexdigest()[:24],
                "work_id": work["work_id"],
                "state": work["state"],
                "severity": "error",
                "message": "Uncertain effect requires evidence reconciliation"
                if work["state"] == "UNKNOWN"
                else "Work failed; inspect evidence before recovery",
            }
            for work in works
            if work["state"] in {"UNKNOWN", "FAILED"}
        ]
        acknowledged = set()
        if incidents:
            # Activity is a bounded view, not the acknowledgement authority.
            # Query only current incident IDs from the existing durable trail.
            identifiers = [item["incident_id"] for item in incidents]
            placeholders = ",".join("?" for _ in identifiers)
            with self.gate.store.operation_transaction() as db:
                acknowledged = {
                    row[0]
                    for row in db.execute(
                        "SELECT DISTINCT json_extract(evidence_json,'$.incident_id') "
                        "FROM governance_audit WHERE event_type='control.incident.acknowledged' "
                        f"AND json_extract(evidence_json,'$.incident_id') IN ({placeholders})",
                        identifiers,
                    )
                }
        for incident in incidents:
            incident["acknowledged"] = incident["incident_id"] in acknowledged
        if self.health_loader is None:
            from nous_runtime.api.routes import handle_health

            health = load("health", handle_health, {"ok": False})
        else:
            health = load("health", self.health_loader, {"ok": False})
        return redact_sensitive_data(
            {
                "schema": "apeir.operations/v1",
                "server_authoritative": True,
                "generated_at": int(time.time()),
                "agents": agents,
                "works": works,
                "workflows": workflows,
                "nodes": nodes,
                "controller_public_key": controller.get("public_key", ""),
                "pairings": pairings,
                "skills": skills,
                "skill_diagnostics": skill_diagnostics,
                "skill_catalogs": load(
                    "skill_catalogs",
                    lambda: [
                        {"source": source, "remote": "://" in source}
                        for source in SkillRegistry(self.root).catalogs()
                    ],
                    [],
                ),
                "devices": devices,
                "approvals": approvals,
                "grants": grants,
                "credential_leases": leases,
                "artifacts": artifacts[:500],
                "evidence": evidence,
                "activity": activity,
                "incidents": incidents,
                "health": {
                    "runtime": health,
                    "degraded": bool(
                        errors
                        or incidents
                        or not health.get("ok")
                        or (health.get("data") or {}).get("status", "ok") != "ok"
                    ),
                    "components": errors,
                },
                "controls": {
                    "actions": [
                        "approve_once",
                        "deny",
                        "interrupt",
                        "reconcile",
                        "revoke",
                        "acknowledge",
                    ]
                    + (["resume"] if self.workflow_handlers else []),
                    "effect_interrupt_guarantee": False,
                    "kernel_traversed": False,
                },
            }
        )

    def _request_for_work(self, work):
        authorization_id = work.execution_arguments.get("authorization_id")
        if not authorization_id:
            raise PermissionError("Work has no governed Operation binding")
        request = self.gate.get_operation_request(authorization_id)
        if (
            request.work_id != work.work_id
            or request.resource_id != work.target_resource_id
        ):
            raise PermissionError("Work authorization binding differs")
        return request

    def _admit(self, context, request, action):
        self.gate._require_human(context, request)
        if is_human_session_context(context, self.gate.store) and not human_permission(
            context, "control." + action, request.resource_id
        ):
            raise PermissionError("Human control permission denied")
        with self.gate.store.operation_transaction() as db:
            self.gate._require_human(context, request, db=db)
            self.gate.store.append_operation_audit(
                db,
                "control.action.admitted",
                self.gate._evidence(
                    request,
                    action=action,
                    actor_id=context.subject_id,
                    authorization_context_id=context.context_id,
                    human_session_id=context.session_id,
                ),
            )

    def node_action(self, body, context):
        """Human-governed trust administration, not Work or Capability authorization."""
        controller = self.controller()
        action, target = body.get("action"), body.get("target_id")

        def admit(record):
            node_id = record.get("node_id", "")
            resource = (
                "node:" + node_id if node_id else "controller:" + controller.public_key
            )
            request = GovernanceRequest(
                operation_id=record.get("request_id", "node-trust:" + node_id),
                work_id="",
                capability_id="node.trust",
                resource_id=resource,
                subject_id="node:" + node_id,
                node_id=node_id,
            )
            self._admit(
                context, request, "revoke" if action == "revoke" else "node_pair"
            )
            with self.gate.store.operation_transaction() as db:
                self.gate._require_human(context, request, db=db)
                self.gate.store.append_operation_audit(
                    db,
                    "node.trust.decision",
                    {
                        "request_id": record.get("request_id", ""),
                        "node_id": node_id,
                        "public_key": record.get("public_key", ""),
                        "node_proof_digest": record.get("node_proof_digest", ""),
                        "controller_public_key": controller.public_key,
                        "action": action,
                        "resource_id": resource,
                        "actor_id": context.subject_id,
                        "human_session_id": context.session_id,
                        "authorization_context_id": context.context_id,
                        "execution_authority_issued": False,
                        "trust_persistence_confirmed": False,
                    },
                )
            return {
                "actor_id": context.subject_id,
                "human_session_id": context.session_id,
                "authorization_context_id": context.context_id,
            }

        if body.get("kind") == "nodes" and action == "revoke":
            return controller.revoke_node(target, admit=admit)
        if body.get("kind") != "pairings":
            raise PermissionError("Unsupported Node trust action")
        if action == "create":
            if target != controller.public_key:
                raise PermissionError("Confirm the exact Controller public key")
            return controller.create_pairing(body.get("relay_url", ""), admit=admit)
        if action in {"approve_once", "deny"}:
            return controller.decide_pairing(
                target,
                approve=action == "approve_once",
                node_id=body.get("node_id", ""),
                public_key=body.get("public_key", ""),
                admit=admit,
            )
        raise PermissionError("Unsupported pairing decision")

    def _authorize_skill_source(self, context, request, source):
        """Check the current human's configured permission for this exact URL."""
        self.gate._require_human(context, request)
        if not human_permission(context, "tool.web_fetch", source):
            raise PermissionError("Human permission denied for exact Skill source URL")

    def _skill_catalog_action(self, body, context):
        from nous_runtime.skills.remote import require_remote_url

        action, source = body["action"], body.get("catalog_source")
        if not isinstance(source, str) or not source or body.get("target_id") != source:
            raise PermissionError("Confirm the exact Skill catalog source")
        # API additions and refreshes acquire remote catalogs explicitly. Local
        # catalog registration retains the existing trusted workspace CLI path.
        if action != "catalog_remove":
            require_remote_url(source)
        registry = SkillRegistry(self.root)
        if action != "catalog_add" and source not in registry.catalogs():
            raise KeyError(source)
        request = GovernanceRequest(
            operation_id="skill-catalog:" + hashlib.sha256(source.encode()).hexdigest(),
            work_id="",
            capability_id="skill.manage",
            resource_id="skill-catalog:" + source,
            subject_id="skill-catalog",
        )
        self._admit(context, request, "skill_manage")

        def revalidate():
            self.gate._require_human(context, request)
            if not human_permission(
                context, "control.skill_manage", request.resource_id
            ):
                raise PermissionError("Human catalog permission expired or revoked")

        def authorize(url):
            self._authorize_skill_source(context, request, url)

        revalidate()
        if action == "catalog_remove":
            result = {
                "removed": registry.remove_catalog(source, before_publish=revalidate)
            }
        else:
            method = (
                registry.add_catalog
                if action == "catalog_add"
                else registry.refresh_catalog
            )
            method(source, before_publish=revalidate, authorize_remote=authorize)
            result = {"registered": True}
        with self.gate.store.operation_transaction() as db:
            self.gate.store.append_operation_audit(
                db,
                "skill.catalog.management.completed",
                {
                    "action": action,
                    "catalog_source": source,
                    "actor_id": context.subject_id,
                    "human_session_id": context.session_id,
                    "authorization_context_id": context.context_id,
                    "execution_performed": False,
                    "execution_authority_issued": False,
                },
            )
        return {
            "catalog": result | {"source": source},
            "authority": "none",
            "execution_performed": False,
        }

    def skill_action(self, body, context):
        """Human package administration; installed instructions are not authority."""
        action, target = body.get("action"), body.get("target_id")
        if action in {"catalog_add", "catalog_refresh", "catalog_remove"}:
            return self._skill_catalog_action(body, context)
        if action not in {"install", "enable", "disable", "remove", "load"}:
            raise PermissionError("Unsupported Skill action")
        row = next(
            (item for item in self.skills()[0] if item["skill_key"] == target), None
        )
        if row is None:
            raise KeyError(target)
        if body.get("digest") != row["digest"] or body.get("version") != row["version"]:
            raise PermissionError("Skill version or digest changed; review it again")
        request = GovernanceRequest(
            operation_id="skill-admin:" + target,
            work_id="",
            capability_id="skill.manage" if action != "load" else "skill.load",
            resource_id="skill:" + row["skill_id"],
            subject_id="skill:" + row["skill_id"],
        )
        permission = (
            "skill_install"
            if action == "install"
            else "skill_load"
            if action == "load"
            else "skill_manage"
        )
        self._admit(context, request, permission)

        def revalidate():
            self.gate._require_human(context, request)
            if is_human_session_context(
                context, self.gate.store
            ) and not human_permission(
                context, "control." + permission, request.resource_id
            ):
                raise PermissionError("Human Skill permission expired or revoked")

        registry = SkillRegistry(self.root)
        if action == "install":
            if row["provider"] != "catalog":
                raise PermissionError("Install requires a registered catalog entry")
            if "://" in row["catalog_source"] and (
                body.get("catalog_source") != row["catalog_source"]
                or body.get("package_source") != row["package_source"]
            ):
                raise PermissionError("Skill source changed; review it again")
            result = registry.install_from_catalog(
                row["skill_id"],
                catalog_source=row["catalog_source"],
                version=row["version"],
                digest=row["digest"],
                before_publish=revalidate,
                authorize_remote=lambda source: self._authorize_skill_source(
                    context, request, source
                ),
                package_source=body.get("package_source", ""),
            ).to_dict()
        else:
            revalidate()
            qualified = row["provider"] + ":" + row["skill_id"]
            if action == "load":
                result = SkillToolRuntime(self.root).execute(
                    "skill_load", {"skill_id": qualified}
                )
                if not result["ok"]:
                    raise PermissionError(result["error"])
            elif action == "remove":
                if row["provider"] != "installed":
                    raise PermissionError("Only installed Skills can be removed")
                result = {
                    "removed": registry.remove(qualified),
                    "skill_id": row["skill_id"],
                }
            else:
                result = getattr(registry, action)(qualified).to_dict()
        with self.gate.store.operation_transaction() as db:
            self.gate.store.append_operation_audit(
                db,
                "skill.management.completed",
                {
                    "action": action,
                    "skill_id": row["skill_id"],
                    "version": row["version"],
                    "package_digest": row["digest"],
                    "catalog_source": row["catalog_source"],
                    "package_source": row["package_source"],
                    "artifact_ref": result.get("artifact_ref", ""),
                    "actor_id": context.subject_id,
                    "human_session_id": context.session_id,
                    "authorization_context_id": context.context_id,
                    "execution_performed": False,
                    "execution_authority_issued": False,
                },
            )
        return {"skill": result, "execution_performed": False, "authority": "none"}

    def action(self, body, context):
        if body.get("kind") == "skills":
            return self.skill_action(body, context)
        if body.get("kind") == "pairings" or (
            body.get("kind") == "nodes" and body.get("action") == "revoke"
        ):
            return self.node_action(body, context)
        action, kind, target = (
            body.get("action"),
            body.get("kind"),
            body.get("target_id"),
        )
        if not isinstance(target, str) or not target:
            raise ValueError("An explicit target is required")
        broker = ApprovalBroker(self.gate.store)
        if kind == "approvals" and action in {"approve_once", "deny"}:
            record = broker.get_operation_approval(target, gate=self.gate)
            request = self.gate.get_operation_request(record["governance_request_id"])
            self._admit(context, request, action)
            response = broker.respond_operation(
                target,
                "approve" if action == "approve_once" else "deny",
                context,
                gate=self.gate,
            )
            return {"approval": response.to_dict(), "replanned": False}
        if kind == "works" and action in {"interrupt", "reconcile", "resume"}:
            work = DistributedWorkStore(self.controller_state).get(target)
            if work is None:
                raise KeyError(target)
            request = self._request_for_work(work)
            self._admit(context, request, action)
            if action == "reconcile":
                # Existing receipt reconciliation cannot execute a Provider. A
                # Reality VERIFIED result still needs independent observation.
                return self.controller().reconcile_work(target)
            if action == "resume":
                if not self.workflow_handlers or work.state in {
                    DistributedWorkState.UNKNOWN,
                    DistributedWorkState.FAILED,
                }:
                    raise PermissionError(
                        "Resume requires registered original handlers and recoverable evidence"
                    )
                coordinator = AgentSessionCoordinator(self.root)
                try:
                    return {
                        "agent_session": coordinator.resume_plan(
                            request.agent_session_id,
                            handlers=self.workflow_handlers,
                            handler_policies=self.workflow_handler_policies,
                        ).to_dict(),
                        "replanned": False,
                    }
                finally:
                    coordinator.close()
            result = self.gate.interrupt_operation(request.authorization_id, context)
            if request.workflow_run_id:
                WorkflowRuntime(str(self.root)).cancel(request.workflow_run_id)
            if request.agent_session_id:
                coordinator = AgentSessionCoordinator(self.root)
                try:
                    coordinator.cancel(
                        request.agent_session_id,
                        reason="Human requested interruption; effect outcome must be reconciled",
                    )
                finally:
                    coordinator.close()
            return result
        if action == "revoke" and kind in {"grants", "credential_leases", "devices"}:
            with self.gate.store.operation_transaction() as db:
                if kind == "grants":
                    row = db.execute(
                        "SELECT proposal_hash FROM governance_leases WHERE lease_id=?",
                        (target,),
                    ).fetchone()
                elif kind == "credential_leases":
                    row = db.execute(
                        "SELECT authorization_id FROM governance_credential_leases WHERE lease_id=?",
                        (target,),
                    ).fetchone()
                else:
                    row = db.execute(
                        "SELECT authorization_id FROM governance_operations WHERE json_extract(request_json,'$.resource_id')=? ORDER BY rowid DESC LIMIT 1",
                        (target,),
                    ).fetchone()
            if row is None:
                raise PermissionError("Revocation has no existing authority binding")
            request = self.gate.get_operation_request(row[0])
            self._admit(context, request, action)
            if kind == "credential_leases":
                CredentialBroker(self.gate).revoke(row[0], context, lease_id=target)
            else:
                self.gate.revoke_operation_authority(
                    row[0],
                    context,
                    grant_id=target if kind == "grants" else "",
                    resource=kind == "devices",
                )
                if kind == "devices":
                    DeviceRegistry(self.device_state).transition(
                        target, DeviceLifecycle.REVOKED
                    )
            return {"target_id": target, "revoked": True}
        if action == "acknowledge" and kind == "incidents":
            incident = next(
                (
                    item
                    for item in self.snapshot()["incidents"]
                    if item["incident_id"] == target
                ),
                None,
            )
            if incident is None:
                raise KeyError(target)
            work = DistributedWorkStore(self.controller_state).get(incident["work_id"])
            request = self._request_for_work(work)
            self._admit(context, request, action)
            self.gate.record_operation_evidence(
                request.authorization_id,
                "control.incident.acknowledged",
                incident_id=target,
                actor_id=context.subject_id,
                authorization_context_id=context.context_id,
                human_session_id=context.session_id,
            )
            return {
                "incident_id": target,
                "acknowledged": True,
                "effect_resolved": False,
            }
        raise PermissionError("Control action is unsupported")

    def transitions(self, *, since=0):
        snapshot = self.snapshot()
        facts = {
            key: snapshot[key]
            for key in (
                "agents",
                "works",
                "workflows",
                "nodes",
                "pairings",
                "skills",
                "skill_catalogs",
                "devices",
                "approvals",
                "grants",
                "credential_leases",
                "incidents",
            )
        }
        facts["health"] = {
            "degraded": snapshot["health"]["degraded"],
            "components": snapshot["health"]["components"],
        }
        digest = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
        stream = EventStream(str(self.root))
        previous = stream.load_events("control-plane")
        if not previous or previous[-1].payload.get("state_digest") != digest:
            stream.emit(
                RunEvent(
                    event_id="control_"
                    + hashlib.sha256(
                        (
                            str(previous[-1].sequence if previous else 0) + digest
                        ).encode()
                    ).hexdigest(),
                    run_id="control-plane",
                    event_type="control.state.changed",
                    actor="runtime",
                    payload={
                        "state_digest": digest,
                        "counts": {
                            key: len(value)
                            for key, value in facts.items()
                            if isinstance(value, list)
                        },
                    },
                )
            )
        return [
            event.to_dict()
            for event in stream.load_events("control-plane")
            if event.sequence > int(since)
        ][:100]


_operations: OperationsPlane | None = None


def get_operations():
    global _operations
    if _operations is None:
        root = os.environ.get("NOUS_WORKSPACE_ROOT", ".")
        _operations = OperationsPlane(
            root,
            controller_state=os.environ.get("NOUS_CONTROLLER_STATE_DIR"),
            device_state=os.environ.get("NOUS_REALITY_STATE_DIR"),
        )
    return _operations


def snapshot_route():
    return ok_response(get_operations().snapshot())


def events_route(params=None):
    return ok_response(
        {
            "events": get_operations().transitions(
                since=int((params or {}).get("since", 0))
            )
        }
    )


class PairingInvitationResponse(dict):
    """Short-lived code stays outside ordinary API serialization until human HTTP delivery."""

    def __init__(self, result):
        public = dict(result)
        self.pairing_code = public.pop("pairing_code")
        super().__init__(ok_response(public))


def action_route(body, *, authorization_context):
    result = get_operations().action(body, authorization_context)
    if body.get("kind") == "pairings" and body.get("action") == "create":
        return PairingInvitationResponse(result)
    return ok_response(result)


def human_challenge_route(body):
    return ok_response(get_human_auth().challenge(body.get("code_challenge", "")))


def human_login_route(body):
    return get_human_auth().login(
        body.get("challenge_id", ""),
        body.get("code", ""),
        body.get("code_verifier", ""),
    )


def human_session_route(*, authorization_context):
    return ok_response(get_human_auth().session(authorization_context))


def human_nonce_route(body, *, authorization_context):
    return ok_response(
        get_human_auth().nonce(
            authorization_context,
            body.get("method", ""),
            body.get("path", ""),
            body.get("body", {}),
        )
    )


def human_logout_route(*, authorization_context):
    return get_human_auth().logout(authorization_context)


OPERATIONS_ROUTES = {
    ("GET", "/api/v1/control/operations"): snapshot_route,
    ("GET", "/api/v1/control/events"): events_route,
    ("POST", "/api/v1/control/operations/actions"): action_route,
    ("POST", "/api/v1/control/human/challenge"): human_challenge_route,
    ("POST", "/api/v1/control/human/session"): human_login_route,
    ("GET", "/api/v1/control/human/session"): human_session_route,
    ("POST", "/api/v1/control/human/nonce"): human_nonce_route,
    ("POST", "/api/v1/control/human/logout"): human_logout_route,
}

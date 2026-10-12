"""Workspace edit review over the existing Workflow, Governance and Artifact owners."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from uuid import uuid4

from nous_runtime.artifact import ArtifactType
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.core.redaction import redact_sensitive_data, redact_sensitive_text
from nous_runtime.governance import GovernanceDecision, GovernanceRequest, get_gate
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.operation_contracts import GovernanceApprovalRequired
from nous_runtime.verification.deterministic import DeterministicVerifier
from nous_runtime.workflow import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowState,
    WorkflowStep,
)
from nous_runtime.workflow.models import WorkflowHandlerPolicy
from nous_runtime.workflow.store import binding_digest
from nous_runtime.workspace.workbench import (
    DeveloperWorkbench,
    WorkbenchConflict,
    WorkbenchError,
)

_WORKFLOW_ID = "workspace.proposal"
_ACTION = "workspace.proposal.apply"
_JOURNAL = "apply:effects"
_MAX_FILES = 24
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DISPATCHED = {"applying", "unknown", "applied", "mismatch"}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class WorkspaceProposalService:
    """Adapt reviewed file edits to canonical durable owners, without another store.

    Workflow inputs bind the immutable CAS manifest. Its apply checkpoint records
    effect intentions before replacement. Governance owns human approval and
    one-use execution admission. Recovery only observes the original attempt.
    """

    def __init__(self, workspace_root: str | Path, *, gate=None, broker=None):
        self.workbench = DeveloperWorkbench(workspace_root)
        self.root = self.workbench.root
        self.resource_id = "workspace:" + _digest(str(self.root).encode("utf-8"))
        self.gate = gate if gate is not None else get_gate()
        if (
            Path(self.gate.store.db_path).resolve()
            != (self.root / ".nous" / "governance.db").resolve()
        ):
            raise WorkbenchError("Workspace and Governance authority differ.")
        self.broker = broker if broker is not None else ApprovalBroker(self.gate.store)
        if (
            Path(self.broker._store.db_path).resolve()
            != Path(self.gate.store.db_path).resolve()
        ):
            raise WorkbenchError("Approval and Governance authority differ.")
        artifact_root = self.root / ".nous" / "artifacts"
        if not artifact_root.resolve().is_relative_to(self.root):
            raise WorkbenchError("Artifact storage escapes the workspace.")
        self.artifacts = ContentAddressedArtifactStore(artifact_root)
        self.workflow_handlers = {_ACTION: self._apply_step}
        self.runtime = WorkflowRuntime(
            str(self.root),
            handlers=self.workflow_handlers,
            max_parallel=1,
            handler_policies={_ACTION: WorkflowHandlerPolicy(reconcile_started=True)},
        )
        self.store = self.runtime.store
        definition = WorkflowDefinition(
            _WORKFLOW_ID,
            "1.0.0",
            TriggerType.MANUAL,
            (WorkflowStep("apply", StepType.CAPABILITY, _ACTION, timeout_seconds=120),),
        )
        prior = self.store.get_definition(definition.workflow_id, definition.version)
        if prior is None:
            self.runtime.register(definition)
        elif prior != definition:
            raise WorkbenchError("Workspace proposal Workflow definition differs.")

    def prepare(
        self,
        files: list[Mapping[str, Any]],
        *,
        subject_id: str,
        title: str = "Workspace changes",
        source_work_id: str = "",
        agent_session_id: str = "",
        plan_id: str = "",
        requested_by: str = "",
        source_request_id: str = "",
    ) -> dict[str, Any]:
        """Snapshot bounded edits, then pause the original Workflow for approval."""
        if not isinstance(files, list) or not 1 <= len(files) <= _MAX_FILES:
            raise WorkbenchError("A proposal must contain between 1 and 24 files.")
        identities = {
            "subject_id": subject_id,
            "source_work_id": source_work_id,
            "agent_session_id": agent_session_id,
            "plan_id": plan_id,
            "requested_by": requested_by,
            "source_request_id": source_request_id,
        }
        if not subject_id or any(
            not isinstance(value, str) or len(value) > 256
            for value in identities.values()
        ):
            raise WorkbenchError("Proposal identity bindings are invalid.")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise WorkbenchError("Proposal title must contain 1 to 200 characters.")
        if redact_sensitive_data({**identities, "title": title}) != {
            **identities,
            "title": title,
        }:
            raise WorkbenchError("Credential material cannot enter a proposal.")
        prepared = []
        seen = set()
        total = 0
        with self.workbench.mutation_lock():
            for item in files:
                if (
                    not isinstance(item, Mapping)
                    or not isinstance(item.get("path"), str)
                    or not isinstance(item.get("content"), str)
                ):
                    raise WorkbenchError("Each file requires a text path and content.")
                path = item["path"]
                if not path or len(path) > 1024:
                    raise WorkbenchError(
                        "Proposal paths must contain 1 to 1024 characters."
                    )
                target = self.workbench._write_target(path)
                relative = target.relative_to(self.root).as_posix()
                if relative in seen:
                    raise WorkbenchError("Proposal paths must be unique.")
                seen.add(relative)
                exists = target.is_file()
                expected_exists = item.get("expected_exists", exists)
                if not isinstance(expected_exists, bool) or expected_exists != exists:
                    raise WorkbenchConflict("A proposal file's existence changed.")
                expected_sha256 = item.get("expected_sha256", "")
                if not isinstance(expected_sha256, str) or (
                    expected_sha256 and not _SHA256.fullmatch(expected_sha256)
                ):
                    raise WorkbenchError(
                        "Expected SHA-256 must be a full lowercase digest."
                    )
                preview = self.workbench.preview_write(
                    relative, item["content"], expected_sha256=expected_sha256
                )
                before = self.workbench._read_bytes(target) if exists else None
                after = item["content"].encode("utf-8")
                if any(
                    redact_sensitive_text(data.decode("utf-8")) != data.decode("utf-8")
                    for data in (before, after)
                    if data is not None
                ):
                    raise WorkbenchError(
                        "Credential material cannot enter proposal Artifacts."
                    )
                total += len(after)
                prepared.append((preview, before, after))
            if total > _MAX_TOTAL_BYTES:
                raise WorkbenchError("The proposal exceeds the 2 MiB write limit.")
            entries = []
            for preview, before, after in prepared:
                before_ref = (
                    self._artifact(before, ArtifactType.FILE, "workspace-original")
                    if before is not None
                    else ""
                )
                after_ref = self._artifact(
                    after, ArtifactType.FILE, "workspace-replacement"
                )
                entries.append(
                    {
                        "path": preview["path"],
                        "expected_exists": preview["exists"],
                        "before_sha256": preview["before_sha256"],
                        "after_sha256": preview["after_sha256"],
                        "before_ref": before_ref,
                        "after_ref": after_ref,
                        "size_bytes": len(after),
                        "changed": preview["changed"],
                    }
                )
            manifest = {
                "schema": "nous.workspace-proposal/v1",
                "workspace_resource": self.resource_id,
                "title": title.strip(),
                "created_at": _now(),
                "proposal_nonce": uuid4().hex,
                **identities,
                "files": entries,
            }
            manifest_ref = self._artifact(
                _canonical(manifest),
                ArtifactType.EVIDENCE,
                "workspace-proposal.json",
                depends_on=tuple(
                    ref
                    for item in entries
                    for ref in (item["before_ref"], item["after_ref"])
                    if ref
                ),
            )
        run = self.runtime.start(
            _WORKFLOW_ID,
            "1.0.0",
            {"manifest_ref": manifest_ref, "workspace_resource": self.resource_id},
            idempotency_key=manifest_ref,
        )
        return self.read(run.run_id)

    def list(self, *, limit: int = 100) -> dict[str, Any]:
        maximum = max(1, min(int(limit), 100))
        runs = [
            run
            for run in self.store.history(_WORKFLOW_ID, limit=maximum)
            if run.inputs.get("workspace_resource") == self.resource_id
        ]
        proposals = [self.read(run.run_id, include_diff=False) for run in runs]
        return {"proposals": proposals, "total": len(proposals)}

    def read(self, proposal_id: str, *, include_diff: bool = True) -> dict[str, Any]:
        with self.workbench.mutation_lock():
            run = self._run(proposal_id)
            manifest = self._manifest(run)
            journal, request = self._binding(run, manifest)
            return self._view(
                run, manifest, journal, request, include_diff=include_diff
            )

    def apply(self, proposal_id: str) -> dict[str, Any]:
        """Resume the original approval pause; an attempted edit is never replayed."""
        run = self._run(proposal_id)
        journal = self.store.checkpoints(run.run_id).get(_JOURNAL, {})
        if journal.get("state") in _DISPATCHED:
            return self.reconcile(proposal_id)
        if run.state in {WorkflowState.CANCELLED, WorkflowState.COMPLETED}:
            result = self.read(proposal_id)
        else:
            self.runtime.resume(run.run_id)
            result = self.read(proposal_id)
        return {**result, "ok": result["applied"]}

    def reconcile(self, proposal_id: str) -> dict[str, Any]:
        """Acquire fresh byte evidence for an original attempt; do not write files."""
        with self.store.execution_lock(proposal_id), self.workbench.mutation_lock():
            run = self._run(proposal_id)
            manifest = self._manifest(run)
            journal, request = self._binding(run, manifest)
            if journal.get("state") not in _DISPATCHED:
                return self._view(run, manifest, journal, request)
            journal = self._reconcile_locked(run, manifest, journal, request)
            output = self._output(run, journal, request)
            if journal["state"] == "applied":
                checkpoint = self.store.checkpoints(run.run_id).get("apply", {})
                definition = self.store.get_definition(
                    run.workflow_id, run.workflow_version
                )
                checkpoint.update(
                    status="completed",
                    output=output,
                    error="",
                    binding_digest=self.runtime._step_binding(run, definition.steps[0]),
                    output_digest=binding_digest(output),
                )
                run = self.store.finish_step(run.run_id, "apply", checkpoint)
                if not run.cancellation_requested:
                    run.state = WorkflowState.COMPLETED
                    run.error = ""
                    self.store.save_run(run)
            elif run.state not in {WorkflowState.COMPLETED, WorkflowState.CANCELLED}:
                run.state = (
                    WorkflowState.UNKNOWN
                    if journal["state"] == "unknown"
                    else WorkflowState.FAILED
                )
                run.error = (
                    journal.get("error") or "Workspace effect requires reconciliation."
                )
                self.store.save_run(run)
            result = self._view(run, manifest, journal, request)
            return {**result, "ok": result["applied"], "replayed": False}

    def _apply_step(self, _step: WorkflowStep, context: dict[str, Any]):
        with self.workbench.mutation_lock():
            run = self._run(context["run_id"])
            manifest = self._manifest(run)
            journal, request = self._binding(run, manifest, create=True)
            if journal.get("state") in _DISPATCHED:
                journal = self._reconcile_locked(run, manifest, journal, request)
                if journal["state"] == "applied":
                    return self._output(run, journal, request)
                raise WorkbenchError(
                    "Workspace effect remains uncertain; it cannot be replayed."
                )
            if journal.get("state") in {"conflict", "denied"}:
                raise WorkbenchConflict(
                    journal.get("error") or "Original proposal cannot execute."
                )
            verdict = self.gate.evaluate_operation(request.authorization_id)
            approval = self.gate.store.get_approval_request(
                "apr_" + request.authorization_id[4:]
            )
            if verdict in {GovernanceDecision.DENY, GovernanceDecision.UNKNOWN}:
                journal.update(
                    state="denied" if verdict is GovernanceDecision.DENY else "blocked",
                    error="Current Governance admission is " + verdict.value + ".",
                )
                self._save(run.run_id, journal)
                raise WorkbenchError(journal["error"])
            if not approval or approval.get("status") != "APPROVED":
                pending = self.broker.request_operation(
                    request.authorization_id, gate=self.gate
                )
                raise GovernanceApprovalRequired(
                    {
                        **self._output(run, journal, request),
                        "approval_request_id": pending.request_id,
                    }
                )
            try:
                self._preflight(manifest)
            except (WorkbenchError, OSError) as exc:
                journal.update(state="conflict", error=redact_sensitive_text(str(exc)))
                self._save(run.run_id, journal)
                raise
            journal.update(state="applying", started_at=_now(), files=[])
            self._save(run.run_id, journal)
            completed = set()

            def resource_check():
                try:
                    current_run = self.store.get_run(run.run_id)
                    if current_run is None or current_run.cancellation_requested:
                        return False
                    for index, item in enumerate(manifest["files"]):
                        observed = self._observe(item["path"])
                        expected_exists = (
                            True if index in completed else item["expected_exists"]
                        )
                        expected_hash = (
                            item["after_sha256"]
                            if index in completed
                            else item["before_sha256"]
                        )
                        if observed != {
                            "exists": expected_exists,
                            "sha256": expected_hash,
                        }:
                            return False
                    return True
                except (OSError, WorkbenchError):
                    return False

            try:
                with self.gate.admit_operation(
                    request.authorization_id, resource_check=resource_check
                ) as revalidate:
                    for index, item in enumerate(manifest["files"]):
                        revalidate()
                        journal["files"].append(
                            {
                                "path": item["path"],
                                "state": "intent",
                                "before_sha256": item["before_sha256"],
                                "after_sha256": item["after_sha256"],
                            }
                        )
                        self._save(run.run_id, journal)
                        replacement = (
                            self.artifacts.resolve(item["after_ref"])
                            .read_bytes()
                            .decode("utf-8")
                        )
                        result = self.workbench._write_file(
                            item["path"],
                            replacement,
                            expected_sha256=item["before_sha256"],
                            operation="proposal",
                        )
                        if self._observe(item["path"]) != {
                            "exists": True,
                            "sha256": item["after_sha256"],
                        }:
                            raise WorkbenchConflict(
                                "Fresh file bytes differ from the approved replacement."
                            )
                        completed.add(index)
                        journal["files"][-1].update(
                            state="written",
                            backup_path=result["backup_path"],
                            run_id=result["run_id"],
                        )
                        self._save(run.run_id, journal)
                    revalidate()
                journal = self._reconcile_locked(run, manifest, journal, request)
                if journal["state"] != "applied":
                    raise WorkbenchError("Fresh workspace verification did not match.")
                return self._output(run, journal, request)
            except Exception as exc:
                journal.update(state="unknown", error=redact_sensitive_text(str(exc)))
                self._save(run.run_id, journal)
                raise

    def _run(self, proposal_id):
        run = self.store.get_run(str(proposal_id))
        if run is None or run.workflow_id != _WORKFLOW_ID:
            raise WorkbenchError("Workspace proposal was not found.")
        if run.inputs.get("workspace_resource") != self.resource_id:
            raise WorkbenchError("Proposal belongs to a different workspace.")
        return run

    def _manifest(self, run):
        ref = run.inputs.get("manifest_ref")
        manifest = json.loads(self._cas_bytes(ref, limit=_MAX_MANIFEST_BYTES))
        if (
            manifest.get("schema") != "nous.workspace-proposal/v1"
            or manifest.get("workspace_resource") != self.resource_id
            or not isinstance(manifest.get("files"), list)
            or not 1 <= len(manifest["files"]) <= _MAX_FILES
            or not manifest.get("subject_id")
        ):
            raise WorkbenchError("Proposal manifest bindings are invalid.")
        seen = set()
        total = 0
        for item in manifest["files"]:
            pure = PurePosixPath(item["path"])
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or any(part.casefold() in {".nous", ".git"} for part in pure.parts)
                or pure.as_posix() in {".", "workspace.json"}
            ):
                raise WorkbenchError("Proposal manifest path is protected.")
            relative = pure.as_posix()
            if relative != item["path"] or relative in seen:
                raise WorkbenchError("Proposal manifest paths differ or repeat.")
            seen.add(relative)
            after = self._cas_bytes(item["after_ref"])
            if len(after) > _MAX_FILE_BYTES or _digest(after) != item["after_sha256"]:
                raise WorkbenchError("Proposal replacement integrity differs.")
            after.decode("utf-8")
            total += len(after)
            if not isinstance(item.get("expected_exists"), bool):
                raise WorkbenchError("Proposal existence binding is invalid.")
            if item["expected_exists"]:
                before = self._cas_bytes(item["before_ref"])
                if _digest(before) != item["before_sha256"]:
                    raise WorkbenchError("Proposal original integrity differs.")
                before.decode("utf-8")
            elif item["before_ref"] or item["before_sha256"]:
                raise WorkbenchError("Absent proposal files have original bytes.")
        if total > _MAX_TOTAL_BYTES:
            raise WorkbenchError("Proposal replacement bytes exceed their bound.")
        return manifest

    def _request(self, run, manifest, capability_inputs):
        return GovernanceRequest(
            operation_id="work_" + _digest((run.run_id + ":apply").encode())[:32],
            work_id="work_" + _digest((run.run_id + ":apply").encode())[:32],
            workflow_run_id=run.run_id,
            agent_session_id=manifest["agent_session_id"],
            plan_id=manifest["plan_id"],
            capability_id="project.write_file",
            resource_id=self.resource_id,
            subject_id=manifest["subject_id"],
            input_artifacts=tuple(
                dict.fromkeys(
                    (
                        run.inputs["manifest_ref"],
                        *(
                            ref
                            for item in manifest["files"]
                            for ref in (item["before_ref"], item["after_ref"])
                            if ref
                        ),
                    )
                )
            ),
            expected_effect={
                "files": [
                    {"path": item["path"], "sha256": item["after_sha256"]}
                    for item in manifest["files"]
                ],
                "checksum": _digest(
                    _canonical(
                        [
                            {
                                "path": item["path"],
                                "exists": True,
                                "sha256": item["after_sha256"],
                            }
                            for item in manifest["files"]
                        ]
                    )
                ),
            },
            capability_inputs=capability_inputs,
        )

    def _binding(self, run, manifest, *, create=False):
        journal = self.store.checkpoints(run.run_id).get(_JOURNAL)
        if journal is None:
            if not create:
                raise WorkbenchError("Original proposal Governance binding is missing.")
            request = self._request(
                run, manifest, self.gate.capability_inputs("project.write_file")
            )
            self.gate.register_operation(request)
            journal = {
                "manifest_ref": run.inputs["manifest_ref"],
                "authorization_id": request.authorization_id,
                "state": "proposed",
                "files": [],
            }
            self._save(run.run_id, journal)
        request = self.gate.get_operation_request(journal["authorization_id"])
        if journal.get("manifest_ref") != run.inputs.get(
            "manifest_ref"
        ) or request != self._request(run, manifest, request.capability_inputs):
            raise WorkbenchError("Original proposal authorization binding differs.")
        return journal, request

    def _preflight(self, manifest):
        for item in manifest["files"]:
            if self._observe(item["path"]) != {
                "exists": item["expected_exists"],
                "sha256": item["before_sha256"],
            }:
                raise WorkbenchConflict(
                    "A file changed after proposal review; create a new proposal."
                )

    def _observe(self, path):
        target = self.workbench._write_target(path)
        if target.relative_to(self.root).as_posix() != path:
            raise WorkbenchError("The approved target path changed.")
        if not target.is_file():
            return {"exists": False, "sha256": ""}
        if target.stat().st_size > _MAX_FILE_BYTES:
            raise WorkbenchError("Observed file exceeds the proposal bound.")
        data = target.read_bytes()
        if len(data) > _MAX_FILE_BYTES:
            raise WorkbenchError("Observed file exceeds the proposal bound.")
        return {"exists": True, "sha256": _digest(data)}

    def _reconcile_locked(self, run, manifest, journal, request):
        observed = []
        errors = []
        for item in manifest["files"]:
            try:
                observed.append({"path": item["path"], **self._observe(item["path"])})
            except (OSError, WorkbenchError):
                errors.append(
                    {
                        "path": item["path"],
                        "error": "Fresh file observation is unavailable.",
                    }
                )
        expected = [
            {"path": item["path"], "exists": True, "sha256": item["after_sha256"]}
            for item in manifest["files"]
        ]
        with self.gate.store.operation_transaction() as db:
            admitted = (
                db.execute(
                    "SELECT 1 FROM governance_lease_consumption WHERE execution_id=?",
                    (request.authorization_id,),
                ).fetchone()
                is not None
            )
        intentions = journal.get("files") or []
        complete_intent = len(intentions) == len(manifest["files"]) and all(
            intention.get("path") == item["path"]
            and intention.get("before_sha256") == item["before_sha256"]
            and intention.get("after_sha256") == item["after_sha256"]
            for intention, item in zip(intentions, manifest["files"])
        )
        result = DeterministicVerifier().verify(
            {"checksum": _digest(_canonical(observed))},
            {"checksum": _digest(_canonical(expected))},
        )
        verdict = (
            "UNKNOWN"
            if errors or not admitted or not complete_intent
            else "MATCH"
            if result.passed
            else "MISMATCH"
        )
        observation_ref = self._artifact(
            _canonical(
                {
                    "schema": "nous.workspace-observation/v1",
                    "proposal_id": run.run_id,
                    "authorization_id": request.authorization_id,
                    "workspace_resource": self.resource_id,
                    "manifest_ref": run.inputs["manifest_ref"],
                    "observed_at": _now(),
                    "files": observed,
                    "errors": errors,
                }
            ),
            ArtifactType.EVIDENCE,
            "workspace-observation.json",
            depends_on=(run.inputs["manifest_ref"],),
        )
        verification = {
            "schema": "nous.workspace-verification/v1",
            "proposal_id": run.run_id,
            "authorization_id": request.authorization_id,
            "manifest_ref": run.inputs["manifest_ref"],
            "observation_ref": observation_ref,
            "verdict": verdict,
            "checked_at": _now(),
            "admission_recorded": admitted,
            "complete_effect_intent": complete_intent,
            "deterministic": asdict(result),
        }
        verification_ref = self._artifact(
            _canonical(verification),
            ArtifactType.VERIFICATION_RESULT,
            "workspace-verification.json",
            depends_on=(observation_ref, run.inputs["manifest_ref"]),
        )
        journal.update(
            state="applied"
            if verdict == "MATCH"
            else "unknown"
            if verdict == "UNKNOWN"
            else "mismatch",
            verification={**verification, "verification_ref": verification_ref},
            error=""
            if verdict == "MATCH"
            else "Original workspace attempt requires reconciliation; it cannot be replayed.",
        )
        self.gate.record_operation_evidence(
            request.authorization_id,
            "workspace.effect.verified",
            verdict=verdict,
            observation_ref=observation_ref,
            verification_ref=verification_ref,
        )
        self._save(run.run_id, journal)
        return journal

    def _artifact(self, data, kind, name, *, depends_on=()):
        stored = self.artifacts.store_bytes(
            data,
            artifact_type=kind,
            name=name,
            produced_by="workspace.proposal",
            depends_on=depends_on,
        )
        ref = stored["artifact"]["digest"]
        self.artifacts.pin(ref, reason="workspace.proposal")
        return ref

    def _cas_bytes(self, ref, *, limit=_MAX_FILE_BYTES):
        record = self.artifacts.get(ref)
        if record is not None and record.size_bytes > limit:
            raise WorkbenchError("Proposal Artifact exceeds its byte bound.")
        content = self.artifacts.resolve(ref).read_bytes()
        if len(content) > limit:
            raise WorkbenchError("Proposal Artifact exceeds its byte bound.")
        return content

    def _save(self, run_id, journal):
        self.store.checkpoint(run_id, _JOURNAL, journal)

    @staticmethod
    def _output(run, journal, request):
        return {
            "proposal_id": run.run_id,
            "manifest_ref": run.inputs["manifest_ref"],
            "authorization_id": request.authorization_id,
            "work_id": request.work_id,
            "state": journal["state"].upper(),
            "applied": journal["state"] == "applied",
            "verification": journal.get("verification", {}),
            "execution_scope": "runtime-service",
            "kernel_traversed": False,
        }

    def _view(self, run, manifest, journal, request, *, include_diff=True):
        approval_id = "apr_" + request.authorization_id[4:]
        approval = self.gate.store.get_approval_request(approval_id)
        status = str((approval or {}).get("status") or "MISSING")
        files = []
        intentions = {item["path"]: item for item in journal.get("files") or []}
        for item in manifest["files"]:
            try:
                current = self._observe(item["path"])
            except (OSError, WorkbenchError):
                current = {"exists": None, "sha256": ""}
            diff = ""
            if include_diff:
                before = (
                    self._cas_bytes(item["before_ref"]) if item["before_ref"] else b""
                )
                after = self._cas_bytes(item["after_ref"])
                diff = "\n".join(
                    difflib.unified_diff(
                        before.decode("utf-8").splitlines(),
                        after.decode("utf-8").splitlines(),
                        fromfile="a/" + item["path"],
                        tofile="b/" + item["path"],
                        lineterm="",
                    )
                )
            files.append(
                {
                    **item,
                    "diff": diff,
                    "current_exists": current["exists"],
                    "current_sha256": current["sha256"],
                    "backup_path": intentions.get(item["path"], {}).get(
                        "backup_path", ""
                    ),
                }
            )
        return {
            **self._output(run, journal, request),
            "ok": True,
            "workflow_state": run.state.value,
            "cancellation_requested": run.cancellation_requested,
            "title": manifest["title"],
            "subject_id": manifest["subject_id"],
            "source_work_id": manifest["source_work_id"],
            "agent_session_id": manifest["agent_session_id"],
            "plan_id": manifest["plan_id"],
            "requested_by": manifest.get("requested_by", ""),
            "source_request_id": manifest.get("source_request_id", ""),
            "created_at": manifest["created_at"],
            "resource_id": self.resource_id,
            "files": files,
            "detail_level": "full" if include_diff else "summary",
            "file_count": len(files),
            "total_size_bytes": sum(item["size_bytes"] for item in files),
            "approval_request_id": approval_id if approval else "",
            "approval_status": status,
            "approval_required": status == "PENDING",
            "recovery_required": journal["state"]
            in {"unknown", "mismatch", "applying"},
            "error": journal.get("error") or run.error,
        }


__all__ = ["WorkspaceProposalService"]

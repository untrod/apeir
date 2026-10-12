"""Real file edits retain the original Workflow, authority and evidence on recovery."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from nous_runtime.core.errors import ArtifactError
from nous_runtime.governance import (
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceStore,
)
from nous_runtime.governance.cli import _build_context
from nous_runtime.workspace.proposals import WorkspaceProposalService
from nous_runtime.workspace.workbench import (
    DeveloperWorkbench,
    WorkbenchConflict,
    WorkbenchError,
)
from nous_runtime.workflow.store import WorkflowBindingError


@pytest.fixture
def service(tmp_path):
    gate = ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / ".nous"))
    return WorkspaceProposalService(tmp_path, gate=gate)


def prepare(service, *, files=None):
    return service.prepare(
        files
        if files is not None
        else [
            {"path": "first.txt", "content": "first replacement\n"},
            {"path": "second.txt", "content": "second replacement\n"},
        ],
        subject_id="workspace-test-agent",
    )


def approve(service, proposal):
    return service.broker.respond_operation(
        proposal["approval_request_id"], "approve", _build_context(), gate=service.gate
    )


def consumed(service):
    with service.gate.store.operation_transaction() as db:
        return db.execute(
            "SELECT COUNT(*) FROM governance_lease_consumption"
        ).fetchone()[0]


def test_explicit_workspace_initializes_one_authority_outside_cwd(
    tmp_path, monkeypatch
):
    from nous_runtime.governance import get_gate

    outside = tmp_path / "outside"
    selected = tmp_path / "selected"
    outside.mkdir()
    selected.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("NOUS_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", None)
    original = WorkspaceProposalService(selected)
    assert (
        Path(get_gate().store.db_path).resolve() == selected / ".nous" / "governance.db"
    )
    assert original.gate is get_gate()
    proposal = prepare(original)
    approve(original, proposal)
    assert original.apply(proposal["proposal_id"])["applied"]
    assert not (outside / ".nous" / "governance.db").exists()


def test_existing_authority_cannot_be_silently_retargeted(
    service, tmp_path, monkeypatch
):
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", service.gate)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="another workspace"):
        WorkspaceProposalService(other)
    assert (
        service.gate
        is __import__("nous_runtime.governance", fromlist=["get_gate"]).get_gate()
    )


def test_default_governance_store_matches_host_selected_workspace(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path / "selected"))
    assert (
        Path(GovernanceStore().db_path).resolve()
        == tmp_path / "selected" / ".nous" / "governance.db"
    )


def test_registered_secret_never_enters_proposal_content_artifacts(service):
    from nous_runtime.core.redaction import register_sensitive_value

    fake_material = "APEIR_FAKE_ONLY_PROPOSAL_SECRET_f934c18a"
    register_sensitive_value(fake_material)
    with pytest.raises(WorkbenchError, match="Credential material"):
        prepare(
            service,
            files=[
                {"path": "public.py", "content": "value = '" + fake_material + "'\n"}
            ],
        )
    assert service.list()["total"] == 0
    for path in (service.root / ".nous").rglob("*"):
        if path.is_file():
            assert fake_material.encode() not in path.read_bytes()


@pytest.mark.parametrize("before", [b"original\n", b"original\r\n"])
def test_listing_defers_diffs_but_still_verifies_artifact_bytes(
    service, monkeypatch, before
):
    (service.root / "first.txt").write_bytes(before)
    proposal = prepare(
        service,
        files=[
            {
                "path": "first.txt",
                "content": "after\n",
                "expected_sha256": hashlib.sha256(before).hexdigest(),
            }
        ],
    )

    def forbidden_diff(*args, **kwargs):
        pytest.fail("List must not build every file diff")

    with monkeypatch.context() as patch:
        patch.setattr(
            "nous_runtime.workspace.proposals.difflib.unified_diff", forbidden_diff
        )
        listed = service.list()["proposals"][0]
        assert listed["detail_level"] == "summary"
        assert listed["files"][0]["diff"] == ""
    assert "-original" in service.read(proposal["proposal_id"])["files"][0]["diff"]
    replacement = service.artifacts.resolve(proposal["files"][0]["after_ref"])
    replacement.write_bytes(b"tampered")
    with pytest.raises(ArtifactError):
        service.list()


@pytest.mark.parametrize("before", [b"original\n", b"original\r\n"])
def test_review_original_bytes_and_restart_use_existing_durable_owners(service, before):
    (service.root / "first.txt").write_bytes(before)
    proposal = prepare(
        service,
        files=[
            {
                "path": "first.txt",
                "content": " first replacement\n ",
                "expected_sha256": hashlib.sha256(before).hexdigest(),
            },
            {"path": "empty.txt", "content": "", "expected_exists": False},
        ],
    )
    assert proposal["workflow_state"] == "waiting_approval"
    assert proposal["state"] == "PROPOSED" and proposal["approval_required"]
    assert (service.root / "first.txt").read_bytes() == before
    assert not (service.root / "empty.txt").exists()
    assert proposal["files"][0]["before_ref"].startswith("sha256:")
    assert "-original" in proposal["files"][0]["diff"]
    assert consumed(service) == 0
    reloaded = WorkspaceProposalService(service.root, gate=service.gate)
    assert reloaded.list()["proposals"][0]["proposal_id"] == proposal["proposal_id"]
    approve(reloaded, proposal)
    applied = reloaded.apply(proposal["proposal_id"])
    assert applied["ok"] and applied["state"] == "APPLIED"
    assert applied["proposal_id"] == proposal["proposal_id"]
    assert applied["authorization_id"] == proposal["authorization_id"]
    assert applied["workflow_state"] == "completed"
    assert (service.root / "first.txt").read_bytes() == b" first replacement\n "
    assert (service.root / "empty.txt").is_file()
    assert (service.root / applied["files"][0]["backup_path"]).read_bytes() == before
    verification = applied["verification"]
    assert verification["verdict"] == "MATCH"
    assert verification["deterministic"]["checks_run"] == 1
    assert reloaded.artifacts.verify(verification["observation_ref"])
    assert reloaded.artifacts.verify(verification["verification_ref"])
    assert consumed(service) == 1
    assert applied["execution_scope"] == "runtime-service"
    assert applied["kernel_traversed"] is False
    checkpoints = reloaded.store.checkpoints(proposal["proposal_id"])
    assert checkpoints["apply"]["status"] == "completed"
    assert checkpoints["apply:effects"]["state"] == "applied"


def test_pending_and_denied_proposals_never_mutate(service):
    proposal = prepare(service)
    assert not service.apply(proposal["proposal_id"])["ok"]
    assert consumed(service) == 0
    service.broker.respond_operation(
        proposal["approval_request_id"], "deny", _build_context(), gate=service.gate
    )
    denied = service.apply(proposal["proposal_id"])
    assert denied["state"] == "DENIED"
    assert denied["approval_status"] == "DENIED"
    assert not (service.root / "first.txt").exists()
    assert not (service.root / "second.txt").exists()
    assert consumed(service) == 0


@pytest.mark.parametrize("subject_type", ["model", "agent", "service", "user"])
def test_self_declared_identity_cannot_approve_original_proposal(service, subject_type):
    proposal = prepare(service)
    context = AuthorizationContext(
        subject_type=subject_type,
        subject_id="claimed-human",
        authn_method="cli_os_user",
        authn_confidence=1,
    )
    with pytest.raises(PermissionError):
        service.broker.respond_operation(
            proposal["approval_request_id"], "approve", context, gate=service.gate
        )
    assert service.read(proposal["proposal_id"])["approval_status"] == "PENDING"
    assert consumed(service) == 0


def test_stale_later_file_preflight_prevents_every_replacement(service):
    proposal = prepare(service)
    approve(service, proposal)
    (service.root / "second.txt").write_text("outside editor")
    result = service.apply(proposal["proposal_id"])
    assert result["state"] == "CONFLICT" and not result["ok"]
    assert not (service.root / "first.txt").exists()
    assert (service.root / "second.txt").read_text() == "outside editor"
    assert consumed(service) == 0


def test_normalized_line_endings_cannot_substitute_for_original_byte_version(service):
    before = b"original\r\n"
    target = service.root / "first.txt"
    target.write_bytes(before)
    with pytest.raises(WorkbenchConflict):
        prepare(
            service,
            files=[
                {
                    "path": "first.txt",
                    "content": "after\n",
                    "expected_sha256": hashlib.sha256(b"original\n").hexdigest(),
                }
            ],
        )
    assert target.read_bytes() == before
    assert service.list()["total"] == 0
    assert consumed(service) == 0


def test_changed_replacement_cas_cannot_reuse_approval(service):
    proposal = prepare(service)
    approve(service, proposal)
    replacement = service.artifacts.resolve(proposal["files"][0]["after_ref"])
    replacement.write_bytes(b"other replacement\n")
    with pytest.raises(ArtifactError):
        service.apply(proposal["proposal_id"])
    assert not (service.root / "first.txt").exists()
    assert consumed(service) == 0


def test_changed_workflow_manifest_cannot_reuse_original_authority(service):
    proposal = prepare(service)
    other = prepare(service, files=[{"path": "third.txt", "content": "third"}])
    approve(service, proposal)
    run = service.store.get_run(proposal["proposal_id"])
    run.inputs["manifest_ref"] = other["manifest_ref"]
    with pytest.raises(WorkflowBindingError, match="binding changed"):
        service.store.save_run(run)
    assert not (service.root / "third.txt").exists()
    assert consumed(service) == 0


@pytest.mark.parametrize(
    "path", ["../outside.txt", ".git/config", "nested/.NOUS/secret", "workspace.json"]
)
def test_private_or_escaped_proposals_fail_before_publication(service, path):
    with pytest.raises(WorkbenchError):
        prepare(service, files=[{"path": path, "content": "fake"}])
    assert service.list()["total"] == 0
    assert not service.artifacts.list()


def test_proposal_rejects_duplicate_bounds_and_absent_vs_empty(service):
    (service.root / "empty.txt").write_text("")
    with pytest.raises(WorkbenchConflict):
        prepare(
            service,
            files=[{"path": "empty.txt", "content": "new", "expected_exists": False}],
        )
    for files in (
        [{"path": "a.txt", "content": "x"}, {"path": "./a.txt", "content": "y"}],
        [{"path": str(index), "content": "x"} for index in range(25)],
        [{"path": "too-large.txt", "content": "x" * (1024 * 1024 + 1)}],
        [{"path": str(index), "content": "x" * (1024 * 1024)} for index in range(3)],
    ):
        with pytest.raises(WorkbenchError):
            prepare(service, files=files)
    assert service.list()["total"] == 0


def test_concurrent_original_apply_consumes_one_admission(service, monkeypatch):
    proposal = prepare(service)
    approve(service, proposal)
    calls = []
    original = DeveloperWorkbench._write_file

    def record(self, *args, **kwargs):
        calls.append(args[0])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DeveloperWorkbench, "_write_file", record)
    other = WorkspaceProposalService(service.root, gate=service.gate)
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(owner.apply, proposal["proposal_id"])
            for owner in (service, other)
        ]
        results = [future.result() for future in futures]
    assert all(result["ok"] for result in results)
    assert calls == ["first.txt", "second.txt"]
    assert consumed(service) == 1


@pytest.mark.parametrize(
    "failed_path,expected_verdict", [("first.txt", "UNKNOWN"), ("second.txt", "MATCH")]
)
def test_effect_then_evidence_failure_reconciles_original_without_replay(
    service, monkeypatch, failed_path, expected_verdict
):
    proposal = prepare(service)
    approve(service, proposal)
    original = service.workbench._emit_change

    def fail_after_effect(run_id, task_id, change, **kwargs):
        if change["path"] == failed_path:
            raise OSError("controlled lost effect acknowledgement")
        return original(run_id, task_id, change, **kwargs)

    monkeypatch.setattr(service.workbench, "_emit_change", fail_after_effect)
    lost = service.apply(proposal["proposal_id"])
    assert lost["state"] == "UNKNOWN"
    assert (service.root / "first.txt").read_text() == "first replacement\n"
    before_recovery = {
        path.name: path.read_bytes() for path in service.root.glob("*.txt")
    }
    reloaded = WorkspaceProposalService(service.root, gate=service.gate)

    def no_replay(*args, **kwargs):
        pytest.fail("Recovery attempted another file effect")

    monkeypatch.setattr(reloaded.workbench, "_write_file", no_replay)
    reconciled = reloaded.reconcile(proposal["proposal_id"])
    assert reconciled["verification"]["verdict"] == expected_verdict
    assert reconciled["ok"] is (expected_verdict == "MATCH")
    assert (
        reloaded.apply(proposal["proposal_id"])["verification"]["verdict"]
        == expected_verdict
    )
    assert {
        path.name: path.read_bytes() for path in service.root.glob("*.txt")
    } == before_recovery
    assert consumed(service) == 1


def test_missing_admission_cannot_be_repaired_from_desired_file_bytes(service):
    proposal = prepare(service)
    run = service.store.get_run(proposal["proposal_id"])
    journal = service.store.checkpoints(run.run_id)["apply:effects"]
    journal.update(
        state="applying",
        files=[
            {key: item[key] for key in ("path", "before_sha256", "after_sha256")}
            for item in proposal["files"]
        ],
    )
    service.store.checkpoint(run.run_id, "apply:effects", journal)
    (service.root / "first.txt").write_text("first replacement\n")
    (service.root / "second.txt").write_text("second replacement\n")
    reconciled = service.reconcile(proposal["proposal_id"])
    assert reconciled["verification"]["verdict"] == "UNKNOWN"
    assert not reconciled["applied"] and consumed(service) == 0


def test_changed_bytes_after_apply_produce_mismatch_and_never_replay(
    service, monkeypatch
):
    proposal = prepare(service)
    approve(service, proposal)
    assert service.apply(proposal["proposal_id"])["ok"]
    (service.root / "second.txt").write_text("later external edit")
    monkeypatch.setattr(
        service.workbench,
        "_write_file",
        lambda *args, **kwargs: pytest.fail(
            "Reconciliation rewrote an externally changed file"
        ),
    )
    result = service.reconcile(proposal["proposal_id"])
    assert not result["ok"] and result["state"] == "MISMATCH"
    assert result["verification"]["verdict"] == "MISMATCH"
    assert (service.root / "second.txt").read_text() == "later external edit"
    assert consumed(service) == 1


def test_fresh_observation_failure_is_unknown(service, monkeypatch):
    proposal = prepare(service)
    approve(service, proposal)
    assert service.apply(proposal["proposal_id"])["ok"]
    original = service._observe

    def unavailable(path):
        if path == "second.txt":
            raise OSError("controlled independent observation failure")
        return original(path)

    monkeypatch.setattr(service, "_observe", unavailable)
    result = service.reconcile(proposal["proposal_id"])
    assert result["verification"]["verdict"] == "UNKNOWN"
    assert not result["ok"] and consumed(service) == 1


def test_changed_trusted_metadata_between_files_blocks_later_effect(
    service, monkeypatch
):
    proposal = prepare(service)
    approve(service, proposal)
    original = service.workbench._write_file

    def change_metadata(*args, **kwargs):
        result = original(*args, **kwargs)
        contract = service.gate.operation_contracts.get("project.write_file").unwrap()
        contract.observation_method = "changed-trusted-observer"
        return result

    monkeypatch.setattr(service.workbench, "_write_file", change_metadata)
    result = service.apply(proposal["proposal_id"])
    assert result["state"] == "UNKNOWN"
    assert (service.root / "first.txt").exists()
    assert not (service.root / "second.txt").exists()
    assert consumed(service) == 1


def test_workbench_same_expected_hash_serializes_cooperating_writers(
    tmp_path, monkeypatch
):
    target = tmp_path / "shared.txt"
    target.write_text("original")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    entered, release, second_started, second_done = Event(), Event(), Event(), Event()
    import nous_runtime.workspace.workbench as module

    original = module.os.replace

    def held_replace(source, destination):
        if Path(source).name.startswith(".nous-workbench-") and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(source, destination)

    monkeypatch.setattr(module.os, "replace", held_replace)

    def write(value, *, second=False):
        if second:
            second_started.set()
        try:
            return DeveloperWorkbench(tmp_path).write_file(
                "shared.txt", value, expected_sha256=expected
            )["ok"]
        except WorkbenchConflict:
            return False
        finally:
            if second:
                second_done.set()

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(write, "first")
        assert entered.wait(5)
        second = pool.submit(write, "second", second=True)
        assert second_started.wait(5)
        assert not second_done.wait(0.1)
        release.set()
        assert first.result() is True
        assert second.result() is False
    assert target.read_text() == "first"


def test_service_rejects_another_workspace_authority(tmp_path):
    root = tmp_path / "selected"
    root.mkdir()
    gate = ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / "other"))
    with pytest.raises(WorkbenchError, match="authority differ"):
        WorkspaceProposalService(root, gate=gate)


def test_manifest_and_verification_do_not_persist_replacement_as_workflow_parameters(
    service,
):
    proposal = prepare(service)
    run = service.store.get_run(proposal["proposal_id"])
    assert "first replacement" not in json.dumps(service.store._run_dict(run))
    approval = service.gate.store.get_approval_request(proposal["approval_request_id"])
    request = service.gate.get_operation_request(proposal["authorization_id"])
    assert "first replacement" not in json.dumps(approval)
    assert proposal["manifest_ref"] in request.input_artifacts
    assert request.expected_effect["checksum"]


@pytest.mark.parametrize("fence", ["expired", "revoked"])
def test_current_authority_fences_approved_original_before_first_effect(service, fence):
    proposal = prepare(service)
    approve(service, proposal)
    with service.gate.store.operation_transaction() as db:
        if fence == "expired":
            db.execute("UPDATE governance_leases SET expires_at='2000-01-01T00:00:00Z'")
        else:
            db.execute(
                "INSERT INTO governance_revocations (revocation_id,target_id,target_type,reason,revoked_by,revoked_at,revocation_json) VALUES(?,?,?,?,?,?,?)",
                (
                    "revocation-test",
                    proposal["authorization_id"],
                    "operation",
                    "test",
                    "human",
                    "2026-01-01",
                    "{}",
                ),
            )
    result = service.apply(proposal["proposal_id"])
    assert result["state"] == "DENIED" and not result["applied"]
    assert not (service.root / "first.txt").exists()
    assert consumed(service) == 0


def test_lost_final_response_after_verification_reuses_original_result(
    service, monkeypatch
):
    proposal = prepare(service)
    approve(service, proposal)

    def lost_response(*args, **kwargs):
        raise OSError("controlled lost final response")

    monkeypatch.setattr(service, "read", lost_response)
    with pytest.raises(OSError, match="lost final response"):
        service.apply(proposal["proposal_id"])
    reloaded = WorkspaceProposalService(service.root, gate=service.gate)
    monkeypatch.setattr(
        reloaded.workbench,
        "_write_file",
        lambda *args, **kwargs: pytest.fail("Lost response triggered replay"),
    )
    result = reloaded.reconcile(proposal["proposal_id"])
    assert result["ok"] and result["proposal_id"] == proposal["proposal_id"]
    assert result["verification"]["verdict"] == "MATCH"
    assert consumed(service) == 1


def test_hard_interruption_after_last_replace_reconciles_only(service, monkeypatch):
    proposal = prepare(service)
    approve(service, proposal)
    original = service.workbench._emit_change

    def interrupt(run_id, task_id, change, **kwargs):
        if change["path"] == "second.txt":
            raise SystemExit("controlled hard interruption")
        return original(run_id, task_id, change, **kwargs)

    monkeypatch.setattr(service.workbench, "_emit_change", interrupt)
    with pytest.raises(SystemExit, match="hard interruption"):
        service.apply(proposal["proposal_id"])
    assert (
        service.store.checkpoints(proposal["proposal_id"])["apply:effects"]["state"]
        == "applying"
    )
    reloaded = WorkspaceProposalService(service.root, gate=service.gate)
    monkeypatch.setattr(
        reloaded.workbench,
        "_write_file",
        lambda *args, **kwargs: pytest.fail("Hard interruption triggered replay"),
    )
    result = reloaded.reconcile(proposal["proposal_id"])
    assert result["ok"] and result["verification"]["verdict"] == "MATCH"
    assert result["workflow_state"] == "completed"
    assert consumed(service) == 1


def test_verification_artifact_failure_cannot_publish_completion(service, monkeypatch):
    proposal = prepare(service)
    approve(service, proposal)
    original = service._artifact

    def unavailable(data, kind, name, **kwargs):
        if name == "workspace-verification.json":
            raise OSError("controlled verification storage failure")
        return original(data, kind, name, **kwargs)

    monkeypatch.setattr(service, "_artifact", unavailable)
    result = service.apply(proposal["proposal_id"])
    assert result["state"] == "UNKNOWN" and not result["applied"]
    assert result["workflow_state"] == "failed"
    reloaded = WorkspaceProposalService(service.root, gate=service.gate)
    monkeypatch.setattr(
        reloaded.workbench,
        "_write_file",
        lambda *args, **kwargs: pytest.fail("Missing verification triggered replay"),
    )
    result = reloaded.reconcile(proposal["proposal_id"])
    assert result["ok"] and result["verification"]["verdict"] == "MATCH"
    assert consumed(service) == 1

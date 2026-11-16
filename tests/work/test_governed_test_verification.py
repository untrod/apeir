"""Source contracts for canonical receipts; VM processes are explicit fixtures."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from nous_runtime.capability.runtime_executor import execute_runtime_capability
from nous_runtime.work import ModelWorkDeliberator, WorkHarness
from nous_runtime.work.deliberation import _execution_progress
from nous_runtime.work.models import work_timestamp
from tests.work.test_work_deliberation import StubFacade


@pytest.fixture
def original_test(tmp_path, monkeypatch):
    harness = WorkHarness(tmp_path)
    work = harness.create("Fix the code in this repository")
    revision = work.plan.revision
    work.observations.extend(
        [
            {
                "kind": "tool",
                "tool": "read_file",
                "ok": True,
                "action_sequence": 1,
                "plan_revision": revision,
                "result": {"path": "example.py", "sha256": "old"},
            },
            {
                "kind": "tool",
                "tool": "patch_file",
                "ok": True,
                "action_sequence": 2,
                "plan_revision": revision,
                "observed_at": work_timestamp(),
                "result": {
                    "change": {
                        "path": "example.py",
                        "before_digest": "old",
                        "after_digest": "new",
                    }
                },
            },
        ]
    )
    monkeypatch.setattr(
        "nous_runtime.workspace.workbench.run_process_strict",
        lambda *a, **kw: SimpleNamespace(
            ok=True,
            returncode=0,
            stdout="",
            stderr="Ran 2 tests in 0.01s\n\nOK\n",
            runtime_seconds=0.01,
            limit_exceeded=False,
            sandbox_id="explicit-vm-fixture",
            input_snapshot_sha256="a" * 64,
            availability_state="available",
            security_grade="strong_vm",
            enforced_controls=("fixture",),
            unenforced_controls=(),
        ),
    )
    result = execute_runtime_capability(
        "project.run_tests", {"target": "."}, workspace_root=tmp_path
    )
    assert result["test_outcome"] == "PASS"
    work.observations.append(
        {
            "kind": "tool",
            "tool": "run_project_tests",
            "ok": True,
            "action_sequence": 3,
            "plan_revision": revision,
            "result": result,
        }
    )
    harness.persist_progress(work, "work.observing", {})
    return harness, work, result


def test_fixed_test_profile_and_original_receipt_advance_verification(original_test):
    harness, work, result = original_test
    progress = _execution_progress(harness.context_for(work))
    assert result["artifact_id"] and result["artifact_digest"]
    assert progress["execution_started"] is True
    assert progress["tests_run"] is True
    assert progress["diff_reviewed"] is False
    reopened = WorkHarness(harness.root).require(work.run_id)
    assert _execution_progress(harness.context_for(reopened))["tests_run"] is True


def test_a_later_uncertain_test_cannot_reuse_an_earlier_passing_receipt(original_test):
    harness, work, _ = original_test
    work.observations.append(
        {
            "kind": "tool",
            "tool": "run_project_tests",
            "ok": False,
            "action_sequence": 4,
            "plan_revision": work.plan.revision,
            "result": {"ok": False, "error": "Original response lost; do not replay"},
        }
    )
    harness.persist_progress(work, "work.recovery.required", {})
    assert _execution_progress(harness.context_for(work))["tests_run"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        "model_claim",
        "wrong_work",
        "wrong_workspace",
        "wrong_revision",
        "artifact_bytes",
        "receipt_before_edit",
        "missing_snapshot",
        "changed_counts",
    ],
)
def test_fixed_test_proof_rejects_missing_stale_foreign_and_tampered_evidence(
    original_test, tamper, tmp_path
):
    harness, work, result = original_test
    context = harness.context_for(work)
    if tamper == "artifact_bytes":
        from nous_runtime.artifact import ContentAddressedArtifactStore

        ContentAddressedArtifactStore(tmp_path / ".nous/artifacts").resolve(
            result["artifact_digest"]
        ).write_bytes(b"tampered")
    elif tamper == "wrong_work":
        other = harness.create("Inspect a separate task")
        context = replace(context, run_id=other.run_id)
    elif tamper == "wrong_workspace":
        context = replace(
            context,
            workspace={**context.workspace, "execution_root": str(tmp_path / "other")},
        )
    elif tamper == "wrong_revision":
        context = replace(
            context, plan={**context.plan, "revision": context.plan["revision"] + 1}
        )
    else:
        rows = deepcopy(list(context.recent_observations))
        if tamper == "model_claim":
            rows[-1]["result"] = {
                "ok": True,
                "test_outcome": "PASS",
                "exit_code": 0,
                "security_grade": "strong_vm",
            }
        elif tamper == "receipt_before_edit":
            rows[1]["observed_at"] = "2099-01-01T00:00:00Z"
        elif tamper == "missing_snapshot":
            rows[-1]["result"].pop("input_snapshot_sha256")
        elif tamper == "changed_counts":
            rows[-1]["result"]["test_counts"] = {"run": 999, "passed": 999}
        work.observations[:] = rows
        harness.persist_progress(work, "work.observing", {})
        context = harness.context_for(work)
    assert _execution_progress(context)["tests_run"] is False


def test_model_uses_available_fixed_test_profile_instead_of_an_unavailable_terminal(
    tmp_path,
):
    harness = WorkHarness(tmp_path)
    work = harness.create("Fix the code in this repository")
    work.observations.extend(
        [
            {
                "kind": "tool",
                "tool": "read_file",
                "ok": True,
                "result": {"path": "example.py"},
            },
            {
                "kind": "tool",
                "tool": "patch_file",
                "ok": True,
                "result": {
                    "change": {
                        "path": "example.py",
                        "before_digest": "old",
                        "after_digest": "new",
                    }
                },
            },
        ]
    )
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
    from nous_runtime.tools import ToolCatalog

    tools = ToolCatalog()
    tools.register_runtime(WorkspaceToolRuntime(str(tmp_path), allow_mutations=True))
    assert "shell_start" not in {row["tool_id"] for row in tools.discover()}
    work.loaded_tools.update(
        {row["tool_id"]: row for row in tools.expand("shell")["tools"]}
    )
    facade = StubFacade(
        None,
        tool_calls=(
            {
                "id": "fixed-test",
                "function": {
                    "name": "run_project_tests",
                    "arguments": '{"profile":"python-unittest","target":".","timeout_seconds":30}',
                },
            },
        ),
    )
    decision = ModelWorkDeliberator(facade)(harness.context_for(work))
    assert decision.phase == "VERIFY" and decision.tool_name == "run_project_tests"
    assert [tool["function"]["name"] for tool in facade.requests[0].tools] == [
        "run_project_tests"
    ]
    assert decision.tool_arguments["profile"] == "python-unittest"
    assert "host-shell fallback" in facade.requests[0].messages[0]["content"]


def test_fixed_test_selection_does_not_accept_a_model_completion_claim(tmp_path):
    harness = WorkHarness(tmp_path)
    work = harness.create("Fix the code in this repository")
    work.loaded_tools["run_project_tests"] = {
        "tool_id": "run_project_tests",
        "effect_class": "execute",
        "input_schema": {"type": "object"},
    }
    work.observations.append(
        {
            "kind": "tool",
            "tool": "patch_file",
            "ok": True,
            "result": {"change": {"path": "example.py"}},
        }
    )
    facade = StubFacade(
        {"status": "complete", "summary": "Tests passed", "confidence": "high"}
    )
    with pytest.raises(RuntimeError, match="requires exactly one native tool call"):
        ModelWorkDeliberator(facade)(harness.context_for(work))
    assert _execution_progress(harness.context_for(work))["tests_run"] is False


@pytest.fixture
def failed_readonly_test(tmp_path, monkeypatch, request):
    from nous_runtime.events import RunState
    from nous_runtime.governance.cli import _build_context
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
    from nous_runtime.tools import ToolCatalog
    from nous_runtime.work.loop import AgentLoop

    mode = getattr(request, "param", "failure")
    (tmp_path / "tests").mkdir()
    harness = WorkHarness(tmp_path)
    work = harness.create("Run project tests and inspect their original result")
    monkeypatch.setattr(
        "nous_runtime.workspace.workbench.run_process_strict",
        lambda *a, **kw: SimpleNamespace(
            ok=False,
            returncode=1,
            stdout="",
            stderr="Ran 2 tests in 0.01s\n\nFAILED (failures=1)\n",
            runtime_seconds=0.01,
            limit_exceeded="timeout" if mode == "timeout" else "",
            sandbox_id="explicit-failed-vm-fixture",
            input_snapshot_sha256="b" * 64,
            availability_state="available",
            security_grade="resource_only" if mode == "weak_backend" else "strong_vm",
            enforced_controls=("fixture",),
            unenforced_controls=(),
        ),
    )
    arguments = {"profile": "python-unittest", "target": "tests", "timeout_seconds": 30}
    result = execute_runtime_capability(
        "project.run_tests", arguments, workspace_root=tmp_path
    )
    assert result["test_outcome"] == "FAIL" and result["ok"] is False
    digest = AgentLoop._arguments_digest(arguments)
    work.observations.append(
        {
            "kind": "tool",
            "tool": "run_project_tests",
            "ok": False,
            "action_sequence": 1,
            "arguments_digest": digest,
            "plan_revision": work.plan.revision if work.plan else 0,
            "observed_at": work_timestamp(),
            "result": result,
        }
    )
    work.action_sequence = 1
    work.goal.block("Original execution outcome requires inspection")
    work.state = RunState.RECOVERY_REQUIRED
    work.pending_action = {
        "tool": "run_project_tests",
        "capability_id": "project.run_tests",
        "effect_class": "execute",
        "action_sequence": 1,
        "arguments_digest": digest,
        "recovery_policy": "kernel_or_manual",
    }
    harness.persist_progress(
        work, "work.recovery.required", {"automatic_replay": False}
    )
    owner = WorkspaceToolRuntime(
        str(tmp_path),
        allow_mutations=True,
        source_work_id=work.run_id,
        authorization_context=_build_context().to_dict(),
    )
    tools = ToolCatalog()
    tools.register_runtime(owner)
    work.loaded_tools.update(
        {row["tool_id"]: row for row in tools.discover(include_schemas=True)}
    )
    harness.persist_progress(
        work, "work.recovery.required", {"automatic_replay": False}
    )
    calls = []
    monkeypatch.setattr(
        "nous_runtime.workspace.workbench.run_process_strict",
        lambda *a, **kw: calls.append(a),
    )
    return harness, work, result, tools, owner, calls


def test_explicit_resume_observes_original_failed_readonly_test_without_reexecution(
    failed_readonly_test,
):
    from nous_runtime.events import RunState
    from nous_runtime.work.deliberation import verify_recorded_work

    harness, work, result, tools, _, calls = failed_readonly_test
    resumed = harness.resume(
        work.run_id,
        tools=tools,
        deliberator=lambda _: {
            "status": "ask_user",
            "summary": "The original suite failed; inspect it before proposing another edit",
        },
    )
    assert resumed.state is RunState.WAITING_USER
    assert resumed.run_id == work.run_id and resumed.pending_action == {}
    assert calls == []
    assert resumed.observations[-1]["result"]["test_outcome"] == "FAIL"
    assert verify_recorded_work(harness.context_for(resumed))["ok"] is False
    evidence = [
        event
        for event in harness.events.load_events(work.run_id)
        if event.event_type == "work.test.reconciled"
    ]
    assert len(evidence) == 1
    assert evidence[0].payload["test_run_id"] == result["run_id"]
    assert (
        evidence[0].payload["test_outcome"] == "FAIL"
        and evidence[0].payload["automatic_replay"] is False
    )


@pytest.mark.parametrize(
    "mode",
    [
        "artifact_bytes",
        "wrong_owner",
        "missing_auth",
        "wrong_arguments",
        "missing_run",
        "cancelled",
        "wrong_revision",
    ],
)
def test_failed_test_recovery_rejects_unbound_or_tampered_evidence(
    failed_readonly_test, mode
):
    from nous_runtime.events import RunState
    from nous_runtime.artifact import ContentAddressedArtifactStore

    harness, work, result, tools, owner, calls = failed_readonly_test
    if mode == "artifact_bytes":
        ContentAddressedArtifactStore(harness.root / ".nous/artifacts").resolve(
            result["artifact_digest"]
        ).write_bytes(b"tampered")
    elif mode == "wrong_owner":
        owner.source_work_id = "another-work"
    elif mode == "missing_auth":
        owner.authorization_context = {}
    elif mode == "wrong_arguments":
        work.pending_action["arguments_digest"] = "unrelated"
    elif mode == "missing_run":
        work.observations[-1]["result"]["run_id"] = "missing"
    elif mode == "wrong_revision":
        work.observations[-1]["plan_revision"] += 1
    if mode == "cancelled":
        harness.cancel(work.run_id)
    else:
        harness.persist_progress(work, "work.recovery.required", {})
    resumed = harness.resume(
        work.run_id,
        tools=tools,
        deliberator=lambda _: pytest.fail(
            "Uncertain evidence cannot reach deliberation"
        ),
    )
    assert resumed.state is (
        RunState.CANCELLED if mode == "cancelled" else RunState.RECOVERY_REQUIRED
    )
    assert calls == []


@pytest.mark.parametrize(
    "failed_readonly_test", ["timeout", "weak_backend"], indirect=True
)
def test_timeout_and_unqualified_backend_do_not_gain_readonly_recovery(
    failed_readonly_test,
):
    from nous_runtime.events import RunState

    harness, work, _, tools, _, calls = failed_readonly_test
    resumed = harness.resume(
        work.run_id,
        tools=tools,
        deliberator=lambda _: pytest.fail("Unqualified or incomplete execution"),
    )
    assert resumed.state is RunState.RECOVERY_REQUIRED and calls == []


def test_cancellation_during_failed_test_inspection_stops_continuation(
    failed_readonly_test, monkeypatch
):
    from nous_runtime.events import RunState

    harness, work, _, tools, _, calls = failed_readonly_test
    inspect = harness._completed_readonly_test_failure

    def cancel_after_inspection(snapshot, catalog):
        result = inspect(snapshot, catalog)
        assert result is not None
        harness.cancel(work.run_id)
        return result

    monkeypatch.setattr(
        harness, "_completed_readonly_test_failure", cancel_after_inspection
    )
    resumed = harness.resume(
        work.run_id,
        tools=tools,
        deliberator=lambda _: pytest.fail("Original Work was cancelled"),
    )
    assert resumed.state is RunState.CANCELLED and calls == []


def test_known_failed_validation_returns_to_source_inspection_before_another_edit(
    failed_readonly_test,
):
    harness, work, _, tools, _, calls = failed_readonly_test
    revision = work.plan.revision if work.plan else 0
    failed = work.observations[-1]
    failed["action_sequence"] = 3
    work.pending_action["action_sequence"] = 3
    work.action_sequence = 3
    work.observations[:0] = [
        {
            "kind": "tool",
            "tool": "read_file",
            "ok": True,
            "action_sequence": 1,
            "plan_revision": revision,
            "result": {"path": "example.py"},
        },
        {
            "kind": "tool",
            "tool": "patch_file",
            "ok": True,
            "action_sequence": 2,
            "plan_revision": revision,
            "result": {
                "change": {
                    "path": "example.py",
                    "before_digest": "old",
                    "after_digest": "new",
                }
            },
        },
    ]
    harness.persist_progress(work, "work.recovery.required", {})
    context = harness.context_for(work)
    assert _execution_progress(context)["phase"] == "INSPECT"
    facade = StubFacade(
        {
            "status": "continue",
            "summary": "Inspect the source relevant to the failed suite",
            "confidence": "high",
            "tool_name": "read_file",
            "tool_arguments": {"path": "example.py"},
        }
    )
    decision = ModelWorkDeliberator(facade)(context)
    assert decision.phase == "INSPECT" and decision.tool_name == "read_file"
    assert facade.requests[0].tools == ()
    work.observations.append(
        {
            "kind": "tool",
            "tool": "read_file",
            "ok": True,
            "action_sequence": 4,
            "plan_revision": revision,
            "result": {"path": "example.py"},
        }
    )
    harness.persist_progress(work, "work.observing", {})
    progress = _execution_progress(harness.context_for(work))
    assert progress["phase"] == "ACT"
    assert progress["tests_run"] is False and calls == []

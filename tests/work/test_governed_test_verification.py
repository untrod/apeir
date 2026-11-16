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

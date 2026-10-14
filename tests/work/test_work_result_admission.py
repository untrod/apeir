from __future__ import annotations

import pytest

from nous_runtime.events import RunState
from nous_runtime.planner.plan import TaskStatus
from nous_runtime.tools.artifact import ArtifactToolRuntime
from nous_runtime.tools import ToolCatalog, ToolDefinition
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness
from nous_runtime.work.deliberation import verify_recorded_work


class ResultTools:
    def __init__(self, result, effect_class="read"):
        self.result = result
        self.effect_class = effect_class
        self.calls = 0

    def specifications(self):
        return (
            {
                "type": "function",
                "function": {
                    "name": "inspect_value",
                    "description": "Isolated result fixture",
                    "parameters": {"type": "object"},
                },
            },
        )

    def require(self, name):
        return type(
            "Definition",
            (),
            {
                "effect_class": self.effect_class,
                "capability_id": name,
            },
        )()

    def execute(self, _name, _arguments):
        self.calls += 1
        return self.result


INVALID_RESULTS = [
    None,
    {},
    {"error": "denied"},
    {"isError": True},
    {"ok": "false"},
    {"ok": 1},
    {"ok": None},
    {"ok": True, "success": False},
    {"ok": True, "passed": "true"},
    {"ok": True, "error": "denied"},
    {"ok": True, "errors": ["denied"]},
    {"ok": True, "isError": True},
    {"ok": True, "outcome": "UNKNOWN"},
    {"ok": True, "recovery_required": True},
    {"ok": True, "error_code": "DENIED"},
    "done",
    1,
    True,
]


def run_result(harness, tools):
    created = harness.create(
        "Explain this idea", completion_criteria=["inspection succeeds"]
    )
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Inspect requested value",
                tool_name="inspect_value",
            ),
            WorkDecision(DecisionStatus.COMPLETE, "Claim completion"),
        )
    )
    return harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        verifier=verify_recorded_work,
        max_iterations=2,
    )


@pytest.mark.parametrize("result", INVALID_RESULTS)
def test_error_or_unknown_tool_result_cannot_complete_original_work(tmp_path, result):
    harness = WorkHarness(tmp_path)
    tools = ResultTools(result)
    settled = run_result(harness, tools)
    assert settled.state is not RunState.COMPLETED
    assert tools.calls == 1
    assert settled.observations[0]["ok"] is False
    assert not any(
        item["kind"] == "verification" and item["ok"] is True
        for item in settled.observations
    )
    assert WorkHarness(tmp_path).require(settled.run_id).state is not RunState.COMPLETED


@pytest.mark.parametrize("result", INVALID_RESULTS[:-1])
def test_verifier_error_or_unknown_cannot_complete_original_work(tmp_path, result):
    harness = WorkHarness(tmp_path)
    created = harness.create(
        "Explain this idea", completion_criteria=["verification succeeds"]
    )
    settled = harness.run(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE, "Claim completion"
        ),
        verifier=lambda _context: result,
        max_iterations=1,
    )
    assert settled.state is not RunState.COMPLETED
    assert settled.observations[-1]["kind"] == "verification"
    assert settled.observations[-1]["ok"] is False


@pytest.mark.parametrize(
    "result",
    [
        {"ok": True},
        {"success": True},
        {"passed": True},
        {
            "ok": True,
            "success": True,
            "passed": True,
            "error": "",
            "errors": [],
            "isError": False,
        },
    ],
)
def test_explicit_boolean_success_envelopes_complete_original_work(tmp_path, result):
    tools = ResultTools(result)
    settled = run_result(WorkHarness(tmp_path), tools)
    assert settled.state is RunState.COMPLETED
    assert tools.calls == 1


def test_actual_artifact_reader_result_completes_original_work(tmp_path):
    result = ArtifactToolRuntime(tmp_path).execute("artifact_list", {})
    assert result["ok"] is True
    settled = run_result(WorkHarness(tmp_path), ResultTools(result))
    assert settled.state is RunState.COMPLETED


@pytest.mark.parametrize("verifier", [None, verify_recorded_work])
def test_unplanned_work_cannot_skip_failed_tool_verification(tmp_path, verifier):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain this idea")
    assert created.plan is None
    assert created.goal.completion_criteria == []
    tools = ResultTools({"error": "access denied"})
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Inspect requested value",
                tool_name="inspect_value",
            ),
            WorkDecision(DecisionStatus.COMPLETE, "Claim completion"),
        )
    )
    settled = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        verifier=verifier,
        max_iterations=2,
    )
    assert settled.state is not RunState.COMPLETED
    assert tools.calls == 1
    assert settled.observations[-1]["kind"] == "verification"
    assert settled.observations[-1]["ok"] is False


@pytest.mark.parametrize("verified", [True, False])
def test_boolean_verifier_contract_is_preserved(tmp_path, verified):
    harness = WorkHarness(tmp_path)
    created = harness.create(
        "Explain this idea", completion_criteria=["verification succeeds"]
    )
    settled = harness.run(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE, "Claim completion"
        ),
        verifier=lambda _context: verified,
        max_iterations=1,
    )
    assert (settled.state is RunState.COMPLETED) is verified


@pytest.mark.parametrize("effect", ["write", "execute", "network", "unknown"])
@pytest.mark.parametrize(
    "result", [None, {}, {"ok": True, "error": "rollback failed"}, "lost response"]
)
def test_ambiguous_effect_result_retains_pending_action_and_never_replays(
    tmp_path, effect, result
):
    harness = WorkHarness(tmp_path)
    tools = ResultTools(result, effect)
    settled = run_result(harness, tools)
    assert settled.state is RunState.RECOVERY_REQUIRED
    original = dict(settled.pending_action)
    assert original["tool"] == "inspect_value"
    assert tools.calls == 1
    restored = WorkHarness(tmp_path).resume(
        settled.run_id,
        deliberator=lambda _context: pytest.fail("uncertain effect cannot deliberate"),
        tools=tools,
        verifier=verify_recorded_work,
    )
    assert restored.state is RunState.RECOVERY_REQUIRED
    assert restored.pending_action == original
    assert tools.calls == 1


@pytest.mark.parametrize("result", [None, "done", True])
def test_catalog_does_not_manufacture_success_for_scalar_executor_result(
    tmp_path, result
):
    tools = ToolCatalog()
    tools.register(
        ToolDefinition(
            "inspect_value",
            "Isolated result fixture",
            {},
            category="audit",
            effect_class="read",
        ),
        executor=lambda _name, _arguments: result,
    )
    harness = WorkHarness(tmp_path)
    created = harness.create(
        "Explain this idea", completion_criteria=["inspection succeeds"]
    )
    created.loaded_tools["inspect_value"] = tools.require("inspect_value").to_dict()
    harness.persist_progress(created, "work.progress", {})
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Inspect requested value",
                tool_name="inspect_value",
            ),
            WorkDecision(DecisionStatus.COMPLETE, "Claim completion"),
        )
    )
    settled = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        verifier=verify_recorded_work,
        max_iterations=2,
    )
    assert settled.state is not RunState.COMPLETED
    assert settled.observations[0]["ok"] is False


def coding_work(
    harness,
    *,
    exit_code=0,
    test_sequence=3,
    diff_sequence=4,
    result_sequence=None,
    previous_revision=False,
    change_sequence=2,
):
    snapshot = harness.create("Fix the code in this repository")
    revision = snapshot.plan.revision
    prior = revision - 1 if previous_revision else revision
    observations = [
        ("read_file", 1, revision, {"path": "src/example.py"}),
        (
            "patch_file",
            change_sequence,
            revision,
            {
                "change": {
                    "path": "src/example.py",
                    "before_digest": "old",
                    "after_digest": "new",
                }
            },
        ),
        (
            "shell_status",
            test_sequence,
            prior,
            {"command": ["pytest", "-q"], "state": "EXITED", "exit_code": exit_code},
        ),
        (
            "git_diff",
            diff_sequence,
            prior,
            {"stdout": "diff --git a/src/example.py b/src/example.py"},
        ),
    ]
    for tool, sequence, rev, result in observations:
        if tool == "shell_status" and exit_code == "missing":
            result.pop("exit_code")
        if tool == "shell_status" and result_sequence is not None:
            result["action_sequence"] = result_sequence
            result["work_id"] = snapshot.run_id
        snapshot.observations.append(
            {
                "kind": "tool",
                "tool": tool,
                "ok": True,
                "action_sequence": sequence,
                "plan_revision": rev,
                "result": result,
            }
        )
    for task in snapshot.plan.tasks:
        if task.task_id != "verify":
            task.status = TaskStatus.COMPLETED
    snapshot.action_sequence = max(test_sequence, diff_sequence, 2)
    harness.persist_progress(snapshot, "work.progress", {})
    return harness.run(
        snapshot.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE, "Claim coding completion"
        ),
        verifier=verify_recorded_work,
        max_iterations=1,
    )


@pytest.mark.parametrize(
    "test_sequence,diff_sequence,result_sequence,previous_revision",
    [
        (1, 1, None, False),
        (1, 4, None, False),
        (3, 1, None, False),
        (3, 4, 1, False),
        (3, 4, None, True),
    ],
)
def test_tests_and_diff_must_cover_current_change(
    tmp_path, test_sequence, diff_sequence, result_sequence, previous_revision
):
    settled = coding_work(
        WorkHarness(tmp_path),
        test_sequence=test_sequence,
        diff_sequence=diff_sequence,
        result_sequence=result_sequence,
        previous_revision=previous_revision,
    )
    assert settled.state is not RunState.COMPLETED
    assert settled.observations[-1]["ok"] is False


@pytest.mark.parametrize("exit_code", [None, False, True, "0", "", 0.0, 1, "missing"])
def test_test_exit_requires_exact_integer_zero(tmp_path, exit_code):
    settled = coding_work(WorkHarness(tmp_path), exit_code=exit_code)
    assert settled.state is not RunState.COMPLETED
    assert "tests_run" in settled.observations[-1]["result"]["missing_progress_facts"]


def test_current_tests_and_diff_complete_original_coding_work(tmp_path):
    settled = coding_work(WorkHarness(tmp_path), result_sequence=3)
    assert settled.state is RunState.COMPLETED
    assert settled.observations[-1]["ok"] is True


@pytest.mark.parametrize("sequence", [None, False, "2"])
def test_unbound_change_order_cannot_qualify_coding_verification(tmp_path, sequence):
    settled = coding_work(WorkHarness(tmp_path), change_sequence=sequence)
    assert settled.state is not RunState.COMPLETED
    assert "tests_run" in settled.observations[-1]["result"]["missing_progress_facts"]
    assert (
        "diff_reviewed" in settled.observations[-1]["result"]["missing_progress_facts"]
    )


@pytest.mark.parametrize(
    "result",
    [
        {"found": True},
        {"found": True, "ok": False},
        {"found": True, "ok": True, "isError": True},
        {"found": True, "ok": True, "error": "identity unavailable"},
        {"found": True, "ok": True, "outcome": "UNKNOWN"},
    ],
)
def test_recovery_discovery_flag_cannot_override_invalid_original_result(
    tmp_path, result
):
    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect the original process and its current state")
    created.pending_action = {
        "tool": "shell_start",
        "effect_class": "execute",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    original = dict(created.pending_action)
    harness.persist_progress(created, "work.action.dispatched", {})
    tools = ResultTools(result, "execute")
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail("invalid recovery cannot deliberate"),
        tools=tools,
    )
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert settled.pending_action == original
    assert tools.calls == 0


def test_reattaching_running_test_cannot_complete_unplanned_coding_work(
    tmp_path, bound_process_recovery
):
    harness = WorkHarness(tmp_path)
    created = harness.create("Run a persistent targeted test")
    assert created.analysis.task_type == "coding"
    assert created.plan is None
    created.pending_action = {
        "tool": "shell_start",
        "effect_class": "execute",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    tools, _store, _session, _spec, _host, calls = bound_process_recovery(
        harness, created
    )
    created.loaded_tools["shell_recover"] = tools.require("shell_recover").to_dict()
    harness.persist_progress(created, "work.action.dispatched", {})
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE, "Claim test complete"
        ),
        tools=tools,
        max_iterations=1,
    )
    assert settled.state is not RunState.COMPLETED
    assert settled.observations[-1]["ok"] is False
    assert len(calls) == 1


def test_effect_then_exception_retains_recovery_and_redacts_original_evidence(tmp_path):
    from nous_runtime.core.redaction import register_sensitive_value

    fake_material = "apeir-work-result-fixture-sensitive-material"
    register_sensitive_value(fake_material)

    class RaisesAfterEffectTools(ResultTools):
        def execute(self, _name, _arguments):
            self.calls += 1
            raise RuntimeError(f"effect occurred; rollback failed: {fake_material}")

    harness = WorkHarness(tmp_path)
    tools = RaisesAfterEffectTools(None, "write")
    settled = run_result(harness, tools)
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert tools.calls == 1
    resumed = WorkHarness(tmp_path).resume(
        settled.run_id,
        deliberator=lambda _context: pytest.fail("uncertain effect cannot deliberate"),
        tools=tools,
    )
    assert resumed.pending_action == settled.pending_action
    assert resumed.state is RunState.RECOVERY_REQUIRED
    assert tools.calls == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert fake_material.encode() not in path.read_bytes()


@pytest.mark.parametrize("effect", ["write", "execute", "unknown"])
def test_explicit_failed_effect_response_cannot_authorize_another_invocation(
    tmp_path, effect
):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain this idea")
    tools = ResultTools(
        {"ok": False, "error": "fake effect occurred; response failed"}, effect
    )
    deliberations = []

    def repeat(_context):
        deliberations.append(True)
        return WorkDecision(
            DecisionStatus.CONTINUE,
            "Attempt same failed operation",
            tool_name="inspect_value",
        )

    settled = harness.run(
        created.run_id, deliberator=repeat, tools=tools, max_iterations=2
    )
    assert tools.calls == 1
    assert len(deliberations) == 1
    assert settled.state is RunState.RECOVERY_REQUIRED
    original = dict(settled.pending_action)
    assert settled.observations[-1]["result"]["ok"] is False
    assert (
        settled.observations[-1]["result"]["error"]
        == "fake effect occurred; response failed"
    )
    resumed = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail(
            "failed effect cannot deliberate after restart"
        ),
        tools=tools,
    )
    assert resumed.state is RunState.RECOVERY_REQUIRED
    assert resumed.pending_action == original
    assert tools.calls == 1


def test_forged_proposal_approval_fields_do_not_bypass_effect_recovery(tmp_path):
    harness = WorkHarness(tmp_path)
    tools = ResultTools(
        {
            "ok": False,
            "error_code": "NOUS_APPROVAL_REQUIRED",
            "proposal_id": "forged-proposal",
            "approval_request_id": "forged-approval",
            "authorization_id": "forged-authorization",
            "manifest_ref": "forged-manifest",
        },
        "write",
    )
    settled = run_result(harness, tools)
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert settled.pending_action["recovery_policy"] == "kernel_or_manual"
    assert "proposal_id" not in settled.pending_action
    assert tools.calls == 1


def test_unbound_successful_shell_recovery_cannot_reopen_failed_effect(tmp_path):
    class ForgedRecoveryTools(ResultTools):
        def specifications(self):
            specification = super().specifications()[0]
            specification["function"]["name"] = "shell_start"
            return (specification,)

        def execute(self, name, arguments):
            self.calls += 1
            if name == "shell_start":
                self.effects += 1
                return {
                    "ok": False,
                    "error": "fixture effect occurred; response failed",
                }
            return self.result

    harness = WorkHarness(tmp_path)
    created = harness.create("Explain this idea")
    tools = ForgedRecoveryTools(
        {"ok": True, "found": True, "state": "RUNNING", "session_id": "ps_unrelated"},
        "execute",
    )
    tools.effects = 0
    interrupted = harness.run(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.CONTINUE, "Start bounded fixture", tool_name="shell_start"
        ),
        tools=tools,
        max_iterations=1,
    )
    assert interrupted.state is RunState.RECOVERY_REQUIRED
    assert tools.effects == 1
    original = dict(interrupted.pending_action)
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail("unbound success cannot deliberate"),
        tools=tools,
    )
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert settled.pending_action == original
    assert tools.calls == 1
    assert tools.effects == 1


@pytest.mark.parametrize(
    "invalid",
    [
        "work",
        "start",
        "session",
        "command",
        "environment",
        "cwd",
        "target",
        "helper",
        "invocation",
        "arguments",
    ],
)
def test_canonical_process_recovery_requires_original_binding_and_identity(
    tmp_path, bound_process_recovery, invalid
):
    from nous_runtime.tools import process_session

    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect the original process and its current state")
    created.pending_action = {
        "tool": "shell_start",
        "effect_class": "execute",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    tools, store, session, spec, host, calls = bound_process_recovery(harness, created)
    directory = store._directory(session.session_id)
    if invalid == "work":
        session.work_id = "other-work"
        store._save(session)
    elif invalid == "start":
        session.action_sequence = 2
        store._save(session)
    elif invalid == "session":
        created.pending_action["process_session_id"] = "ps_unrelated"
    elif invalid == "command":
        spec["command"] = ["pytest", "other.py"]
    elif invalid == "environment":
        spec["env"] = {"FAKE_PROFILE": "changed"}
    elif invalid == "cwd":
        session.cwd = str(tmp_path.parent)
        spec["cwd"] = session.cwd
        store._save(session)
    elif invalid == "target":
        host["process_identity"] = {**host["process_identity"], "pid": 9999}
    elif invalid == "helper":
        host["helper_identity"] = {}
    elif invalid == "invocation":
        session.tool_call_id = "invoke_unrelated"
        store._save(session)
    elif invalid == "arguments":
        created.pending_action["arguments_digest"] = "sha256:" + "f" * 64
    process_session._atomic_json(directory / "spec.json", spec)
    process_session._atomic_json(directory / "host.json", host)
    original = dict(created.pending_action)
    harness.persist_progress(created, "work.action.dispatched", {})
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail(
            "unproven original process cannot deliberate"
        ),
        tools=tools,
    )
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert settled.pending_action == original
    assert len(calls) == (0 if invalid == "arguments" else 1)


def test_current_work_cancellation_during_canonical_recovery_blocks_resume(
    tmp_path, bound_process_recovery
):
    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect the original process and its current state")
    created.pending_action = {
        "tool": "shell_start",
        "effect_class": "execute",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    tools, store, _session, _spec, _host, calls = bound_process_recovery(
        harness, created
    )
    harness.persist_progress(created, "work.action.dispatched", {})
    original_recover = store.recover
    original_pending = dict(created.pending_action)

    def cancel_then_observe(**arguments):
        harness.cancel(created.run_id)
        return original_recover(**arguments)

    store.recover = cancel_then_observe
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail("cancelled Work cannot deliberate"),
        tools=tools,
    )
    assert settled.state is RunState.CANCELLED
    assert settled.pending_action == original_pending
    assert WorkHarness(tmp_path).require(created.run_id).state is RunState.CANCELLED
    assert len(calls) == 1


@pytest.mark.parametrize("different", ["command", "profile"])
def test_valid_same_work_action_host_cannot_replace_original_pending_inputs(
    tmp_path, bound_process_recovery, different
):
    from nous_runtime.tools import process_session

    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect original process evidence")
    created.pending_action = {
        "tool": "shell_start",
        "effect_class": "execute",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    tools, store, session, spec, host, calls = bound_process_recovery(harness, created)
    if different == "command":
        session.command = [*session.command, "other.py"]
        session.command_digest = process_session._digest(session.command)
        session.process_identity["command_digest"] = session.command_digest
        spec.update(command=session.command, command_digest=session.command_digest)
        host["command_digest"] = session.command_digest
    else:
        spec["env"] = {**spec["env"], "FAKE_PROFILE": "different"}
        session.environment_ref = process_session._digest(spec["env"])
    store._save(session)
    directory = store._directory(session.session_id)
    process_session._atomic_json(directory / "spec.json", spec)
    process_session._atomic_json(directory / "host.json", host)
    assert store._recovery_spec_matches(session) is True
    assert store.status(session.session_id)["ok"] is True
    original = dict(created.pending_action)
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail(
            "different valid host cannot replace original inputs"
        ),
        tools=tools,
    )
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert settled.pending_action == original
    assert len(calls) == 1


def test_legacy_pending_without_original_process_binding_remains_unknown(
    tmp_path, bound_process_recovery
):
    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect original process evidence")
    created.pending_action = {
        "tool": "shell_start",
        "effect_class": "execute",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    tools, _store, _session, _spec, _host, calls = bound_process_recovery(
        harness, created
    )
    created.pending_action.pop("process_binding")
    original = dict(created.pending_action)
    harness.persist_progress(created, "work.action.dispatched", {})
    settled = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=lambda _context: pytest.fail(
            "missing original binding cannot be guessed"
        ),
        tools=tools,
    )
    assert settled.state is RunState.RECOVERY_REQUIRED
    assert settled.pending_action == original
    assert calls == []

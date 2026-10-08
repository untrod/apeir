"""Slow host setup must not extend authority or create a second admission."""

from types import SimpleNamespace

import pytest

from nous_runtime.agents.adapters.supervisor import ProcessSupervisor
from nous_runtime.environments.providers import ProviderExecutionResult
from nous_runtime.governance.operation_contracts import GovernanceDecision
from nous_runtime.node_runtime.service import WorkloadResponseLost
from tests.interoperability.test_external_agent import approve, execute, setup_agent

pytestmark = pytest.mark.unit


class PreparedRunner:
    def __init__(self, prepare=lambda: None, *, mode="normal"):
        self.prepare = prepare
        self.mode = mode
        self.effects = 0
        self.cleaned = 0
        self.callback = None

    def __call__(self, *args):
        pytest.fail("Admission-aware runner must not use legacy fallback")

    def execute_admitted(self, cmd, env, cwd, timeout_ms, *, before_dispatch):
        self.callback = before_dispatch
        try:
            self.prepare()
            if self.mode != "omit":
                before_dispatch()
                if self.mode == "duplicate":
                    before_dispatch()
                self.effects += 1
            if self.mode == "lost":
                raise WorkloadResponseLost(
                    "response lost", output={"effect_count": 1}, completed=True
                )
            return ProviderExecutionResult(ok=True, exit_code=0, stdout="proposal")
        finally:
            self.cleaned += 1


@pytest.mark.parametrize(
    "verdict", [GovernanceDecision.DENY, GovernanceDecision.UNKNOWN]
)
def test_policy_change_during_setup_prevents_dispatch(tmp_path, verdict):
    policy = SimpleNamespace(evaluate=lambda request: GovernanceDecision.ALLOW)
    runner = PreparedRunner(
        lambda: setattr(policy, "evaluate", lambda request: verdict)
    )
    fixture = setup_agent(tmp_path, runner, policy=policy)
    approve(fixture)
    assert execute(fixture)["state"] == "FAILED"
    assert runner.effects == 0
    assert runner.cleaned == 1
    assert execute(fixture)["state"] == "FAILED"
    assert runner.cleaned == 1


def test_expiry_during_setup_prevents_dispatch(tmp_path, monkeypatch):
    from nous_runtime.governance import operation_gate

    runner = PreparedRunner(
        lambda: monkeypatch.setattr(
            operation_gate, "_utc_now", lambda: "9999-12-31T23:59:59Z"
        )
    )
    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    assert execute(fixture)["state"] == "FAILED"
    assert runner.effects == 0
    assert runner.cleaned == 1


@pytest.mark.parametrize("mode", ["omit", "duplicate"])
def test_dispatch_admission_cannot_be_omitted_or_reused(tmp_path, mode):
    runner = PreparedRunner(mode=mode)
    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    assert execute(fixture)["state"] == "FAILED"
    assert runner.effects == 0
    assert runner.cleaned == 1
    with pytest.raises(PermissionError, match="no longer usable"):
        runner.callback()


def test_valid_dispatch_and_late_callback_rejected(tmp_path):
    runner = PreparedRunner()
    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    assert execute(fixture)["state"] == "COMPLETED"
    assert execute(fixture)["state"] == "COMPLETED"
    assert runner.effects == 1
    assert runner.cleaned == 1
    with pytest.raises(PermissionError, match="no longer usable"):
        runner.callback()


def test_response_loss_keeps_native_journal_no_second_dispatch(tmp_path):
    runner = PreparedRunner(mode="lost")
    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    with pytest.raises(WorkloadResponseLost):
        execute(fixture)
    assert execute(fixture)["state"] == "COMPLETED"
    assert runner.effects == 1
    assert runner.cleaned == 1
    with pytest.raises(PermissionError, match="no longer usable"):
        runner.callback()


def test_cancel_during_setup_prevents_dispatch(tmp_path, monkeypatch):
    original = ProcessSupervisor._execute

    def execute_with_cancel(supervisor, *args, **kwargs):
        runner.prepare = supervisor.cancel
        return original(supervisor, *args, **kwargs)

    runner = PreparedRunner()
    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    monkeypatch.setattr(ProcessSupervisor, "_execute", execute_with_cancel)
    assert execute(fixture)["state"] == "FAILED"
    assert runner.effects == 0
    assert runner.cleaned == 1


def test_dispatch_runner_without_authority_fails_before_setup(tmp_path):
    from nous_runtime.agents.adapters.command_adapter import CommandAgentAdapter
    from nous_runtime.agents.external.models import (
        AgentDescriptor,
        AgentRunContext,
        AgentRunRequest,
    )

    runner = PreparedRunner()
    adapter = CommandAgentAdapter(
        AgentDescriptor(agent_id="prepared", executable_reference="unused"),
        execution_runner=runner,
    )
    result = adapter.execute(
        AgentRunRequest(run_id="unapproved", agent_id="prepared"),
        AgentRunContext(run_id="unapproved", workspace_path=str(tmp_path)),
    )
    assert result.status == "FAILED"
    assert runner.effects == runner.cleaned == 0

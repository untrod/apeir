from __future__ import annotations

from nous_runtime.agent.pipeline import RuntimeAgentExecutor


def test_runtime_agent_executor_applies_lifecycle_budget_and_events():
    result = RuntimeAgentExecutor().execute(
        task_id="task-1",
        capability_id="tool.echo",
        parameters={"message": "hello"},
        handler=lambda params: {"echo": params["message"]},
        estimated_tokens=5,
    )

    assert result.ok
    assert result.output == {"echo": "hello"}
    assert result.state == "COMPLETED"
    assert result.budget["tool_invocations"] == 1
    assert result.budget["tokens"] == 5
    assert [event["event_type"] for event in result.events] == [
        "agent.execution.created",
        "agent.execution.started",
        "agent.invocation.completed",
        "agent.execution.completed",
    ]


def test_runtime_agent_executor_reports_handler_failure():
    def fail(params):
        raise RuntimeError("boom")

    result = RuntimeAgentExecutor().execute(
        task_id="task-2",
        capability_id="tool.fail",
        handler=fail,
    )

    assert not result.ok
    assert result.state == "FAILED"
    assert result.invocation["status"] == "failed"
    assert result.error == "boom"

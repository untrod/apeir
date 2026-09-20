from __future__ import annotations

from nous_runtime.chat.agent_execution import ChatAgentExecution


def _execution(*, max_models: int = 2) -> ChatAgentExecution:
    return ChatAgentExecution(
        task_id="task-chat-agent",
        workspace_id="workspace",
        session_id="session",
        tool_names={"read_file"},
        max_model_invocations=max_models,
    )


def test_chat_agent_execution_owns_model_and_tool_invocations() -> None:
    execution = _execution()

    model, model_record = execution.invoke_model(lambda: "model-result")
    tool, tool_record = execution.invoke_tool(
        "read_file",
        {"path": "README.md"},
        lambda: {"ok": True, "content": "ready"},
    )
    summary = execution.finish(ok=True, message="complete")

    assert model == "model-result"
    assert tool["ok"] is True
    assert model_record["kind"] == "model"
    assert tool_record["kind"] == "tool"
    assert summary["state"] == "COMPLETED"
    assert summary["budget"]["model_invocations"] == 1
    assert summary["budget"]["tool_invocations"] == 1


def test_chat_agent_execution_checkpoints_a_bounded_pause() -> None:
    execution = _execution(max_models=1)
    execution.invoke_model(lambda: "partial")

    summary = execution.finish(ok=False, paused=True, message="continue")

    assert summary["state"] == "CHECKPOINTED"
    assert summary["checkpoint_id"]


def test_chat_agent_execution_records_failure() -> None:
    execution = _execution()

    summary = execution.finish(ok=False, message="provider failed")

    assert summary["state"] == "FAILED"
    assert any(
        event["event_type"] == "agent.execution.failed"
        for event in summary["events"]
    )

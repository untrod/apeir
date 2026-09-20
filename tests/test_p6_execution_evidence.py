from __future__ import annotations

import json
from types import SimpleNamespace

from nous_runtime.events import EventStream
from nous_runtime.runtime.pipeline import RuntimePipeline
from nous_runtime.runtime.redaction import REDACTED, redact_runtime_evidence
from nous_runtime.runtime.request import RuntimeRequest
from nous_runtime.runtime.session import RuntimeSessionStore


class _ExecuteGate:
    def evaluate(self, proposal, context):
        return SimpleNamespace(
            action_mode="EXECUTE",
            reason_message="allowed",
            reason_code="TEST",
            decision_id="decision-p6",
        )


def _pipeline(tmp_path, monkeypatch) -> RuntimePipeline:
    pipeline = RuntimePipeline(
        workspace_root=str(tmp_path),
        product_handlers={
            "chat": lambda request, context: {
                "ok": True,
                "status": "success",
                "content": "completed",
            }
        },
        gate=_ExecuteGate(),
    )
    monkeypatch.setattr(
        pipeline, "_build_context", lambda request, intent, workspace: {}
    )
    monkeypatch.setattr(
        pipeline,
        "_plan",
        lambda request, intent, workspace: {
            "status": "planned",
            "reason": "",
            "execution_mode": "gateway_agent",
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_decide",
        lambda request, workspace, intent: {
            "selected": "bound",
            "reason": "",
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_evaluate",
        lambda request, workspace, trace, execution: {
            "status": "evaluated"
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_collect_experience",
        lambda workspace, execution, evaluation: {"status": "collected"},
    )
    return pipeline


def test_runtime_evidence_redacts_nested_credentials_and_secret_values() -> None:
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"  # security-scan: fixture
    result = redact_runtime_evidence(
        {
            "api_key": secret,
            "nested": [{"Authorization": f"Bearer {secret}"}],
            "prompt": f"token accidentally pasted: {secret}",
            "credential_ref": "env:OPENAI_API_KEY",
            "credential_env": "OPENAI_API_KEY",
        }
    )

    assert result["api_key"] == REDACTED
    assert result["nested"][0]["Authorization"] == REDACTED
    assert result["prompt"] == REDACTED
    assert result["credential_ref"] == "env:OPENAI_API_KEY"
    assert result["credential_env"] == "OPENAI_API_KEY"
    assert secret not in json.dumps(result)


def test_pipeline_preserves_stable_ids_and_redacts_replay_evidence(
    tmp_path, monkeypatch
) -> None:
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"  # security-scan: fixture
    pipeline = _pipeline(tmp_path, monkeypatch)
    request = RuntimeRequest(
        "complete the task",
        session="conversation-p6",
        request_id="p6-stable-run",
        constraints={
            "product_capability": "chat",
            "api_key": secret,
            "credential_ref": "env:OPENAI_API_KEY",
        },
        authorization_context={
            "subject_id": "operator",
            "access_token": secret,
        },
    )

    response = pipeline.run(request)
    events = EventStream(str(tmp_path)).load_events(request.request_id)
    sessions = RuntimeSessionStore(str(tmp_path)).list()
    serialized = json.dumps(
        {
            "response": response.to_dict(),
            "events": [event.to_dict() for event in events],
            "sessions": sessions,
        }
    )

    assert response.status == "ok"
    assert response.request_id == request.request_id
    assert response.trace_id == request.request_id
    assert response.result["run_id"] == request.request_id
    assert response.result["task_id"] == request.request_id
    assert events
    assert all(event.run_id == request.request_id for event in events)
    assert all(event.task_id == request.request_id for event in events)
    assert secret not in serialized
    input_entry = response.result["trace"]["entries"][0]
    assert input_entry["data"]["constraints"]["api_key"] == REDACTED
    assert (
        input_entry["data"]["constraints"]["credential_ref"]
        == "env:OPENAI_API_KEY"
    )
    assert (
        input_entry["data"]["authorization_context"]["access_token"]
        == REDACTED
    )


class _RecoveryFacade:
    def __init__(self, *, complete: bool) -> None:
        self.complete = complete
        self.calls = 0

    def try_invoke_sync(self, request):
        from nous_runtime.model_runtime.facade import GatewayResponse

        self.calls += 1
        if not self.complete:
            return GatewayResponse(
                request_id=request.execution.task_id,
                content="I will create the file.",
                provider_id="deterministic",
                model_id="deterministic/p6",
            )
        if self.calls == 1:
            return GatewayResponse(
                request_id=request.execution.task_id,
                provider_id="deterministic",
                model_id="deterministic/p6",
                tool_calls=(
                    {
                        "id": "p6-write",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": (
                                '{"path":"result.txt",'
                                '"content":"P6 recovery completed."}'
                            ),
                        },
                    },
                ),
            )
        return GatewayResponse(
            request_id=request.execution.task_id,
            content="The recovered task completed.",
            provider_id="deterministic",
            model_id="deterministic/p6",
        )


def _chat_runtime(root, facade):
    from nous_runtime.chat import ChatRuntime
    from nous_runtime.connectivity.project import ProjectExecutionService
    from nous_runtime.model_runtime.bridges import GatewayChatHandler
    from nous_runtime.runtime.orchestrator import RuntimeOrchestrator

    orchestrator = RuntimeOrchestrator(
        workspace_root=str(root),
        product_handlers={"chat": GatewayChatHandler(facade)},
        gate=_ExecuteGate(),
        bootstrap=False,
    )
    return ChatRuntime(
        str(root),
        orchestrator=orchestrator,
        project_execution=ProjectExecutionService(),
    )


def test_product_chain_recovers_project_checkpoint_after_runtime_restart(
    tmp_path, monkeypatch
) -> None:
    from nous_runtime.chat import ChatRequest

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))
    first_runtime = _chat_runtime(
        tmp_path,
        _RecoveryFacade(complete=False),
    )
    first = first_runtime.send(
        ChatRequest(
            "Create result.txt with code output.",
            "workspace-p6",
            "operator",
            request_id="p6-run-before-restart",
        )
    )

    first_link = first.data["project_execution"]
    first_agent = first.data["result"]["execution"]["result"]["agent_execution"]
    assert first.status == "failed"
    assert first_link["status"] == "recovery_required"
    assert first_link["checkpoint_id"]
    assert first_agent["state"] == "CHECKPOINTED"
    assert first_agent["checkpoint_id"]
    assert not (tmp_path / "result.txt").exists()

    restarted_runtime = _chat_runtime(
        tmp_path,
        _RecoveryFacade(complete=True),
    )
    resumed = restarted_runtime.send(
        ChatRequest(
            "Continue the code task and create result.txt.",
            "workspace-p6",
            "operator",
            conversation_id=first.conversation_id,
            request_id="p6-run-after-restart",
        )
    )

    resumed_link = resumed.data["project_execution"]
    assistant = restarted_runtime.conversations.history(
        first.conversation_id
    )[-1]
    events = EventStream(str(tmp_path)).load_events("p6-run-after-restart")

    assert resumed.status == "ok"
    assert resumed_link["resumed"] is True
    assert resumed_link["status"] == "succeeded"
    assert resumed_link["project_id"] == first_link["project_id"]
    assert resumed_link["work_item_id"] == first_link["work_item_id"]
    assert resumed_link["checkpoint_id"] != first_link["checkpoint_id"]
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == (
        "P6 recovery completed."
    )
    assert assistant.run_id == "p6-run-after-restart"
    assert assistant.task_id == "p6-run-after-restart"
    assert assistant.event_id == "p6-run-after-restart"
    assert events
    assert all(event.run_id == "p6-run-after-restart" for event in events)
    assert all(event.task_id == "p6-run-after-restart" for event in events)
    event_types = {event.event_type for event in events}
    assert {
        "model.invocation.started",
        "model.invocation.completed",
        "tool.started",
        "tool.completed",
        "artifact.created",
        "verification.completed",
        "run.completed",
    } <= event_types

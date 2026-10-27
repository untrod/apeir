"""User intent and explicit model choices survive the development entry point."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from nous_runtime.chat import ChatIntent, ChatRequest, ChatRuntime, classify_chat
from nous_runtime.chat.collaboration import (
    ChatCollaborationCoordinator,
    should_collaborate,
)
from nous_runtime.model_runtime.bridges import GatewayChatHandler
from nous_runtime.model_runtime.facade import GatewayResponse
from nous_runtime.model_runtime.models import (
    CapabilityLevel,
    ModelInstance,
    ModelInstanceState,
    RoutingMode,
)
from tests.model_runtime.test_gateway_facade import build_facade
from tests.test_chat_runtime import FakeOrchestrator


@pytest.mark.parametrize(
    "text",
    [
        "请分析 Approval 模块的代码，保留人工批准流程，提出双文件修改建议。",
        "Fix Promise.reject(error) in the repository code.",
        "Implement a Python device status parser.",
        "给我实现一个展示设备状态的 Python 函数。",
        "请修复工作流编译器代码。",
    ],
)
def test_engineering_request_is_not_an_incidental_control_keyword(text):
    assert classify_chat(text) is ChatIntent.CODE_TASK


@pytest.mark.parametrize(
    "text", ["Explain how to approve a pull request safely.", "如何批准一个请求？"]
)
def test_approval_explanation_is_a_conversation(text):
    assert classify_chat(text) is ChatIntent.CONVERSATION


@pytest.mark.parametrize(
    "text",
    [
        "approve",
        "approve this",
        "approve this action",
        "reject request-12",
        "批准",
        "请批准这个操作",
        "拒绝执行",
    ],
)
def test_standalone_approval_still_requires_the_trusted_control_path(text):
    assert classify_chat(text) is ChatIntent.APPROVAL_RESPONSE


@pytest.mark.parametrize(
    "text", ["create a workflow", "请创建一个工作流", "run workflow"]
)
def test_direct_workflow_request_retains_its_entry_point(text):
    assert classify_chat(text) is ChatIntent.WORKFLOW_REQUEST


def test_discussing_approval_reaches_runtime_without_creating_authority(tmp_path):
    orchestrator = FakeOrchestrator()
    chat = ChatRuntime(str(tmp_path), orchestrator=orchestrator)
    response = chat.send(
        ChatRequest(
            "请分析代码中的批准流程。", "workspace", "user", agent_mode="read_only"
        )
    )
    assert response.intent is ChatIntent.CODE_TASK
    assert not response.requires_trusted_approval
    assert len(orchestrator.requests) == 1
    assert orchestrator.requests[0].constraints["mutation_authorized"] is False


@pytest.mark.parametrize("mode", ["present", "disabled"])
def test_selected_chat_model_is_not_replaced_by_a_higher_scoring_model(tmp_path, mode):
    facade, _adapter = build_facade("complete")
    registry = facade.gateway.registry
    original = registry.get("local/unified").descriptor
    other = replace(
        original,
        model_id="local/other",
        display_name="Other",
        reasoning_level=CapabilityLevel.HIGH,
        coding_level=CapabilityLevel.HIGH,
    )
    registry.register(other)
    registry.enable(other.model_id)
    registry.register_instance(
        ModelInstance(
            instance_id="other-0",
            model_id=other.model_id,
            node_id="local",
            backend="mock",
            state=ModelInstanceState.READY,
        )
    )
    if mode == "disabled":
        registry.disable(original.model_id)
    try:
        result = GatewayChatHandler(facade, checkpoint_root=str(tmp_path))(
            SimpleNamespace(
                request_id="user-fixed-model",
                user_input="hello",
                constraints={"model_id": original.model_id, "agent_mode": "chat"},
            ),
            {"workspace": str(tmp_path), "session": "session"},
        )
        if mode == "present":
            assert result["gateway"]["model_id"] == original.model_id
        else:
            assert result["ok"] is False
            assert result["gateway"]["model_id"] != other.model_id
    finally:
        facade.gateway.close_sync_bridge()


def test_collaboration_roles_keep_the_explicit_model():
    requests = []

    class Facade:
        def try_invoke_sync(self, request):
            requests.append(request)
            return GatewayResponse(
                request_id=request.execution.task_id, content="brief"
            )

    ChatCollaborationCoordinator(Facade()).prepare(
        "Analyze the program in parallel.",
        task_id="task",
        workspace_id="workspace",
        session_id="session",
        trace_id="trace",
        preferred_model="fixed/model",
        max_parallel_lanes=1,
    )
    assert len(requests) == 2
    assert all(request.routing_mode is RoutingMode.LOCKED for request in requests)


@pytest.mark.parametrize(
    "text",
    ["Fix the failing unit test.", "请修复代码并运行测试。", "Review this function."],
)
def test_simple_development_does_not_spawn_model_collaboration(text):
    assert not should_collaborate(text, "code_task")


@pytest.mark.parametrize(
    ("text", "expected_calls"),
    [
        ("Fix code and run tests.", 1),
        ("Analyze code and tests in parallel.", 5),
        ("Use a single agent to analyze code and tests in parallel.", 1),
    ],
)
def test_development_gateway_records_only_requested_collaboration(
    tmp_path, text, expected_calls
):
    facade, adapter = build_facade("Analysis only; no files changed or tests run.")
    try:
        result = GatewayChatHandler(facade, checkpoint_root=str(tmp_path))(
            SimpleNamespace(
                request_id="development-call-count",
                user_input=text,
                constraints={"agent_mode": "chat", "chat_intent": "code_task"},
            ),
            {"workspace": str(tmp_path), "session": "session"},
        )
        assert result["ok"] is True
        assert len(adapter.invocations) == expected_calls
    finally:
        facade.gateway.close_sync_bridge()


def test_explicit_single_agent_request_wins_over_multiple_deliverables():
    assert not should_collaborate(
        "Use a single agent to create the program, report, paper and tests.",
        "code_task",
    )
    assert should_collaborate("Analyze code and tests in parallel.", "code_task")

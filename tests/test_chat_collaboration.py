from __future__ import annotations

import threading
import time
from pathlib import Path

from nous_runtime.api.routes import handle_global_search
from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.chat.collaboration import (
    ChatCollaborationCoordinator,
    build_lanes,
    should_collaborate,
)
from nous_runtime.model_runtime.facade import GatewayResponse


def test_complex_delivery_selects_independent_collaboration_lanes() -> None:
    request = "Create a small program, its test report, and a short paper in parallel."
    assert should_collaborate(request, "code_task")
    lanes = build_lanes(request)
    assert {lane.lane_id for lane in lanes} >= {
        "implementation",
        "report",
        "paper",
    }
    assert not should_collaborate("Hello Nous", "conversation")


def test_chinese_system_delivery_selects_collaboration() -> None:
    request = "在工作区制作一个专业的航天计算系统，并生成程序、测试和设计文档。"

    assert should_collaborate(request, "CREATE")
    assert {lane.lane_id for lane in build_lanes(request)} >= {
        "implementation",
        "quality",
    }


def test_collaboration_uses_manager_parallel_workers_and_reviewer() -> None:
    class Facade:
        def __init__(self) -> None:
            self.calls = []
            self.lock = threading.Lock()

        def try_invoke_sync(self, request):
            with self.lock:
                self.calls.append(request)
            agent = request.execution.agent_id
            if agent.startswith("nous.worker"):
                time.sleep(0.03)
            content = {
                "nous.manager": "Files and acceptance contract.",
                "nous.reviewer": "APPROVED: verified receipts satisfy the request.",
            }.get(agent, f"Brief from {agent}")
            return GatewayResponse(
                request_id=request.execution.task_id,
                content=content,
                provider_id="deepseek",
                model_id="deepseek/deepseek-chat",
                usage={"total_tokens": 10},
                latency_ms=20,
            )

    facade = Facade()
    events = []
    coordinator = ChatCollaborationCoordinator(facade)  # type: ignore[arg-type]
    preparation = coordinator.prepare(
        "Create a program, report, paper, and tests.",
        task_id="run-one",
        workspace_id="default",
        session_id="session",
        trace_id="trace",
        emit=lambda kind, payload: events.append((kind, payload)),
    )
    review = coordinator.review(
        "Create a program, report, paper, and tests.",
        {"response": "completed", "tool_steps": [{"ok": True}]},
        task_id="run-one",
        workspace_id="default",
        session_id="session",
        trace_id="trace",
        emit=lambda kind, payload: events.append((kind, payload)),
    )

    assert preparation.manager_brief
    assert len(preparation.lanes) == 4
    assert {item["model_id"] for item in preparation.lanes} == {
        "deepseek/deepseek-chat"
    }
    assert review["approved"] is True
    assert (
        sum(call.execution.agent_id.startswith("nous.worker") for call in facade.calls)
        == 4
    )
    assert any(kind == "collaboration.prepared" for kind, _ in events)
    assert any(kind == "review.completed" for kind, _ in events)
    lane_events = [
        payload for kind, payload in events if kind == "model.lane.completed"
    ]
    assert lane_events and all(
        payload["cost_usd"] is None and payload["cost_measurement"] == "unknown"
        for payload in lane_events
    )
    assert all(
        item["cost_usd"] is None and item["cost_measurement"] == "unknown"
        for item in preparation.lanes
    )
    assert all(
        item["usage_request_id"] is None and item["usage_attempt"] is None
        for item in preparation.lanes
    )


def test_reviewer_cannot_approve_failed_tool_receipts() -> None:
    class Facade:
        def try_invoke_sync(self, request):
            return GatewayResponse(
                request_id=request.execution.task_id,
                content="APPROVED: the response appears complete.",
                provider_id="test",
                model_id="test/reviewer",
            )

    review = ChatCollaborationCoordinator(Facade()).review(  # type: ignore[arg-type]
        "Create and verify a program.",
        {"response": "completed", "tool_steps": [{"ok": False}]},
        task_id="run-failed-receipt",
        workspace_id="default",
        session_id="session",
        trace_id="trace",
    )

    assert review["approved"] is False
    assert review["receipts_verified"] is False


def test_reviewer_accepts_a_failed_test_superseded_by_a_passing_test() -> None:
    class Facade:
        def try_invoke_sync(self, request):
            return GatewayResponse(
                request_id=request.execution.task_id,
                content="APPROVED: final verification supersedes the repair failure.",
                provider_id="test",
                model_id="test/reviewer",
            )

    review = ChatCollaborationCoordinator(Facade()).review(  # type: ignore[arg-type]
        "Create and verify a program.",
        {
            "response": "completed",
            "tool_steps": [
                {"tool": "write_file", "ok": True},
                {"tool": "run_command", "ok": False},
                {"tool": "write_file", "ok": True},
                {"tool": "run_command", "ok": True},
            ],
        },
        task_id="run-repaired",
        workspace_id="default",
        session_id="session",
        trace_id="trace",
    )

    assert review["approved"] is True
    assert review["receipts_verified"] is True


def test_batch_project_write_is_guarded_and_audited(tmp_path: Path) -> None:
    from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
    from nous_runtime.governance.cli import _build_context
    from nous_runtime.workspace.proposals import WorkspaceProposalService

    service = WorkspaceProposalService(
        tmp_path,
        gate=ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / ".nous")),
    )
    runtime = WorkspaceToolRuntime(
        str(tmp_path), allow_mutations=True, proposal_service=service
    )
    result = runtime.execute(
        "write_files",
        {
            "files": [
                {"path": "project/app.py", "content": "print('ok')\n"},
                {"path": "project/REPORT.md", "content": "# Report\n"},
                {"path": "project/PAPER.md", "content": "# Paper\n"},
            ]
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "NOUS_APPROVAL_REQUIRED"
    assert result["file_count"] == 3
    assert not (tmp_path / "project" / "app.py").exists()
    original = service.read(result["proposal_id"])
    assert original["manifest_ref"] == result["manifest_ref"]
    service.broker.respond_operation(
        original["approval_request_id"], "approve", _build_context(), gate=service.gate
    )
    applied = service.apply(original["proposal_id"])
    assert applied["applied"] and applied["verification"]["verdict"] == "MATCH"
    assert applied["authorization_id"] == result["authorization_id"]
    assert applied["verification"]["admission_recorded"] is True
    assert applied["verification"]["observation_ref"]
    assert applied["verification"]["verification_ref"]
    assert (tmp_path / "project" / "app.py").is_file()


def test_global_search_finds_workspace_files_and_conversations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "acceptance-report.md").write_text(
        "Runtime acceptance evidence",
        encoding="utf-8",
    )
    from nous_runtime.conversation import ConversationStore

    ConversationStore(tmp_path).create(
        "default",
        "local",
        title="Acceptance project",
    )
    response = handle_global_search("acceptance")
    results = response["data"]["results"]

    assert response["ok"] is True
    assert {item["kind"] for item in results} >= {"conversation", "file"}

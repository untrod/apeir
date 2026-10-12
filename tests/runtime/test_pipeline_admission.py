"""A missing or non-executing governance verdict cannot dispatch a product."""

from types import SimpleNamespace

import pytest

from nous_runtime.runtime.pipeline import RuntimePipeline
from nous_runtime.runtime.request import RuntimeRequest


@pytest.mark.parametrize("surface", ["local_cli", "desktop", "server"])
def test_governance_exception_never_becomes_compatibility_execution(tmp_path, surface):
    class UnavailableGate:
        def evaluate(self, *_):
            raise RuntimeError("deterministic unavailable governance store")

    invoked = []
    pipeline = RuntimePipeline(
        workspace_root=str(tmp_path),
        gate=UnavailableGate(),
        product_handlers={"chat": lambda *_: invoked.append(True) or {"ok": True}},
    )
    response = pipeline.run(
        RuntimeRequest(
            "Explain this project",
            constraints={"product_capability": "chat"},
            governance_surface=surface,
        )
    )
    assert response.status == "deny"
    assert invoked == []


@pytest.mark.parametrize(
    "mode,allowed",
    [("UNKNOWN", True), ("EXECUTE", False), ("EXECUTE", None), ("RECOMMEND", False)],
)
def test_only_explicit_allowed_execute_can_dispatch(tmp_path, mode, allowed):
    class Gate:
        def evaluate(self, *_):
            return SimpleNamespace(
                action_mode=mode,
                allowed=allowed,
                reason_message="test verdict",
                reason_code="TEST",
                decision_id="test",
            )

    invoked = []
    pipeline = RuntimePipeline(
        workspace_root=str(tmp_path),
        gate=Gate(),
        product_handlers={"chat": lambda *_: invoked.append(True) or {"ok": True}},
    )
    response = pipeline.run(
        RuntimeRequest(
            "Explain this project", constraints={"product_capability": "chat"}
        )
    )
    assert response.status in {"deny", "recommend"}
    assert invoked == []


def test_model_tool_workspace_is_bound_to_resolver_not_request_metadata(tmp_path):
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime

    owned = tmp_path / "owned"
    outside = tmp_path / "outside"
    owned.mkdir()
    outside.mkdir()
    (owned / "scope.txt").write_text("owned workspace")
    (outside / "scope.txt").write_text("outside workspace")

    class Gate:
        def evaluate(self, *_):
            return SimpleNamespace(
                action_mode="EXECUTE",
                allowed=True,
                reason_message="allowed",
                decision_id="known-read",
                reason_code="TEST",
            )

    def read_scoped_file(request, _):
        result = WorkspaceToolRuntime(request.constraints["workspace_path"]).execute(
            "read_file", {"path": "scope.txt"}
        )
        return {"ok": True, "status": "success", "content": result["content"]}

    response = RuntimePipeline(
        workspace_root=str(owned),
        gate=Gate(),
        product_handlers={"chat": read_scoped_file},
    ).run(
        RuntimeRequest(
            "Read scope.txt",
            constraints={"product_capability": "chat", "workspace_path": str(outside)},
        )
    )
    assert response.result["execution"]["result"]["content"] == "owned workspace"

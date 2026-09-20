from __future__ import annotations

import inspect
from types import SimpleNamespace

from nous_runtime.cli import shell_v2
from nous_runtime.model_runtime.facade import GatewayOperation


def test_terminal_natural_language_uses_model_gateway(
    monkeypatch,
    tmp_path,
) -> None:
    captured = []

    class Facade:
        def try_invoke_sync(self, request):
            captured.append(request)
            return SimpleNamespace(
                ok=True,
                content="gateway response",
                error={},
            )

    monkeypatch.setattr(
        shell_v2,
        "_session",
        lambda: SimpleNamespace(
            root=tmp_path,
            workspace_id="workspace",
            conversation_id="conversation",
        ),
    )
    monkeypatch.setattr(shell_v2, "_activity", lambda *args: None)
    monkeypatch.setattr(
        shell_v2,
        "_record_trace_timeline",
        lambda *args: None,
    )
    monkeypatch.setattr(
        "nous_runtime.runtime.bootstrap.NousRuntime.bootstrap",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.facade.get_gateway_facade",
        lambda required: Facade(),
    )

    result = shell_v2._call_llm("hello")

    assert result == "gateway response"
    assert captured[0].operation is GatewayOperation.CHAT
    assert captured[0].execution.workspace_id == "workspace"
    assert captured[0].execution.session_id == "conversation"
    assert "execute_capability" not in inspect.getsource(shell_v2._call_llm)

"""Runtime orchestrator facade."""

from __future__ import annotations

from typing import Any

from nous_runtime.runtime.bootstrap import NousRuntime
from nous_runtime.runtime.pipeline import ProductHandler, RuntimePipeline
from nous_runtime.runtime.request import RuntimeRequest
from nous_runtime.runtime.response import RuntimeResponse


class RuntimeOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: str = "",
        product_handlers: dict[str, ProductHandler] | None = None,
        gate: Any = None,
        bootstrap: bool = True,
    ):
        self.runtime = (
            NousRuntime.bootstrap(workspace_root=workspace_root)
            if bootstrap
            else None
        )
        self.pipeline = RuntimePipeline(workspace_root=workspace_root, product_handlers=product_handlers, gate=gate)

    def run(self, request: RuntimeRequest) -> RuntimeResponse:
        return self.pipeline.run(request)


def run_runtime_request(user_input: str, *, workspace: str = "", session: str = "", user_id: str = "local") -> RuntimeResponse:
    return RuntimeOrchestrator().run(
        RuntimeRequest(user_input=user_input, workspace=workspace, session=session, user_id=user_id)
    )

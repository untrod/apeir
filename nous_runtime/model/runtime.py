"""Model Runtime facade."""

from __future__ import annotations

from nous_runtime.model.selector import ModelSelector
from nous_runtime.model.types import ModelRequest, ModelSelection


class ModelRuntime:
    def __init__(
        self,
        selector: ModelSelector | None = None,
        *,
        gateway: object | None = None,
    ):
        self.selector = selector or ModelSelector()
        self.gateway = gateway

    def select(self, request: ModelRequest) -> ModelSelection:
        return self.selector.select(request)

    async def invoke(self, request: object) -> object:
        """Invoke through the unified gateway when one is configured."""
        if self.gateway is None:
            from nous_runtime.model_runtime.errors import ModelRuntimeError

            raise ModelRuntimeError("unified model gateway is not configured")
        return await self.gateway.invoke(request)

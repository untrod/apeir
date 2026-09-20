"""Deterministic model selection adapter."""

from __future__ import annotations

from nous_runtime.model.types import ModelRequest, ModelSelection


class ModelSelector:
    def select(self, request: ModelRequest) -> ModelSelection:
        if request.privacy == "local":
            return ModelSelection("ollama", "local-default", 0.78, "Local privacy requirement.")
        if request.task_type in {"code", "engineering", "runtime"}:
            return ModelSelection("default", "coding-default", 0.72, "Task type favors coding model profile.")
        return ModelSelection("default", "general-default", 0.62, "Default model profile.")

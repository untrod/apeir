"""Explicit tool and model invocation boundaries for Agent runs."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from nous_runtime.agent.budget import AgentBudgetLedger
from nous_runtime.agent.errors import AgentBoundaryError, AgentBudgetError
from nous_runtime.agent.execution_state import (
    InvocationKind,
    InvocationRecord,
    InvocationStatus,
    execution_timestamp,
)


@dataclass(frozen=True)
class InvocationRequest:
    run_id: str
    agent_id: str
    kind: InvocationKind
    target: str
    capability_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    estimated_tokens: int = 0
    estimated_runtime_ms: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    invocation_id: str = field(
        default_factory=lambda: f"invoke_{uuid.uuid4().hex}"
    )

    def audit_dict(self) -> dict[str, Any]:
        """Return a credential-safe request representation."""
        return {
            "invocation_id": self.invocation_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "kind": self.kind.value,
            "target": self.target,
            "capability_id": self.capability_id,
            "parameter_names": sorted(str(key) for key in self.parameters),
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_tokens": self.estimated_tokens,
            "estimated_runtime_ms": self.estimated_runtime_ms,
            "metadata": dict(self.metadata),
        }


InvocationHandler = Callable[[InvocationRequest], Any]


class InvocationBoundary:
    def __init__(
        self,
        *,
        kind: InvocationKind,
        allowed_targets: set[str],
        allowed_capabilities: set[str],
        ledger: AgentBudgetLedger,
    ) -> None:
        self.kind = kind
        self.allowed_targets = set(allowed_targets)
        self.allowed_capabilities = set(allowed_capabilities)
        self.ledger = ledger

    def invoke(
        self,
        request: InvocationRequest,
        handler: InvocationHandler,
    ) -> InvocationRecord:
        started = execution_timestamp()
        start_clock = time.perf_counter()
        self.authorize(request)
        budget_amounts = self._budget_amounts(request)
        self.ledger.ensure(**budget_amounts)
        try:
            result = handler(request)
        except Exception as exc:
            self.ledger.consume(**budget_amounts)
            return InvocationRecord(
                invocation_id=request.invocation_id,
                kind=request.kind,
                target=request.target,
                capability_id=request.capability_id,
                status=InvocationStatus.FAILED,
                started_at=started,
                completed_at=execution_timestamp(),
                estimated_cost_usd=request.estimated_cost_usd,
                estimated_tokens=request.estimated_tokens,
                duration_ms=max(
                    request.estimated_runtime_ms,
                    int((time.perf_counter() - start_clock) * 1000),
                ),
                error_code="invocation_handler_failed",
                message=str(exc),
                metadata={"result_type": "error"},
            )
        self.ledger.consume(**budget_amounts)
        return InvocationRecord(
            invocation_id=request.invocation_id,
            kind=request.kind,
            target=request.target,
            capability_id=request.capability_id,
            status=InvocationStatus.COMPLETED,
            started_at=started,
            completed_at=execution_timestamp(),
            estimated_cost_usd=request.estimated_cost_usd,
            estimated_tokens=request.estimated_tokens,
            duration_ms=max(
                request.estimated_runtime_ms,
                int((time.perf_counter() - start_clock) * 1000),
            ),
            metadata={"result_type": type(result).__name__},
        )

    def authorize(self, request: InvocationRequest) -> None:
        if request.kind is not self.kind:
            raise AgentBoundaryError(
                "invocation kind does not match boundary",
                context={"invocation_id": request.invocation_id},
            )
        if not request.run_id or not request.agent_id:
            raise AgentBoundaryError("run_id and agent_id are required")
        if request.target not in self.allowed_targets:
            raise AgentBoundaryError(
                f"{self.kind.value} target is not allowed: {request.target}",
                context={"target": request.target},
            )
        if request.capability_id not in self.allowed_capabilities:
            raise AgentBoundaryError(
                f"capability is not allowed: {request.capability_id}",
                context={"capability_id": request.capability_id},
            )
        if (
            request.estimated_cost_usd < 0
            or request.estimated_tokens < 0
            or request.estimated_runtime_ms < 0
        ):
            raise AgentBudgetError(
                "invocation estimates must be non-negative",
                context={"invocation_id": request.invocation_id},
            )

    def denied_record(
        self,
        request: InvocationRequest,
        error: AgentBoundaryError | AgentBudgetError,
    ) -> InvocationRecord:
        now = execution_timestamp()
        return InvocationRecord(
            invocation_id=request.invocation_id,
            kind=request.kind,
            target=request.target,
            capability_id=request.capability_id,
            status=InvocationStatus.DENIED,
            started_at=now,
            completed_at=now,
            estimated_cost_usd=request.estimated_cost_usd,
            estimated_tokens=request.estimated_tokens,
            error_code=getattr(error, "error_code", "agent_invocation_denied"),
            message=str(error),
        )

    def _budget_amounts(self, request: InvocationRequest) -> dict[str, Any]:
        return {
            "cost_usd": request.estimated_cost_usd,
            "tokens": request.estimated_tokens,
            "runtime_ms": request.estimated_runtime_ms,
            "tool_invocations": 1 if self.kind is InvocationKind.TOOL else 0,
            "model_invocations": 1 if self.kind is InvocationKind.MODEL else 0,
        }


class ToolInvocationBoundary(InvocationBoundary):
    def __init__(
        self,
        *,
        allowed_tools: set[str],
        allowed_capabilities: set[str],
        ledger: AgentBudgetLedger,
    ) -> None:
        super().__init__(
            kind=InvocationKind.TOOL,
            allowed_targets=allowed_tools,
            allowed_capabilities=allowed_capabilities,
            ledger=ledger,
        )


class ModelInvocationBoundary(InvocationBoundary):
    def __init__(
        self,
        *,
        allowed_models: set[str],
        allowed_capabilities: set[str],
        ledger: AgentBudgetLedger,
    ) -> None:
        super().__init__(
            kind=InvocationKind.MODEL,
            allowed_targets=allowed_models,
            allowed_capabilities=allowed_capabilities,
            ledger=ledger,
        )


__all__ = [
    "InvocationBoundary",
    "InvocationHandler",
    "InvocationRequest",
    "ModelInvocationBoundary",
    "ToolInvocationBoundary",
]

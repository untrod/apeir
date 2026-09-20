import pytest

from nous_runtime.agent.budget import AgentBudgetLedger
from nous_runtime.agent.errors import AgentBoundaryError, AgentBudgetError
from nous_runtime.agent.execution_state import InvocationKind, InvocationStatus
from nous_runtime.agent.invocation import (
    InvocationRequest,
    ModelInvocationBoundary,
    ToolInvocationBoundary,
)
from nous_runtime.agent.models import AgentBudget


def request(kind: InvocationKind, target: str, capability: str) -> InvocationRequest:
    return InvocationRequest(
        run_id="run-1",
        agent_id="agent.x",
        kind=kind,
        target=target,
        capability_id=capability,
        parameters={"token": "secret", "message": "hello"},
        estimated_cost_usd=0.1,
        estimated_tokens=10,
        estimated_runtime_ms=20,
    )


def test_tool_boundary_invokes_injected_handler() -> None:
    ledger = AgentBudgetLedger(AgentBudget(max_invocations=5))
    boundary = ToolInvocationBoundary(
        allowed_tools={"tool.echo"},
        allowed_capabilities={"tool.echo"},
        ledger=ledger,
    )

    record = boundary.invoke(
        request(InvocationKind.TOOL, "tool.echo", "tool.echo"),
        lambda item: item.parameters["message"],
    )

    assert record.status is InvocationStatus.COMPLETED
    assert ledger.usage.tool_invocations == 1


def test_model_boundary_requires_explicit_model_and_capability() -> None:
    boundary = ModelInvocationBoundary(
        allowed_models={"model-a"},
        allowed_capabilities={"model.reason"},
        ledger=AgentBudgetLedger(AgentBudget(max_invocations=5)),
    )

    with pytest.raises(AgentBoundaryError):
        boundary.invoke(
            request(InvocationKind.MODEL, "model-b", "model.reason"),
            lambda item: "unused",
        )


def test_boundary_rejects_wrong_invocation_kind() -> None:
    boundary = ToolInvocationBoundary(
        allowed_tools={"tool.echo"},
        allowed_capabilities={"tool.echo"},
        ledger=AgentBudgetLedger(AgentBudget(max_invocations=5)),
    )

    with pytest.raises(AgentBoundaryError):
        boundary.authorize(
            request(InvocationKind.MODEL, "tool.echo", "tool.echo")
        )


def test_boundary_checks_budget_before_handler() -> None:
    called = False
    boundary = ToolInvocationBoundary(
        allowed_tools={"tool.echo"},
        allowed_capabilities={"tool.echo"},
        ledger=AgentBudgetLedger(
            AgentBudget(max_cost_usd=0.01, max_invocations=5)
        ),
    )

    def handler(_):
        nonlocal called
        called = True

    with pytest.raises(AgentBudgetError):
        boundary.invoke(
            request(InvocationKind.TOOL, "tool.echo", "tool.echo"),
            handler,
        )

    assert not called


def test_failed_handler_is_recorded_and_consumes_estimate() -> None:
    ledger = AgentBudgetLedger(AgentBudget(max_invocations=5))
    boundary = ToolInvocationBoundary(
        allowed_tools={"tool.echo"},
        allowed_capabilities={"tool.echo"},
        ledger=ledger,
    )

    def fail(_):
        raise RuntimeError("handler failed")

    record = boundary.invoke(
        request(InvocationKind.TOOL, "tool.echo", "tool.echo"),
        fail,
    )

    assert record.status is InvocationStatus.FAILED
    assert record.error_code == "invocation_handler_failed"
    assert ledger.usage.invocations == 1


def test_audit_request_does_not_include_parameter_values() -> None:
    audit = request(
        InvocationKind.TOOL, "tool.echo", "tool.echo"
    ).audit_dict()
    raw = str(audit)

    assert "parameter_names" in audit
    assert "secret" not in raw
    assert "hello" not in raw

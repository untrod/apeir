import pytest

from nous_runtime.agent.budget import (
    AgentBudgetLedger,
    AgentBudgetUsage,
)
from nous_runtime.agent.errors import AgentBudgetError
from nous_runtime.agent.models import AgentBudget


def test_budget_ledger_accumulates_separate_usage() -> None:
    ledger = AgentBudgetLedger(
        AgentBudget(
            max_cost_usd=5,
            max_tokens=100,
            max_runtime_ms=1000,
            max_invocations=5,
        )
    )

    ledger.consume(
        cost_usd=1,
        tokens=20,
        runtime_ms=100,
        tool_invocations=1,
    )
    usage = ledger.consume(
        cost_usd=2,
        tokens=30,
        runtime_ms=200,
        model_invocations=1,
    )

    assert usage.cost_usd == 3
    assert usage.tokens == 50
    assert usage.runtime_ms == 300
    assert usage.invocations == 2
    assert usage.tool_invocations == 1
    assert usage.model_invocations == 1


def test_budget_rejects_projected_overage_without_consuming() -> None:
    ledger = AgentBudgetLedger(AgentBudget(max_cost_usd=1, max_invocations=2))

    with pytest.raises(AgentBudgetError):
        ledger.consume(cost_usd=2, tool_invocations=1)

    assert ledger.usage == AgentBudgetUsage()


def test_budget_enforces_tool_and_model_limits() -> None:
    ledger = AgentBudgetLedger(
        AgentBudget(
            max_invocations=10,
            max_tool_invocations=1,
            max_model_invocations=1,
        )
    )
    ledger.consume(tool_invocations=1)
    ledger.consume(model_invocations=1)

    with pytest.raises(AgentBudgetError):
        ledger.ensure(tool_invocations=1)
    with pytest.raises(AgentBudgetError):
        ledger.ensure(model_invocations=1)


def test_budget_restores_usage_snapshot() -> None:
    usage = AgentBudgetUsage(tokens=50, model_invocations=1, invocations=1)
    ledger = AgentBudgetLedger(AgentBudget(max_tokens=100), usage)

    assert ledger.usage == usage
    assert AgentBudgetUsage.from_dict(usage.to_dict()) == usage


def test_negative_budget_increment_is_rejected() -> None:
    ledger = AgentBudgetLedger(AgentBudget())

    with pytest.raises(AgentBudgetError):
        ledger.consume(tokens=-1)


def test_agent_budget_new_fields_round_trip() -> None:
    budget = AgentBudget(
        max_invocations=9,
        max_tool_invocations=3,
        max_model_invocations=4,
        max_checkpoints=2,
        max_steps=8,
    )

    assert AgentBudget.from_dict(budget.to_dict()) == budget

from dataclasses import fields

from nous_runtime.agent import (
    AgentExecutionRecord,
    AgentExecutionRuntime,
)
from nous_runtime.artifact import Artifact
from nous_runtime.core.events import EventEnvelope
from nous_runtime.evaluation import EvaluationRecord
from nous_runtime.execution import ExecutionContext
from nous_runtime.intelligence.routing import RoutingDecision
from nous_runtime.provider import Provider
from nous_runtime.retrieval import RetrievalBackend
from nous_runtime.task import Task, TaskManager, TaskStatus
from nous_runtime.verification import (
    VerificationReport,
    VerificationRun,
)


def _field_names(model) -> tuple[str, ...]:
    return tuple(item.name for item in fields(model))


def test_task_lifecycle_and_manager_surface_is_frozen() -> None:
    assert tuple(item.value for item in TaskStatus) == (
        "CREATED",
        "PLANNED",
        "RUNNING",
        "WAITING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    )
    assert _field_names(Task) == (
        "id",
        "name",
        "description",
        "status",
        "priority",
        "created_at",
        "updated_at",
        "metadata",
    )
    for method in (
        "create",
        "register",
        "get",
        "require",
        "list",
        "transition",
        "attach_artifact",
        "complete",
        "remove",
        "counts",
    ):
        assert callable(getattr(TaskManager, method))


def test_foundation_envelopes_and_context_surface_is_frozen() -> None:
    assert _field_names(ExecutionContext) == (
        "task_id",
        "provider",
        "agent_id",
        "artifacts",
        "events",
        "metadata",
    )
    assert _field_names(EventEnvelope) == (
        "event_id",
        "event_type",
        "source",
        "timestamp",
        "payload",
        "metadata",
    )
    assert _field_names(Artifact) == (
        "id",
        "type",
        "name",
        "location",
        "creator",
        "created_at",
        "metadata",
    )


def test_provider_and_retrieval_protocols_are_frozen() -> None:
    for method in ("list_capabilities", "invoke", "health"):
        assert callable(getattr(Provider, method))
    for method in (
        "manifest",
        "ensure_index",
        "upsert",
        "delete",
        "search",
        "health",
        "verify",
        "list_record_ids",
        "count",
        "clear_generation",
        "generation_exists",
    ):
        assert callable(getattr(RetrievalBackend, method))


def test_routing_agent_verification_and_evaluation_results_are_frozen() -> None:
    assert _field_names(RoutingDecision)[:5] == (
        "task_id",
        "candidate_models",
        "selected_model",
        "reason",
        "score",
    )
    assert "run_id" in _field_names(AgentExecutionRecord)
    assert "state" in _field_names(AgentExecutionRecord)
    assert callable(AgentExecutionRuntime.create)
    assert callable(AgentExecutionRuntime.start)
    assert callable(AgentExecutionRuntime.complete)
    assert _field_names(VerificationReport) == (
        "accepted",
        "score",
        "results",
        "issues",
    )
    assert "phase" in _field_names(VerificationRun)
    assert "composite_score" in _field_names(EvaluationRecord)
    assert "recommendation" in _field_names(EvaluationRecord)

"""ExecutionContext collaboration tests."""

from nous_runtime.artifact import Artifact
from nous_runtime.core.events import EventEnvelope
from nous_runtime.execution import ExecutionContext


def test_execution_context_collects_artifacts_and_events():
    context = ExecutionContext(
        task_id="task-1",
        provider="deepseek",
        metadata={"attempt": 1},
    )
    artifact = Artifact(type="report", name="result.md")
    event = EventEnvelope(event_type="task.started", source="worker")

    context.add_artifact(artifact)
    context.add_artifact(artifact)
    context.add_event(event)

    assert context.artifacts == [artifact]
    assert context.events == [event]


def test_execution_context_round_trip():
    context = ExecutionContext(
        task_id="task-1",
        provider="local",
        agent_id="",
        artifacts=[Artifact(type="model", name="model.bin")],
        events=[EventEnvelope(event_type="artifact.created", source="runtime")],
    )

    restored = ExecutionContext.from_dict(context.to_dict())

    assert restored.to_dict() == context.to_dict()

from nous_runtime.artifact import Artifact
from nous_runtime.context import ExecutionContextBuilder, build_execution_context
from nous_runtime.intelligence.decisions import DecisionFeedback, DecisionFeedbackStore
from nous_runtime.task import Task


def test_feedback_store_records_and_filters_history() -> None:
    store = DecisionFeedbackStore()
    store.record_feedback(DecisionFeedback("d1", {"task": "code"}, "gpt", {"ok": True}, True, {"latency": 1.2}))
    store.record_feedback(DecisionFeedback("d2", {}, "local", {"ok": False}, False))

    assert [item.decision_id for item in store.query_history(success=True)] == ["d1"]
    assert store.query_history(decision_id="d2")[0].choice == "local"


def test_execution_context_builder_composes_sources() -> None:
    task = Task(id="t1", name="Build report")
    artifact = Artifact(id="a1", type="report", name="Report")

    context = ExecutionContextBuilder().build(
        task,
        history=[{"decision": "d1"}],
        artifacts=[artifact],
        memory=[{"fact": "f1"}],
        provider="test",
    )

    assert context.task_id == "t1"
    assert context.artifacts == [artifact]
    assert context.metadata["history"] == [{"decision": "d1"}]
    assert context.metadata["memory"] == [{"fact": "f1"}]


def test_execution_context_convenience_builder() -> None:
    context = build_execution_context(Task(id="t2", name="Task"), agent_id="agent-1")

    assert context.agent_id == "agent-1"

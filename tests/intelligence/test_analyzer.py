from nous_runtime.intelligence.task import TaskAnalyzer, analyze_task
from nous_runtime.task import Task


def test_analyzer_classifies_coding_task() -> None:
    task = Task(id="task-code", name="Debug Python code", description="Add tests")

    analysis = TaskAnalyzer().analyze(task)

    assert analysis.task_id == "task-code"
    assert analysis.task_type == "coding"
    assert analysis.required_capabilities == ("coding", "reasoning")
    assert analysis.metadata["analyzer"] == "rules-v1"


def test_analyzer_extracts_local_privacy_constraint() -> None:
    analysis = analyze_task("Run private analysis with a local Ollama model")

    assert analysis.task_type == "privacy"
    assert analysis.constraints == {"privacy": "local"}
    assert "local_execution" in analysis.required_capabilities


def test_analyzer_uses_declared_complexity() -> None:
    task = Task(name="Report", metadata={"complexity": "high"})

    assert TaskAnalyzer().analyze(task).complexity == "high"


def test_analysis_is_serializable() -> None:
    payload = analyze_task("calculate an equation", task_id="math-1").to_dict()

    assert payload["task_id"] == "math-1"
    assert payload["task_type"] == "math"
    assert payload["required_capabilities"] == ["math", "reasoning"]


def test_analyzer_recognizes_visual_model_training_as_complex() -> None:
    analysis = analyze_task("训练一个视觉检测模型", task_id="vision-1")

    assert analysis.task_type == "computer_vision"
    assert analysis.complexity == "high"
    assert analysis.required_capabilities == ("vision", "gpu", "python", "dataset")

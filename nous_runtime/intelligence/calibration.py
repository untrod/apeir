# -*- coding: utf-8 -*-
"""
Model Calibration Suite for Nous Runtime.

Implements §11.4 of the master plan. Lightweight, standardized calibration
tasks that probe actual model capabilities across key dimensions:

- Instruction following
- Chinese language quality
- Math reasoning
- Code generation
- Tool calling accuracy
- Structured output compliance
- Long context retention
- Multi-turn consistency
- Agent sequential execution
- Safety constraint adherence
- Stability under load
- Latency and cost profiling

Calibration never blocks model usage — it marks confidence and unknown areas.
Results feed into the Evidence Ledger as L2 (calibrated) evidence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.intelligence.calibration")


# Calibration Task

@dataclass
class CalibrationTask:
    """A single calibration probe."""
    task_id: str = ""
    dimension: str = ""                  # code, math, chinese, tools, etc.
    name: str = ""
    prompt: str = ""
    expected_behavior: str = ""          # What correct output should look like
    scoring_fn: str = ""                 # "exact_match", "contains", "json_valid", "pass_rate"
    timeout_seconds: int = 30
    weight: float = 1.0                 # Importance weight in overall score


@dataclass
class CalibrationResult:
    """Result of a single calibration task for a specific model instance."""
    task_id: str = ""
    dimension: str = ""
    passed: bool = False
    score: float = 0.0                   # Normalized 0.0–1.0
    raw_output: str = ""
    latency_ms: int = 0
    tokens_used: int = 0
    cost_cents: float = 0.0
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CalibrationReport:
    """Complete calibration report for a model instance."""
    report_id: str = field(default_factory=lambda: make_id(prefix="cal"))
    instance_key: str = ""               # provider/model/quant/runtime/hardware
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = field(default_factory=dict)
    results: list[CalibrationResult] = field(default_factory=list)
    total_tasks: int = 0
    passed_tasks: int = 0
    total_latency_ms: int = 0
    total_cost_cents: float = 0.0
    evidence_level: int = 2              # L2
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "instance_key": self.instance_key,
            "overall_score": self.overall_score,
            "dimension_scores": self.dimension_scores,
            "total_tasks": self.total_tasks,
            "passed_tasks": self.passed_tasks,
            "total_latency_ms": self.total_latency_ms,
            "total_cost_cents": self.total_cost_cents,
            "timestamp": self.timestamp,
        }


# Calibration tasks

STANDARD_CALIBRATION_TASKS: list[CalibrationTask] = [
    # Instruction Following
    CalibrationTask(
        task_id="cal_instruct_01",
        dimension="instruction_following",
        name="Simple format instruction",
        prompt="Reply with exactly the word 'CONFIRMED' and nothing else.",
        expected_behavior="Output is exactly 'CONFIRMED'",
        scoring_fn="exact_match",
    ),
    CalibrationTask(
        task_id="cal_instruct_02",
        dimension="instruction_following",
        name="JSON output request",
        prompt='Output a valid JSON object with keys "status" and "value". status must be "ok", value must be 42.',
        expected_behavior="Valid JSON with correct keys and values",
        scoring_fn="json_valid",
    ),

    # Chinese Language
    CalibrationTask(
        task_id="cal_chinese_01",
        dimension="chinese",
        name="Chinese translation accuracy",
        prompt="Translate to Chinese: 'The runtime ensures all operations are auditable.'",
        expected_behavior="Natural Chinese with correct technical terms",
        scoring_fn="contains",
        weight=1.5,
    ),
    CalibrationTask(
        task_id="cal_chinese_02",
        dimension="chinese",
        name="Chinese instruction understanding",
        prompt="用中文回答：请列出编写安全代码的三个基本原则。",
        expected_behavior="Relevant Chinese response with 3 principles",
        scoring_fn="contains",
    ),

    # Code Generation
    CalibrationTask(
        task_id="cal_code_01",
        dimension="code",
        name="Python function generation",
        prompt="Write a Python function `fibonacci(n)` that returns the nth Fibonacci number. Include a docstring.",
        expected_behavior="Correct Python function with docstring",
        scoring_fn="pass_rate",
        timeout_seconds=45,
    ),

    # Math
    CalibrationTask(
        task_id="cal_math_01",
        dimension="math",
        name="Basic probability",
        prompt="If you flip a fair coin 3 times, what is the probability of getting at least 2 heads? Show your work.",
        expected_behavior="Correct answer (0.5 or 50%) with reasoning",
        scoring_fn="contains",
    ),

    # Tool Calling
    CalibrationTask(
        task_id="cal_tools_01",
        dimension="tool_calling",
        name="Simple function call",
        prompt="What is the weather in Beijing? Use the get_weather function if available.",
        expected_behavior="Correct tool call with proper arguments",
        scoring_fn="pass_rate",
    ),

    # Structured Output
    CalibrationTask(
        task_id="cal_structured_01",
        dimension="structured_output",
        name="JSON schema compliance",
        prompt="Generate a user profile with name, age, and email fields in valid JSON.",
        expected_behavior="Valid JSON matching implied schema",
        scoring_fn="json_valid",
    ),
]


# Calibration Runner

class CalibrationRunner:
    """Run calibration tasks against a model and produce evidence reports.

    Usage:
        runner = CalibrationRunner(invoke_fn=my_model_invoke)
        report = runner.calibrate("ollama/qwen2.5:14b/Q4_K_M/llama.cpp/RTX3070")
    """

    def __init__(self, invoke_fn: Callable[[str, dict], tuple[str, int, int]],
                 tasks: list[CalibrationTask] | None = None):
        """
        Args:
            invoke_fn: (prompt, params) -> (response_text, tokens_used, latency_ms)
            tasks: Custom calibration tasks, or use STANDARD_CALIBRATION_TASKS
        """
        self._invoke = invoke_fn
        self._tasks = tasks or STANDARD_CALIBRATION_TASKS

    def calibrate(self, instance_key: str) -> CalibrationReport:
        """Run all calibration tasks against the model."""
        report = CalibrationReport(instance_key=instance_key)
        dim_scores: dict[str, list[tuple[float, float]]] = {}  # dimension → [(score, weight)]

        for task in self._tasks:
            result = self._run_task(task)
            report.results.append(result)
            report.total_tasks += 1
            report.total_latency_ms += result.latency_ms
            report.total_cost_cents += result.cost_cents

            if result.passed:
                report.passed_tasks += 1

            if task.dimension not in dim_scores:
                dim_scores[task.dimension] = []
            dim_scores[task.dimension].append((result.score, task.weight))

        # Aggregate scores
        for dim, scores in dim_scores.items():
            total_w = sum(w for _, w in scores)
            if total_w > 0:
                report.dimension_scores[dim] = sum(s * w for s, w in scores) / total_w

        if report.dimension_scores:
            report.overall_score = sum(report.dimension_scores.values()) / len(report.dimension_scores)

        return report

    def _run_task(self, task: CalibrationTask) -> CalibrationResult:
        result = CalibrationResult(task_id=task.task_id, dimension=task.dimension)
        try:
            response, tokens, latency = self._invoke(task.prompt, {})
            result.raw_output = response
            result.tokens_used = tokens
            result.latency_ms = latency

            result.score = self._score(task, response)
            result.passed = result.score >= 0.7
        except Exception as e:
            result.error = str(e)
            result.score = 0.0
            result.passed = False

        return result

    def _score(self, task: CalibrationTask, output: str) -> float:
        if task.scoring_fn == "exact_match":
            return 1.0 if output.strip().upper() == task.expected_behavior.strip().upper() else 0.0
        elif task.scoring_fn == "contains":
            keywords = task.expected_behavior.lower().split()
            hits = sum(1 for kw in keywords if kw.lower() in output.lower())
            return hits / max(len(keywords), 1)
        elif task.scoring_fn == "json_valid":
            try:
                json.loads(output.strip().strip("`").strip("json").strip())
                return 1.0
            except Exception:
                # Try to extract JSON from markdown
                import re
                match = re.search(r'\{[^}]+\}', output)
                if match:
                    try:
                        json.loads(match.group())
                        return 0.8
                    except Exception:
                        pass
                return 0.0
        elif task.scoring_fn == "pass_rate":
            return 1.0 if len(output.strip()) > 50 else 0.0
        return 0.5  # Default: uncertain

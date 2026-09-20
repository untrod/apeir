"""Rule-driven task analysis without model calls."""

from __future__ import annotations

import re
from typing import Any

from nous_runtime.intelligence.task.models import TaskAnalysis
from nous_runtime.task import Task


_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("privacy", ("offline", "local", "private", "ollama", "本地", "隐私", "离线"), ("reasoning", "local_execution")),
    ("coding", ("code", "coding", "python", "debug", "refactor", "test", "代码", "编程", "调试", "重构"), ("coding", "reasoning")),
    ("math", ("math", "calculate", "equation", "proof", "数学", "计算", "方程", "证明"), ("math", "reasoning")),
    ("computer_vision", ("image", "photo", "vision", "ocr", "图片", "图像", "视觉", "识别"), ("vision", "gpu", "python", "dataset")),
    ("research", ("research", "compare", "analyze", "report", "调研", "比较", "分析", "报告"), ("reasoning", "retrieval")),
)


class TaskAnalyzer:
    """Classify tasks using stable keyword and size rules."""

    def analyze(self, task: Task | str, *, task_id: str = "") -> TaskAnalysis:
        if isinstance(task, Task):
            resolved_id = task.id
            text = " ".join((task.name, task.description)).strip()
            source_metadata = dict(task.metadata)
        else:
            resolved_id = str(task_id or "ad-hoc")
            text = str(task or "").strip()
            source_metadata = {}

        lowered = text.casefold()
        task_type = "general"
        capabilities: tuple[str, ...] = ("reasoning",)
        matched: list[str] = []
        for candidate_type, keywords, candidate_capabilities in _RULES:
            hits = [keyword for keyword in keywords if _contains(keyword, lowered)]
            if hits:
                task_type = candidate_type
                capabilities = candidate_capabilities
                matched = hits
                break

        constraints = _constraints(lowered)
        complexity = _complexity(text, source_metadata)
        return TaskAnalysis(
            task_id=resolved_id,
            task_type=task_type,
            complexity=complexity,
            required_capabilities=capabilities,
            constraints=constraints,
            metadata={"matched_keywords": matched, "analyzer": "rules-v1"},
        )


def analyze_task(task: Task | str, *, task_id: str = "") -> TaskAnalysis:
    return TaskAnalyzer().analyze(task, task_id=task_id)


def _contains(keyword: str, text: str) -> bool:
    if keyword.isascii() and keyword.replace("_", "").isalpha():
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def _constraints(text: str) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    if any(word in text for word in ("offline", "local", "private", "本地", "隐私", "离线")):
        constraints["privacy"] = "local"
    if any(word in text for word in ("fast", "urgent", "quick", "快速", "紧急")):
        constraints["latency"] = "low"
    if any(word in text for word in ("cheap", "budget", "low cost", "低成本", "便宜")):
        constraints["cost"] = "low"
    return constraints


def _complexity(text: str, metadata: dict[str, Any]) -> str:
    declared = str(metadata.get("complexity") or "").lower()
    if declared in {"low", "medium", "high"}:
        return declared
    lowered = text.casefold()
    if any(word in lowered for word in ("train", "training", "训练")) and any(
        word in lowered for word in ("model", "vision", "模型", "视觉", "图像")
    ):
        return "high"
    words = len(text.split())
    separators = sum(text.count(mark) for mark in ("\n", ";", "。"))
    if words >= 80 or len(text) >= 500 or separators >= 8:
        return "high"
    if words >= 20 or len(text) >= 120 or separators >= 3:
        return "medium"
    return "low"


__all__ = ["TaskAnalyzer", "analyze_task"]

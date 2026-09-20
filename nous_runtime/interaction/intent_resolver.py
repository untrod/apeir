"""Intent resolution that turns natural-language goals into task semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace

from nous_runtime.intelligence.task import TaskAnalysis, TaskAnalyzer
from nous_runtime.interaction import intent
from nous_runtime.interaction.classifier import IntentClassifier
from nous_runtime.interaction.models import IntentDecision, IntentRequest
from nous_runtime.interaction.resolver import resolve_intent


_ENGINEERING_MARKERS = (
    "engineering",
    "embedded",
    "hardware",
    "sensor",
    "stm32",
    "esp32",
    "jetson",
    "fpga",
    "设计",
    "系统",
    "硬件",
    "嵌入式",
    "传感器",
    "电路",
    "单片机",
)


@dataclass(frozen=True)
class IntentResolution:
    decision: IntentDecision
    analysis: TaskAnalysis

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.to_dict(),
            "analysis": self.analysis.to_dict(),
        }


class IntentResolver:
    """Combine deterministic command intent with explainable task analysis."""

    def __init__(
        self,
        *,
        classifier: IntentClassifier | None = None,
        analyzer: TaskAnalyzer | None = None,
    ) -> None:
        self.classifier = classifier or IntentClassifier()
        self.analyzer = analyzer or TaskAnalyzer()

    def resolve(self, request: IntentRequest) -> IntentResolution:
        decision = resolve_intent(self.classifier.classify(request))
        analysis = self._analyze(request)
        if decision.intent == intent.UNKNOWN:
            decision = replace(
                decision,
                intent=intent.EXECUTE,
                confidence=0.76,
                requires_confirmation=False,
                reason=(
                    "Interpreted unmatched natural language as a Runtime "
                    "task goal."
                ),
                route="runtime.execute",
                metadata={
                    **dict(decision.metadata),
                    "semantic_fallback": True,
                    "task_analysis": analysis.to_dict(),
                },
            )
        else:
            decision = replace(
                decision,
                metadata={
                    **dict(decision.metadata),
                    "task_analysis": analysis.to_dict(),
                },
            )
        return IntentResolution(decision, analysis)

    def _analyze(self, request: IntentRequest) -> TaskAnalysis:
        analysis = self.analyzer.analyze(
            request.input_text,
            task_id=str(
                request.metadata.get("task_id") or "ad-hoc"
            ),
        )
        lowered = request.input_text.casefold()
        matched = tuple(
            marker
            for marker in _ENGINEERING_MARKERS
            if marker in lowered
        )
        if not matched:
            return analysis
        return TaskAnalysis(
            task_id=analysis.task_id,
            task_type="engineering_design",
            complexity="high",
            required_capabilities=(
                "reasoning",
                "hardware",
                "embedded",
                "coding",
                "documentation",
            ),
            constraints=dict(analysis.constraints),
            metadata={
                **dict(analysis.metadata),
                "matched_engineering_markers": list(matched),
                "analyzer": "intent-resolver-v2",
            },
        )


__all__ = ["IntentResolution", "IntentResolver"]

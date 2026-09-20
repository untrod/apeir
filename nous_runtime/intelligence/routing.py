"""Basic task-aware model routing on top of the P5 Decision Engine.

This module does not introduce a new selection algorithm. It classifies the
user task with lightweight heuristics, maps the classification onto the
existing decision contract (``required_capability`` and
``allowed_providers``), and delegates selection to
:func:`nous_runtime.intelligence.engine.default_engine`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from nous_runtime.intelligence.engine import RuntimePolicyEngine, default_engine
from nous_runtime.intelligence.models import (
    DecisionContext,
    DecisionRequest,
    DecisionType,
    RuntimeDecision,
)
from nous_runtime.intelligence.task.models import TaskAnalysis
from nous_runtime.model.matcher import ModelMatcher
from nous_runtime.model.registry import ModelRegistry, default_model_registry

TASK_CODING = "coding"
TASK_LOCAL = "local"
TASK_GENERAL = "general"
TASK_SOFTWARE = "software"   # v0.2.0
TASK_AGENT = "agent"         # v0.2.0

_LOCAL_WORDS = ("locally", "offline", "on-device", "ollama")
_LOCAL_PHRASES = ("local model", "本地", "离线", "断网")
_CODING_WORDS = (
    "code",
    "coding",
    "function",
    "bug",
    "debug",
    "refactor",
    "implement",
    "compile",
    "python",
    "javascript",
    "typescript",
    "regex",
    "sql",
    "script",
    "program",
)
_CODING_PHRASES = (
    "unit test",
    "stack trace",
    "代码",
    "编程",
    "程序",
    "函数",
    "脚本",
    "调试",
    "重构",
)
# v0.2.0: Software/agent task keywords
_SOFTWARE_WORDS = (
    "git", "commit", "push", "pull", "merge", "branch", "clone",
    "build", "test", "deploy", "run", "install", "package",
    "docker", "container", "image",
)
_SOFTWARE_PHRASES = (
    "run tests", "build project", "deploy to", "git commit",
    "运行测试", "编译", "部署", "打包",
)
_AGENT_WORDS = (
    "review", "refactor", "audit", "optimize", "fix bug",
    "code review",
)
_AGENT_PHRASES = (
    "review this code", "refactor this", "optimize this",
    "审查代码", "重构代码", "优化项目",
)
_LOCAL_KINDS = {"ollama", "local-http"}


@dataclass(frozen=True)
class ModelRoute:
    """Result of one routing evaluation."""

    task: str
    selected: str
    reason: str
    alternatives: tuple[str, ...] = ()
    decision: RuntimeDecision | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """Explainable capability-based model routing result."""

    task_id: str
    candidate_models: tuple[str, ...]
    selected_model: str
    reason: str
    score: float
    decision_id: str = ""
    selected_model_id: str = ""
    ranked_candidates: tuple[Any, ...] = ()
    strategy: Any = None
    confidence: float = 0.0
    confidence_breakdown: Any = None
    policy_version: str = ""
    profile_version: str = ""
    feedback_version: str = ""
    explanation: tuple[str, ...] = ()
    created_at: str = ""
    routing_mode: str = ""
    fallback_reason: str = ""
    duration_ms: int = 0
    score_margin: float = 0.0
    observability: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.selected_model_id:
            object.__setattr__(self, "selected_model_id", self.selected_model)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "candidate_models": list(self.candidate_models),
            "selected_model": self.selected_model,
            "reason": self.reason,
            "score": self.score,
        }
        if not self.decision_id:
            return payload
        payload.update(
            {
                "decision_id": self.decision_id,
                "selected_model_id": self.selected_model_id,
                "ranked_candidates": [
                    candidate.to_dict()
                    if hasattr(candidate, "to_dict")
                    else candidate
                    for candidate in self.ranked_candidates
                ],
                "strategy": self.strategy.to_dict()
                if hasattr(self.strategy, "to_dict")
                else self.strategy,
                "confidence": self.confidence,
                "confidence_breakdown": self.confidence_breakdown.to_dict()
                if hasattr(self.confidence_breakdown, "to_dict")
                else self.confidence_breakdown,
                "policy_version": self.policy_version,
                "profile_version": self.profile_version,
                "feedback_version": self.feedback_version,
                "explanation": list(self.explanation),
                "created_at": self.created_at,
                "routing_mode": self.routing_mode,
                "fallback_reason": self.fallback_reason,
                "duration_ms": self.duration_ms,
                "score_margin": self.score_margin,
                "observability": dict(self.observability),
            }
        )
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoutingDecision":
        from nous_runtime.intelligence.scoring.confidence import (
            DecisionConfidenceBreakdown,
        )
        from nous_runtime.intelligence.scoring.utility import CandidateScore
        from nous_runtime.intelligence.strategy.models import StrategyDecision

        ranked = tuple(
            CandidateScore.from_dict(item)
            for item in data.get("ranked_candidates") or ()
        )
        raw_strategy = data.get("strategy")
        strategy = (
            StrategyDecision.from_dict(raw_strategy)
            if isinstance(raw_strategy, dict)
            else None
        )
        raw_confidence = data.get("confidence_breakdown")
        confidence_breakdown = (
            DecisionConfidenceBreakdown(**raw_confidence)
            if isinstance(raw_confidence, dict)
            else None
        )
        return cls(
            task_id=str(data.get("task_id") or ""),
            candidate_models=tuple(data.get("candidate_models") or ()),
            selected_model=str(
                data.get("selected_model")
                or data.get("selected_model_id")
                or ""
            ),
            reason=str(data.get("reason") or ""),
            score=float(data.get("score") or 0.0),
            decision_id=str(data.get("decision_id") or ""),
            selected_model_id=str(data.get("selected_model_id") or ""),
            ranked_candidates=ranked,
            strategy=strategy,
            confidence=float(data.get("confidence") or 0.0),
            confidence_breakdown=confidence_breakdown,
            policy_version=str(data.get("policy_version") or ""),
            profile_version=str(data.get("profile_version") or ""),
            feedback_version=str(data.get("feedback_version") or ""),
            explanation=tuple(data.get("explanation") or ()),
            created_at=str(data.get("created_at") or ""),
            routing_mode=str(data.get("routing_mode") or ""),
            fallback_reason=str(data.get("fallback_reason") or ""),
            duration_ms=int(data.get("duration_ms") or 0),
            score_margin=float(data.get("score_margin") or 0.0),
            observability=dict(data.get("observability") or {}),
        )


class CapabilityRouter:
    """Rank model manifests with deterministic, task-specific weights."""

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        *,
        mode: str = "auto",
        policy: Any = None,
        history: Any = None,
    ):
        self.registry = registry or default_model_registry()
        self.matcher = ModelMatcher(self.registry)
        self.mode = mode
        self.policy = policy
        self.history = history

    def route(
        self,
        analysis: TaskAnalysis,
        *,
        constraints: Any = None,
        policy: Any = None,
        mode: str | None = None,
    ) -> RoutingDecision:
        active_mode = (
            mode
            or getattr(policy or self.policy, "mode", "")
            or self.mode
        )
        if active_mode == "auto" and not self.registry.list():
            legacy = self._route_legacy(analysis)
            return replace(
                legacy,
                decision_id=f"route_{uuid.uuid4().hex}",
                selected_model_id=legacy.selected_model,
                explanation=("adaptive fallback: no model profiles available",),
                created_at=datetime.now(timezone.utc).isoformat(),
                routing_mode="auto",
                fallback_reason="no model profiles available",
            )
        if active_mode == "legacy":
            return self._route_legacy(analysis)
        if active_mode not in {"adaptive", "auto"}:
            from nous_runtime.intelligence.scoring.errors import (
                InvalidRoutingConfigurationError,
            )

            raise InvalidRoutingConfigurationError(
                f"unsupported routing mode: {active_mode}"
            )
        from nous_runtime.intelligence.adaptive import AdaptiveRoutingEngine
        from nous_runtime.intelligence.scoring.errors import (
            InvalidRoutingConfigurationError,
            NoEligibleModelError,
        )

        try:
            return AdaptiveRoutingEngine(history=self.history).route(
                analysis,
                self.registry.list(),
                constraints=constraints,
                policy=policy or self.policy,
            )
        except NoEligibleModelError:
            raise
        except InvalidRoutingConfigurationError as exc:
            if active_mode == "adaptive":
                raise
            legacy = self._route_legacy(analysis)
            return replace(
                legacy,
                decision_id=f"route_{uuid.uuid4().hex}",
                selected_model_id=legacy.selected_model,
                explanation=(f"adaptive fallback: {exc}",),
                created_at=datetime.now(timezone.utc).isoformat(),
                routing_mode="auto",
                fallback_reason=str(exc),
            )

    def _route_legacy(self, analysis: TaskAnalysis) -> RoutingDecision:
        privacy = str(analysis.constraints.get("privacy") or "")
        matches = self.matcher.match({
            "capabilities": analysis.required_capabilities,
            "privacy": privacy,
        })
        scored: list[tuple[float, str, str]] = []
        for match in matches:
            profile = match.profile
            weighted = _weighted_profile_score(analysis.task_type, profile)
            score = weighted * match.score
            scored.append((score, profile.model_id, match.reason))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored or scored[0][0] <= 0:
            return RoutingDecision(
                analysis.task_id,
                tuple(item[1] for item in scored),
                "",
                "No model satisfies the required capabilities.",
                0.0,
            )
        score, model_id, match_reason = scored[0]
        return RoutingDecision(
            task_id=analysis.task_id,
            candidate_models=tuple(item[1] for item in scored),
            selected_model=model_id,
            reason=f"{analysis.task_type} weighted capability match; {match_reason}",
            score=round(score, 6),
        )


def route_capabilities(
    analysis: TaskAnalysis,
    *,
    registry: ModelRegistry | None = None,
    constraints: Any = None,
    policy: Any = None,
    mode: str | None = None,
    history: Any = None,
) -> RoutingDecision:
    return CapabilityRouter(
        registry,
        mode=mode or getattr(policy, "mode", "auto"),
        policy=policy,
        history=history,
    ).route(
        analysis,
        constraints=constraints,
        policy=policy,
    )


def _weighted_profile_score(task_type: str, profile: Any) -> float:
    if task_type == "coding":
        return (
            0.4 * profile.coding_score
            + 0.3 * profile.reasoning_score
            + 0.2 * profile.speed_score
            + 0.1 * profile.cost_score
        )
    if task_type == "math":
        return 0.45 * profile.math_score + 0.35 * profile.reasoning_score + 0.1 * profile.speed_score + 0.1 * profile.cost_score
    if task_type == "computer_vision":
        return 0.55 * profile.vision_score + 0.25 * profile.reasoning_score + 0.1 * profile.speed_score + 0.1 * profile.cost_score
    return 0.55 * profile.reasoning_score + 0.2 * profile.speed_score + 0.15 * profile.cost_score + 0.1 * profile.coding_score


def classify_task(prompt: str) -> str:
    """Classify a prompt as coding, local, or general reasoning."""
    return _classify(prompt)[0]


def _classify(prompt: str) -> tuple[str, str]:
    text = str(prompt or "").lower()
    for keyword in _LOCAL_PHRASES + _LOCAL_WORDS:
        if _keyword_in(keyword, text):
            return TASK_LOCAL, keyword
    for keyword in _SOFTWARE_PHRASES + _SOFTWARE_WORDS:
        if _keyword_in(keyword, text):
            return TASK_SOFTWARE, keyword
    for keyword in _AGENT_PHRASES + _AGENT_WORDS:
        if _keyword_in(keyword, text):
            return TASK_AGENT, keyword
    for keyword in _CODING_PHRASES + _CODING_WORDS:
        if _keyword_in(keyword, text):
            return TASK_CODING, keyword
    return TASK_GENERAL, ""


def _keyword_in(keyword: str, text: str) -> bool:
    if keyword.isascii() and keyword.isalpha():
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def default_candidates(workspace: Any = None) -> tuple[dict[str, Any], ...]:
    """Build provider candidates from configured providers and the registry."""
    from nous_runtime.cli.provider_experience import configured_provider_rows

    candidates = []
    for row in configured_provider_rows(workspace):
        provider_id = str(row.get("provider_id") or "")
        kind = str(row.get("kind") or "")
        candidates.append(
            {
                "provider_id": provider_id,
                "name": str(row.get("name") or provider_id),
                "kind": kind,
                "capabilities": tuple(
                    row.get("executable_capabilities") or row.get("capabilities") or ()
                ),
                "health": str(row.get("health") or "unknown"),
                "latency_ms": row.get("latency_ms"),
                "model": str(row.get("model") or ""),
                "local": _is_local(kind, provider_id),
            }
        )
    return tuple(candidates)


def route_model(
    prompt: str,
    *,
    candidates: Iterable[dict[str, Any]] | None = None,
    workspace: Any = None,
    engine: RuntimePolicyEngine | None = None,
) -> ModelRoute:
    """Route a prompt to a provider via the existing Decision Engine."""
    task, matched = _classify(prompt)
    items = tuple(candidates) if candidates is not None else default_candidates(workspace)
    items = tuple(_normalized_candidate(item, task) for item in items)
    if not items:
        return ModelRoute(
            task=task,
            selected="",
            reason="No providers configured. Run 'nous provider add' to configure one.",
        )

    metadata: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    notes = [f"task classified as {task}" + (f" (matched '{matched}')" if matched else "")]
    local_ids = tuple(
        str(item.get("provider_id") or "")
        for item in items
        if item.get("local") or _is_local(str(item.get("kind") or ""), str(item.get("provider_id") or ""))
    )
    # v0.2.0: Capability-aware routing — select the right capability per task type
    if task == TASK_SOFTWARE:
        metadata["required_capability"] = "software.python.run"
        metadata["decision_type"] = "capability"
        notes.append("software capability match (software.*)")
    elif task == TASK_AGENT:
        metadata["required_capability"] = "agent.code.execute"
        metadata["decision_type"] = "capability"
        notes.append("agent capability match (agent.code.*)")
    elif task == TASK_CODING:
        # Prefer agent if available, fall back to model
        metadata["required_capability"] = "model.code"
        notes.append("coding capability match (model.code)")
    elif task == TASK_LOCAL and local_ids:
        metadata["required_capability"] = "model.reason"
        overrides["allowed_providers"] = local_ids
        notes.append("local provider preference")
    elif task == TASK_LOCAL:
        metadata["required_capability"] = "model.reason"
        notes.append("no local provider configured; using general routing")
    else:
        metadata["required_capability"] = "model.reason"
        notes.append("general reasoning capability match (model.reason)")

    # v0.2.0: software/agent tasks flow through the capability decision
    # handler; everything else keeps the provider routing path.
    decision_type = (
        DecisionType.CAPABILITY
        if metadata.get("decision_type") == "capability"
        else DecisionType.PROVIDER
    )
    request = DecisionRequest(
        task_id=f"model-route-{_prompt_digest(prompt)}",
        decision_type=decision_type,
        context=DecisionContext(
            task_kind=task,
            prompt=str(prompt or ""),
            provider_candidates=items,
            explicit_overrides=overrides,
            metadata=metadata,
        ),
    )
    decision = (engine or default_engine()).decide(request)
    if not decision.outcome.selected:
        engine_note = decision.reasons[0].message if decision.reasons else ""
        return ModelRoute(
            task=task,
            selected="",
            reason="; ".join(notes)
            + f"; {engine_note} Run 'nous provider add' to configure one.",
            decision=decision,
        )
    if decision.reasons:
        notes.append(decision.reasons[0].message)
    return ModelRoute(
        task=task,
        selected=decision.outcome.selected,
        reason="; ".join(notes),
        alternatives=tuple(decision.outcome.alternatives),
        decision=decision,
    )


def _normalized_candidate(item: dict[str, Any], task: str) -> dict[str, Any]:
    """Fill scheduler features the provider registry does not report.

    The scheduler scores ``reliability`` from ``success_rate`` and gives
    ``local`` candidates a privacy edge. Configured providers carry neither,
    so derive reliability from health and keep privacy neutral unless the
    user explicitly asked for a local model.
    """
    data = dict(item)
    if data.get("success_rate") is None and data.get("reliability") is None:
        health = str(data.get("health") or "").lower()
        if health in ("ok", "healthy"):
            data["reliability"] = 0.9
        elif health == "degraded":
            data["reliability"] = 0.4
        elif health == "down":
            data["reliability"] = 0.0
    if task != TASK_LOCAL and data.get("privacy_fit") is None:
        data["privacy_fit"] = 1.0
    return data


def _is_local(kind: str, provider_id: str) -> bool:
    lowered = provider_id.lower()
    return kind in _LOCAL_KINDS or "ollama" in lowered or "local" in lowered


def _prompt_digest(prompt: str) -> str:
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:8]

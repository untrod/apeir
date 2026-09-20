"""Model-neutral collaboration for complex chat deliverables.

The coordinator deliberately keeps role planning separate from workspace
effects.  Workers produce bounded implementation briefs in parallel; the
governed workspace agent remains the only component allowed to mutate files.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from nous_runtime.model_runtime.facade import (
    GatewayExecutionContext,
    GatewayOperation,
    GatewayRequest,
    GatewayResponse,
    GatewayTraceContext,
    ModelGatewayFacade,
)
from nous_runtime.model_runtime.models import ModelRole, RoutingMode


EventEmitter = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class CollaborationLane:
    lane_id: str
    role: str
    capability: str
    objective: str


@dataclass
class CollaborationPreparation:
    enabled: bool = False
    manager_brief: str = ""
    lanes: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    @property
    def context(self) -> str:
        sections = []
        if self.manager_brief:
            sections.append("MANAGER BRIEF\n" + self.manager_brief)
        for lane in self.lanes:
            sections.append(
                f"{lane['role'].upper()} WORKER ({lane['lane_id']})\n"
                + str(lane.get("content") or "")
            )
        return "\n\n".join(sections)

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "manager_completed": bool(self.manager_brief),
            "lanes": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "content"
                }
                for item in self.lanes
            ],
            "failures": list(self.failures),
        }


def should_collaborate(text: str, intent: str = "") -> bool:
    """Select collaboration only when the request contains independent work."""
    value = text.casefold()
    intent_value = intent.casefold()
    groups = (
        ("program", "application", "code", "程序", "代码", "软件", "系统", "应用"),
        ("report", "报告", "总结"),
        ("paper", "论文", "研究", "白皮书"),
        ("test", "测试", "verify", "验证"),
        ("document", "documentation", "文档", "说明书", "设计文档"),
    )
    matched = sum(any(marker in value for marker in group) for group in groups)
    explicit = any(
        marker in value
        for marker in (
            "parallel",
            "multi-agent",
            "multi model",
            "多模型",
            "多角色",
            "并行",
            "共线",
            "完整项目",
            "整个项目",
            "专业系统",
        )
    )
    return explicit or matched >= 2 or (
        intent_value in {"workflow_request", "code_task", "create"} and matched >= 1
    )


def build_lanes(text: str) -> tuple[CollaborationLane, ...]:
    value = text.casefold()
    lanes: list[CollaborationLane] = []
    if any(marker in value for marker in ("program", "application", "code", "程序", "代码", "软件", "系统", "应用")):
        lanes.append(
            CollaborationLane(
                "implementation",
                "software engineer",
                "coding",
                "Design the smallest complete implementation, tests, file layout, and exact verification commands.",
            )
        )
    if any(marker in value for marker in ("report", "报告", "总结")):
        lanes.append(
            CollaborationLane(
                "report",
                "technical writer",
                "documentation",
                "Prepare a concise professional engineering report with scope, design, validation, limitations, and reproducible usage.",
            )
        )
    if any(marker in value for marker in ("paper", "论文", "研究", "白皮书")):
        lanes.append(
            CollaborationLane(
                "paper",
                "research writer",
                "research",
                "Prepare a short paper structure with abstract, method, experiment, evidence, limitations, and conclusion; do not invent citations.",
            )
        )
    if any(marker in value for marker in ("test", "测试", "verify", "验证")):
        lanes.append(
            CollaborationLane(
                "quality",
                "quality engineer",
                "verification",
                "Define executable acceptance tests, edge cases, and objective pass/fail evidence.",
            )
        )
    if len(lanes) < 2:
        lanes.extend(
            (
                CollaborationLane(
                    "implementation",
                    "software engineer",
                    "coding",
                    "Produce an implementation and verification brief.",
                ),
                CollaborationLane(
                    "documentation",
                    "technical writer",
                    "documentation",
                    "Produce the user and engineering documentation brief.",
                ),
            )
        )
    deduplicated: dict[str, CollaborationLane] = {}
    for lane in lanes:
        deduplicated.setdefault(lane.lane_id, lane)
    return tuple(deduplicated.values())[:4]


class ChatCollaborationCoordinator:
    """Run manager and independent worker calls through ModelGateway."""

    def __init__(self, facade: ModelGatewayFacade) -> None:
        self.facade = facade

    def prepare(
        self,
        objective: str,
        *,
        task_id: str,
        workspace_id: str,
        session_id: str,
        trace_id: str,
        preferred_model: str = "",
        max_parallel_lanes: int = 4,
        emit: EventEmitter | None = None,
    ) -> CollaborationPreparation:
        lane_limit = max(1, min(int(max_parallel_lanes), 16))
        lanes = build_lanes(objective)[:lane_limit]
        result = CollaborationPreparation(enabled=True)
        notify = emit or (lambda _event, _payload: None)
        notify(
            "collaboration.started",
            {"strategy": "parallel", "lane_count": len(lanes)},
        )

        manager = self._invoke(
            operation=GatewayOperation.PLANNER,
            role=ModelRole.PLANNER,
            task_id=task_id,
            agent_id="nous.manager",
            workspace_id=workspace_id,
            session_id=session_id,
            trace_id=trace_id,
            preferred_model=preferred_model,
            messages=(
                {
                    "role": "system",
                    "content": (
                        "You are the Nous execution manager. Produce a concise "
                        "delivery contract: files, dependencies, acceptance "
                        "criteria, and conflict boundaries. Do not reveal hidden "
                        "reasoning and do not claim that files already exist."
                    ),
                },
                {"role": "user", "content": objective},
            ),
        )
        if manager.ok:
            result.manager_brief = str(manager.content or "")[:12_000]
            notify("manager.completed", self._telemetry(manager, "manager"))
        else:
            result.failures.append(
                {"lane_id": "manager", "error": self._error(manager)}
            )
            notify("manager.failed", {"error": self._error(manager)})

        def run_lane(lane: CollaborationLane) -> tuple[CollaborationLane, GatewayResponse]:
            notify(
                "model.lane.started",
                {
                    "lane_id": lane.lane_id,
                    "role": lane.role,
                    "capability": lane.capability,
                },
            )
            response = self._invoke(
                operation=GatewayOperation.CHAT,
                role=(
                    ModelRole.CODE_WORKER
                    if lane.capability == "coding"
                    else ModelRole.WORKER
                ),
                task_id=f"{task_id}.{lane.lane_id}",
                agent_id=f"nous.worker.{lane.lane_id}",
                workspace_id=workspace_id,
                session_id=session_id,
                trace_id=trace_id,
                preferred_model=preferred_model,
                messages=(
                    {
                        "role": "system",
                        "content": (
                            f"You are the Nous {lane.role} worker. {lane.objective} "
                            "Return an implementation-ready brief for the manager. "
                            "Do not reveal hidden reasoning, call tools, or claim "
                            "that filesystem effects already happened."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            objective
                            + ("\n\nManager contract:\n" + result.manager_brief if result.manager_brief else "")
                        ),
                    },
                ),
            )
            return lane, response

        with ThreadPoolExecutor(max_workers=min(lane_limit, len(lanes))) as pool:
            futures = {pool.submit(run_lane, lane): lane for lane in lanes}
            completed: dict[str, dict[str, Any]] = {}
            for future in as_completed(futures):
                lane, response = future.result()
                if response.ok:
                    item = {
                        "lane_id": lane.lane_id,
                        "role": lane.role,
                        "capability": lane.capability,
                        "provider_id": response.provider_id,
                        "model_id": response.model_id,
                        "usage": dict(response.usage),
                        "cost_usd": response.cost_usd,
                        "latency_ms": response.latency_ms,
                        "retry_count": response.retry_count,
                        "fallback_history": list(response.fallback_history),
                        "content": str(response.content or "")[:16_000],
                    }
                    completed[lane.lane_id] = item
                    notify(
                        "model.lane.completed",
                        self._telemetry(response, lane.lane_id),
                    )
                else:
                    error = self._error(response)
                    result.failures.append(
                        {"lane_id": lane.lane_id, "error": error}
                    )
                    notify(
                        "model.lane.failed",
                        {"lane_id": lane.lane_id, "error": error},
                    )
        result.lanes = [
            completed[lane.lane_id]
            for lane in lanes
            if lane.lane_id in completed
        ]
        notify(
            "collaboration.prepared",
            {
                "completed_lanes": len(result.lanes),
                "failed_lanes": len(result.failures),
            },
        )
        return result

    def review(
        self,
        objective: str,
        candidate: Mapping[str, Any],
        *,
        task_id: str,
        workspace_id: str,
        session_id: str,
        trace_id: str,
        preferred_model: str = "",
        emit: EventEmitter | None = None,
    ) -> dict[str, Any]:
        notify = emit or (lambda _event, _payload: None)
        notify("review.started", {"strategy": "independent_role"})
        response = self._invoke(
            operation=GatewayOperation.REVIEWER,
            role=ModelRole.REVIEWER,
            task_id=f"{task_id}.review",
            agent_id="nous.reviewer",
            workspace_id=workspace_id,
            session_id=session_id,
            trace_id=trace_id,
            preferred_model=preferred_model,
            messages=(
                {
                    "role": "system",
                    "content": (
                        "You are the Nous reviewer. Check the candidate against "
                        "the request and the verified tool receipts. Return a short "
                        "professional verdict beginning with APPROVED or REJECTED, "
                        "followed by concrete gaps. An earlier failed verification "
                        "is valid repair evidence when a later verification receipt "
                        "succeeds; judge the final ordered state. Do not reveal hidden reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "REQUEST:\n"
                        + objective[:8_000]
                        + "\n\nCANDIDATE:\n"
                        + str(dict(candidate))[:24_000]
                    ),
                },
            ),
        )
        verdict = str(response.content or "")[:4_000] if response.ok else ""
        tool_steps = list(candidate.get("tool_steps") or ())
        named_steps = [
            item for item in tool_steps
            if isinstance(item, Mapping) and str(item.get("tool") or "")
        ]
        if named_steps:
            writes = [
                item for item in named_steps
                if item.get("tool") in {"write_file", "write_files"}
            ]
            verifications = [
                item for item in named_steps if item.get("tool") == "run_command"
            ]
            receipts_verified = (
                bool(writes)
                and all(bool(item.get("ok")) for item in writes)
                and (
                    not verifications
                    or bool(verifications[-1].get("ok"))
                )
            )
        else:
            receipts_verified = bool(tool_steps) and all(
                isinstance(item, Mapping) and bool(item.get("ok"))
                for item in tool_steps
            )
        approved = (
            response.ok
            and verdict.lstrip().upper().startswith("APPROVED")
            and receipts_verified
        )
        payload = {
            **self._telemetry(response, "reviewer"),
            "approved": approved,
            "receipts_verified": receipts_verified,
            "verdict": verdict,
            "error": "" if response.ok else self._error(response),
        }
        notify("review.completed" if response.ok else "review.failed", {
            key: value for key, value in payload.items() if key != "verdict"
        })
        return payload

    def _invoke(
        self,
        *,
        operation: GatewayOperation,
        role: ModelRole,
        task_id: str,
        agent_id: str,
        workspace_id: str,
        session_id: str,
        trace_id: str,
        preferred_model: str,
        messages: tuple[Mapping[str, Any], ...],
    ) -> GatewayResponse:
        return self.facade.try_invoke_sync(
            GatewayRequest(
                operation=operation,
                execution=GatewayExecutionContext(
                    task_id=task_id,
                    agent_id=agent_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    priority=60 if role is ModelRole.PLANNER else 50,
                ),
                messages=messages,
                role=role,
                preferred_models=(preferred_model,) if preferred_model else (),
                routing_mode=(
                    RoutingMode.PREFERRED if preferred_model else RoutingMode.AUTO
                ),
                timeout_s=120.0,
                trace=GatewayTraceContext(
                    trace_id=trace_id,
                    correlation_id=task_id,
                ),
                metadata={"collaboration_role": agent_id},
            )
        )

    @staticmethod
    def _telemetry(response: GatewayResponse, lane_id: str) -> dict[str, Any]:
        return {
            "lane_id": lane_id,
            "provider_id": response.provider_id,
            "model_id": response.model_id,
            "usage": dict(response.usage),
            "cost_usd": response.cost_usd,
            "latency_ms": response.latency_ms,
            "retry_count": response.retry_count,
            "fallback_history": list(response.fallback_history),
        }

    @staticmethod
    def _error(response: GatewayResponse) -> str:
        return str(response.error.get("message") or "model invocation failed")


__all__ = [
    "ChatCollaborationCoordinator",
    "CollaborationLane",
    "CollaborationPreparation",
    "build_lanes",
    "should_collaborate",
]

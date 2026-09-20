"""Unified end-to-end Runtime Pipeline."""

from __future__ import annotations

from typing import Any, Callable

from nous_runtime.events.models import RunEvent, RunState
from nous_runtime.events.stream import EventStream
from nous_runtime.interaction.intent_resolver import IntentResolver
from nous_runtime.interaction.models import IntentRequest
from nous_runtime.runtime.lifecycle import RECEIVED
from nous_runtime.runtime.redaction import redact_runtime_evidence
from nous_runtime.runtime.request import RuntimeRequest
from nous_runtime.runtime.response import RuntimeResponse
from nous_runtime.runtime.session import RuntimeSessionStore
from nous_runtime.runtime.trace import RuntimeTrace
from nous_runtime.workspace.resolver import resolve_workspace


ProductHandler = Callable[[RuntimeRequest, dict[str, Any]], dict[str, Any]]

PRODUCT_CAPABILITIES = frozenset(
    {"agent", "chat", "code_assistant", "connector", "knowledge", "multi_agent", "plugin", "workflow"}
)


class RuntimePipeline:
    """Runs the stable Phase 8 loop across existing Runtime subsystems."""

    def __init__(self, *, workspace_root: str = "", product_handlers: dict[str, ProductHandler] | None = None, gate: Any = None):
        self.workspace_root = workspace_root
        self.product_handlers = dict(product_handlers or {})
        unknown = set(self.product_handlers) - PRODUCT_CAPABILITIES
        if unknown:
            raise ValueError("unknown product capabilities: " + ", ".join(sorted(unknown)))
        self.events = EventStream(workspace_root or ".")
        self.gate = gate
        self._trace_roots: dict[str, str] = {}

    def run(self, request: RuntimeRequest) -> RuntimeResponse:
        # A single identifier links the public Run, trace, events, and UI replay.
        trace = RuntimeTrace(request.request_id, trace_id=request.request_id)
        try:
            from nous_runtime.execution.trace import get_tracer

            execution_trace = get_tracer(self.workspace_root or ".").create_trace(
                session_id=request.session,
                task_id=request.request_id,
                trace_id=trace.trace_id,
            )
            self._trace_roots[request.request_id] = execution_trace.root_span_id
        except Exception:
            pass
        try:
            self.events.create_run(
                request.request_id,
                task_id=request.request_id,
                workspace_id=request.workspace,
                metadata={"session_id": request.session},
            )
            self.events.emit_state_change(
                request.request_id,
                RunState.CREATED,
                task_id=request.request_id,
            )
        except Exception:
            # Telemetry must never replace the Runtime result.
            pass
        trace.add(
            "input",
            RECEIVED,
            data=redact_runtime_evidence(request.to_dict()),
        )
        self._emit(request.request_id, "runtime.request.received", {"request_id": request.request_id})

        intent_resolution = IntentResolver().resolve(
            IntentRequest(
                request.user_input,
                user_id=request.user_id,
                workspace_hint=request.workspace,
                metadata={"task_id": request.request_id},
            )
        )
        decision = intent_resolution.decision
        trace.add(
            "intent",
            decision.intent,
            reason=decision.reason,
            data=intent_resolution.to_dict(),
        )
        self._emit(
            request.request_id,
            "intent.resolved",
            {"intent": decision.intent, "confidence": decision.confidence},
        )
        # Chat requests may be clarified by the selected model and every
        # workspace effect remains governed separately.  Do not dead-end the
        # conversation merely because the generic intent classifier is unsure.
        product_capability = str(
            request.constraints.get("product_capability") or ""
        )
        if (
            decision.requires_confirmation
            and decision.confidence < 0.7
            and product_capability != "chat"
        ):
            trace.add("governance", "ASK_CONFIRMATION", reason="Intent confidence is below execution threshold.")
            return self._response(request, trace, "confirmation_required", "Confirmation required.", decision)

        workspace = resolve_workspace(decision.workspace or request.workspace, root=self.workspace_root)
        trace.add("workspace", workspace.workspace_id or "ambiguous", data=workspace.__dict__)
        if workspace.ambiguous:
            return self._response(request, trace, "workspace_ambiguous", "Workspace selection is ambiguous.", decision)

        context_snapshot = self._build_context(request, decision.intent, workspace.path)
        trace.add("context", "loaded", data=context_snapshot)
        self._emit(request.request_id, "context.loaded", context_snapshot)

        self._active_intent_analysis = intent_resolution.analysis
        plan = self._plan(
            request,
            decision.intent,
            workspace.workspace_id,
        )
        trace.add("planning", plan["status"], reason=plan["reason"], data=plan)
        self._emit(
            request.request_id,
            "plan.created",
            {
                "workflow_id": plan.get("workflow_id", ""),
                "execution_mode": plan.get("execution_mode", ""),
                "summary": plan.get("summary", ""),
            },
        )

        runtime_decision = self._decide(request, workspace.workspace_id, decision.intent)
        trace.add("decision", runtime_decision["selected"], reason=runtime_decision["reason"], data=runtime_decision)

        governance = self._governance(request, decision.intent, workspace.path)
        trace.add("governance", governance["status"], reason=governance["reason"], data=governance)
        self._emit(
            request.request_id,
            "governance.evaluated",
            {"status": governance["status"], "decision_id": governance.get("decision_id", "")},
        )
        if governance["status"] in {"DENY", "ASK_APPROVAL", "ESCALATE"}:
            return self._response(request, trace, governance["status"].lower(), governance["reason"], decision)

        self._emit(
            request.request_id,
            "run.started",
            {"state": "RUNNING", "execution_mode": plan.get("execution_mode", "")},
        )
        execution = self._execute_capability(
            request,
            decision.intent,
            plan,
            context_snapshot,
        )
        trace.add("agent", execution["agent"], reason="Selected built-in runtime agent.", data={"capability": execution["capability"]})
        trace.add("capability", execution["status"], reason=execution["reason"], data=execution)
        self._emit(
            request.request_id,
            "step.completed" if execution["ok"] else "step.failed",
            {
                "capability": execution["capability"],
                "agent": execution["agent"],
                "status": execution["status"],
            },
        )

        verification = self._verify(execution)
        trace.add(
            "verification",
            verification["phase"],
            reason=verification.get("error", ""),
            data=verification,
        )
        self._emit(
            request.request_id,
            "verification.completed",
            {
                "accepted": verification.get("accepted", False),
                "score": verification.get("score", 0.0),
            },
        )

        evaluation = self._evaluate(request, workspace.path, trace.trace_id, execution)
        trace.add("evaluation", evaluation["status"], data=evaluation)

        experience = self._collect_experience(workspace.path, execution, evaluation)
        trace.add("experience", experience["status"], data=experience)

        session_id = request.session or request.request_id
        RuntimeSessionStore(self.workspace_root).append_event(
            session_id,
            {
                "request": redact_runtime_evidence(request.to_dict()),
                "response_status": execution["status"],
                "trace_id": trace.trace_id,
            },
        )
        trace.add("response", "ready", data={"session_id": session_id})

        product_result = execution.get("result")
        product_content = (
            product_result.get("content")
            if isinstance(product_result, dict)
            else None
        )
        verified = bool(verification.get("accepted", False))
        if execution["ok"] and verified:
            message = str(product_content or "Runtime request completed.")
        elif execution["ok"]:
            message = "Runtime output failed verification."
        else:
            message = execution["reason"]
        status = "ok" if execution["ok"] and verified else "failed"
        response_result = {
            "trace": trace.to_dict(),
            "plan": plan,
            "execution": execution,
            "verification": verification,
        }
        if isinstance(product_result, dict):
            response_result["citations"] = list(
                product_result.get("citations") or ()
            )
            response_result["context_snapshot_id"] = str(
                product_result.get("context_snapshot_id")
                or context_snapshot.get("snapshot_id")
                or ""
            )
        return self._response(
            request,
            trace,
            status,
            message,
            decision,
            result=response_result,
        )

    def _build_context(self, request: RuntimeRequest, intent: str, workspace_path: str) -> dict[str, Any]:
        try:
            from nous_runtime.context.builder import build_context
            from nous_runtime.context.types import BuildRequest

            snapshot = build_context(
                BuildRequest(
                    intent=intent,
                    user_id=request.user_id,
                    context_hint=request.user_input,
                    metadata={"runtime_request_id": request.request_id},
                ),
                workspace=workspace_path,
            )
            items: list[dict[str, Any]] = []
            remaining = 24_000
            for item in tuple(getattr(snapshot, "items", ()) or ())[:32]:
                content = str(getattr(item, "content", "") or "").strip()
                if not content or remaining <= 0:
                    continue
                content = content[:remaining]
                remaining -= len(content)
                items.append(
                    {
                        "item_id": str(getattr(item, "item_id", "") or ""),
                        "source_id": str(getattr(item, "source_id", "") or ""),
                        "source_type": str(
                            getattr(item, "source_type", "") or ""
                        ),
                        "content": content,
                        "confidence": float(
                            getattr(item, "confidence", 0.0) or 0.0
                        ),
                    }
                )
            return {
                "snapshot_id": str(
                    getattr(snapshot, "snapshot_id", "")
                    or getattr(snapshot, "id", "")
                ),
                "item_count": len(getattr(snapshot, "items", ()) or ()),
                "items": items,
                "truncated": len(items)
                < len(getattr(snapshot, "items", ()) or ()),
            }
        except Exception as exc:
            return {"snapshot_id": "", "item_count": 0, "error": str(exc)}

    def _plan(
        self,
        request: RuntimeRequest,
        intent: str,
        workspace_id: str,
        analysis: Any = None,
    ) -> dict[str, Any]:
        analysis = analysis or getattr(
            self, "_active_intent_analysis", None
        )
        from nous_runtime.intelligence.planning.parallel import (
            ParallelTaskPlanner,
        )
        from nous_runtime.intelligence.planning.workflow import (
            PlanWorkflowBridge,
        )

        plan = ParallelTaskPlanner().generate(analysis)
        workflow = PlanWorkflowBridge().compile(plan)
        execution_mode = "parallel_dag"
        if str(request.constraints.get("product_capability") or "") == "chat":
            from nous_runtime.chat.collaboration import should_collaborate

            execution_mode = (
                "collaborative_parallel"
                if should_collaborate(request.user_input, intent)
                else "gateway_agent"
            )
        workload_profile = request.constraints.get("workload_profile")
        if not isinstance(workload_profile, dict):
            workload_profile = {}
        return {
            "status": "planned",
            "intent": intent,
            "workspace_id": workspace_id,
            "reason": "Generated dependency-aware parallel TaskGraph.",
            "summary": request.user_input[:200],
            "plan": plan.to_dict(),
            "workflow_id": workflow.workflow_id,
            "execution_mode": execution_mode,
            "workload_profile": workload_profile,
            "max_parallel_lanes": int(
                workload_profile.get("max_parallel_lanes") or 1
            ),
        }

    def _decide(self, request: RuntimeRequest, workspace_id: str, intent: str) -> dict[str, Any]:
        try:
            from nous_runtime.intelligence.engine import default_engine
            from nous_runtime.intelligence.models import DecisionContext, DecisionRequest, DecisionType

            decision = default_engine().decide(
                DecisionRequest(
                    task_id=request.request_id,
                    decision_type=DecisionType.EXECUTION,
                    context=DecisionContext(
                        workspace_id=workspace_id,
                        task_kind=intent.lower(),
                        prompt=request.user_input,
                    ),
                )
            )
            return {
                "decision_id": decision.decision_id,
                "selected": decision.selected,
                "confidence": decision.confidence,
                "reason": decision.reasons[0].message if decision.reasons else "",
            }
        except Exception as exc:
            return {"decision_id": "", "selected": "default", "confidence": 0.0, "reason": str(exc)}

    def _governance(self, request: RuntimeRequest, intent: str, workspace_path: str) -> dict[str, str]:
        try:
            from nous_runtime.governance import ActionProposal, AuthorizationContext, get_gate

            self._ensure_builtin_capability()
            proposal = ActionProposal(
                action_type="runtime.pipeline",
                capability_id=self._requested_capability(request),
                target_workspace=workspace_path,
                side_effect_class="read_only",
                reversibility="reversible",
                parameter_summary=intent,
            )
            context = AuthorizationContext.from_dict(request.authorization_context) if request.authorization_context else AuthorizationContext(
                subject_type="user",
                subject_id=request.user_id,
                authn_method="runtime_session",
                authn_confidence=0.8,
                session_locality="local",
            )
            decision = (self.gate or get_gate()).evaluate(proposal, context)
            return {
                "status": str(decision.action_mode),
                "reason": str(decision.reason_message or decision.reason_code),
                "decision_id": str(decision.decision_id),
            }
        except Exception as exc:
            from nous_runtime.governance.runtime_mode import should_fail_closed

            if should_fail_closed(surface=request.governance_surface):
                return {"status": "DENY", "reason": f"governance unavailable: {exc}", "decision_id": ""}
            return {"status": "EXECUTE", "reason": f"governance unavailable in compatibility path: {exc}", "decision_id": ""}

    def _execute_capability(
        self,
        request: RuntimeRequest,
        intent: str,
        plan: dict[str, Any] | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        product = str(request.constraints.get("product_capability") or "").strip()
        if product:
            if product not in PRODUCT_CAPABILITIES:
                return {
                    "ok": False,
                    "status": "failed",
                    "agent": "runtime.product",
                    "capability": product,
                    "reason": "product capability is not registered",
                    "observation_id": "",
                    "builtin_fallback": False,
                }
            handler = self.product_handlers.get(product)
            if handler is not None:
                try:
                    result = dict(
                        handler(
                            request,
                            {
                                "request_id": request.request_id,
                                "workspace": request.workspace,
                                "user_id": request.user_id,
                                "session": request.session,
                                "intent": intent,
                                "runtime_plan": dict(plan or {}),
                                "context_snapshot": dict(
                                    context_snapshot or {}
                                ),
                                "event_stream": self.events,
                            },
                        )
                        or {}
                    )
                except Exception as exc:
                    return {
                        "ok": False,
                        "status": "failed",
                        "agent": "runtime.product",
                        "capability": product,
                        "reason": str(exc),
                        "observation_id": "",
                        "builtin_fallback": False,
                    }
                ok = bool(result.get("ok", True))
                return {
                    "ok": ok,
                    "status": str(result.get("status") or ("success" if ok else "failed")),
                    "agent": str(result.get("agent") or "runtime.product"),
                    "capability": product,
                    "reason": str(result.get("reason") or "Product capability executed."),
                    "observation_id": str(result.get("observation_id") or ""),
                    "builtin_fallback": False,
                    "result": result,
                }
        capability_id = "mock.echo"
        try:
            from nous_runtime.capability.resolver import execute_capability_observation

            authorization_context = None
            if request.authorization_context:
                from nous_runtime.governance.contracts import AuthorizationContext

                authorization_context = AuthorizationContext.from_dict(request.authorization_context)
            from nous_runtime.agent.pipeline import RuntimeAgentExecutor

            agent_result = RuntimeAgentExecutor().execute(
                task_id=request.request_id,
                capability_id=capability_id,
                parameters={
                    "message": request.user_input,
                    "intent": intent,
                },
                handler=lambda parameters: execute_capability_observation(
                    capability_id,
                    _authorization_context=authorization_context,
                    _governance_surface=request.governance_surface,
                    **parameters,
                ),
            )
            observation = agent_result.output
            ok = bool(
                agent_result.ok
                and getattr(observation, "status", "") == "success"
            )
            errors = list(
                getattr(observation, "errors", ()) or ()
            )
            if not ok:
                reason = "; ".join(errors) or agent_result.error
                return self._builtin_echo(
                    request,
                    capability_id,
                    reason,
                    agent=agent_result.to_dict(),
                )
            return {
                "ok": True,
                "status": "success",
                "agent": agent_result.agent_id,
                "agent_run_id": agent_result.run_id,
                "agent_state": agent_result.state,
                "agent_budget": dict(agent_result.budget),
                "agent_events": [
                    dict(item) for item in agent_result.events
                ],
                "capability": capability_id,
                "reason": "Capability executed through Agent Runtime.",
                "observation_id": getattr(
                    observation,
                    "observation_id",
                    "",
                ),
                "builtin_fallback": False,
            }
        except Exception as exc:
            from nous_runtime.governance.runtime_mode import should_fail_closed

            if should_fail_closed(surface=request.governance_surface):
                return {
                    "ok": False,
                    "status": "failed",
                    "agent": "runtime.builtin",
                    "capability": capability_id,
                    "reason": str(exc),
                    "observation_id": "",
                    "builtin_fallback": False,
                }
            return self._builtin_echo(request, capability_id, str(exc))

    def _builtin_echo(
        self,
        request: RuntimeRequest,
        capability_id: str,
        reason: str = "",
        *,
        agent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "success",
            "agent": str(
                (agent or {}).get("agent_id") or "runtime.builtin"
            ),
            "agent_execution": dict(agent or {}),
            "capability": capability_id,
            "reason": reason or "Executed built-in read-only echo capability.",
            "observation_id": "",
            "builtin_fallback": True,
            "result": {"echo": request.user_input},
        }

    @staticmethod
    def _verify(execution: dict[str, Any]) -> dict[str, Any]:
        from nous_runtime.verification import (
            RuleVerifier,
            SchemaVerifier,
            VerificationRepairRuntime,
            VerificationRule,
        )

        runtime = VerificationRepairRuntime(
            (
                SchemaVerifier({"ok": bool, "status": str}),
                RuleVerifier(
                    (
                        VerificationRule(
                            "execution_succeeded",
                            lambda candidate, context: bool(
                                candidate.output.get("ok", False)
                            ),
                            "execution did not succeed",
                            repairable=False,
                        ),
                    )
                ),
            ),
            max_repairs=0,
        )
        run = runtime.run(generate=lambda: dict(execution))
        report = run.reports[-1] if run.reports else None
        return {
            "run_id": run.run_id,
            "phase": run.phase.value,
            "accepted": bool(report and report.accepted),
            "score": report.score if report is not None else 0.0,
            "issues": [
                issue.to_dict()
                for issue in (
                    report.issues if report is not None else ()
                )
            ],
            "repair_count": len(run.repairs),
            "error": run.error,
        }

    def _evaluate(self, request: RuntimeRequest, workspace_path: str, trace_id: str, execution: dict[str, Any]) -> dict[str, Any]:
        try:
            from nous_runtime.evaluation.evaluator import EvaluationEngine

            record = EvaluationEngine(workspace_path, validators=[]).evaluate(
                target_type="runtime_request",
                target_id=trace_id,
                input_summary=request.user_input[:200],
                context={"metadata": {"execution_ok": execution["ok"]}},
                evaluated_by="runtime.pipeline",
            )
            return {
                "status": "evaluated",
                "evaluation_id": record.id,
                "score": record.composite_score,
                "passed": record.passed,
            }
        except Exception as exc:
            return {"status": "skipped", "error": str(exc)}

    def _collect_experience(self, workspace_path: str, execution: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        try:
            from nous_runtime.experience.collector import ExperienceCollector

            experiences = ExperienceCollector(workspace_path).collect_from_agent(
                execution["agent"],
                execution["capability"],
                execution["ok"],
                error="" if execution["ok"] else execution["reason"],
            )
            return {"status": "collected", "count": len(experiences), "evaluation_status": evaluation.get("status", "")}
        except Exception as exc:
            return {"status": "skipped", "error": str(exc)}

    def _response(
        self,
        request: RuntimeRequest,
        trace: RuntimeTrace,
        status: str,
        message: str,
        decision: Any,
        *,
        result: dict[str, Any] | None = None,
    ) -> RuntimeResponse:
        payload = dict(result or {"trace": trace.to_dict()})
        payload.setdefault("run_id", request.request_id)
        payload.setdefault("task_id", request.request_id)
        response = RuntimeResponse(
            request_id=request.request_id,
            status=status,
            message=message,
            intent=getattr(decision, "intent", ""),
            workspace=getattr(decision, "workspace", ""),
            trace_id=trace.trace_id,
            requires_confirmation=getattr(decision, "requires_confirmation", False),
            result=payload,
            errors=() if status in {"ok", "confirmation_required"} else (message,),
        )
        self._emit(
            request.request_id,
            "runtime.response.ready",
            {"request_id": request.request_id, "trace_id": trace.trace_id, "status": status},
        )
        terminal_event = "run.completed" if status in {
            "ok",
            "confirmation_required",
        } else "run.failed"
        self._emit(
            request.request_id,
            terminal_event,
            {"state": "COMPLETED" if terminal_event == "run.completed" else "FAILED", "status": status},
        )
        root_span_id = self._trace_roots.pop(request.request_id, "")
        if root_span_id:
            try:
                from nous_runtime.execution.trace import SpanStatus, get_tracer

                get_tracer(self.workspace_root or ".").complete_span(
                    root_span_id,
                    status=(
                        SpanStatus.COMPLETED
                        if status in {"ok", "confirmation_required"}
                        else SpanStatus.FAILED
                    ),
                    result_summary=message[:500],
                    error_message=(
                        "" if status in {"ok", "confirmation_required"} else message[:500]
                    ),
                )
            except Exception:
                pass
        return response

    @staticmethod
    def _requested_capability(request: RuntimeRequest) -> str:
        product = str(request.constraints.get("product_capability") or "").strip()
        return f"product.{product}" if product in PRODUCT_CAPABILITIES else "mock.echo"

    @staticmethod
    def _ensure_builtin_capability() -> None:
        """Register the runtime built-in echo capability (idempotent).

        v0.2.0: the gate's hardcoded allowlist is gone — every capability
        must be registered, including runtime built-ins.  Without this the
        gate treats mock.echo as unknown/high risk and blocks the pipeline.
        """
        try:
            from nous_runtime.compat.capability import get_capability, register_capability

            if not get_capability("mock.echo"):
                register_capability(
                    "mock.echo",
                    category="tool",
                    provider="runtime.builtin",
                    description="Runtime built-in echo capability",
                    risk="low",
                    side_effect_class="read_only",
                    reversibility="reversible",
                    model_uncertainty=0.0,
                    idempotent=True,
                    locality="local",
                )
        except Exception:
            # Governance falls back to unknown-capability handling.
            return

    def _emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        try:
            self.events.emit(
                RunEvent(
                    run_id=run_id,
                    task_id=run_id,
                    event_type=event_type,
                    payload=redact_runtime_evidence(payload),
                )
            )
        except Exception:
            # Runtime response integrity must not be replaced by telemetry failure.
            return

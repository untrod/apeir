"""Unified end-to-end Runtime Pipeline."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import hashlib
from nous_runtime.context.builder import ContextBudgetError
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
    {
        "agent",
        "chat",
        "code_assistant",
        "connector",
        "knowledge",
        "multi_agent",
        "plugin",
        "workflow",
    }
)


class RuntimePipeline:
    """Runs the stable Phase 8 loop across existing Runtime subsystems."""

    def __init__(
        self,
        *,
        workspace_root: str = "",
        product_handlers: dict[str, ProductHandler] | None = None,
        gate: Any = None,
    ):
        self.workspace_root = workspace_root
        self.product_handlers = dict(product_handlers or {})
        unknown = set(self.product_handlers) - PRODUCT_CAPABILITIES
        if unknown:
            raise ValueError(
                "unknown product capabilities: " + ", ".join(sorted(unknown))
            )
        self.events = EventStream(workspace_root or ".")
        self.gate = gate
        self._trace_roots: dict[str, str] = {}

    def run(self, request: RuntimeRequest) -> RuntimeResponse:
        if (
            request.workspace_file_refs
            and self.events.get_run(request.request_id) is not None
        ):
            from nous_runtime.context.selected_input import SelectedInputError

            raise SelectedInputError("original_request_already_exists")
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
        self._emit(
            request.request_id,
            "runtime.request.received",
            {"request_id": request.request_id},
        )

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
        product_capability = str(request.constraints.get("product_capability") or "")
        if (
            decision.requires_confirmation
            and decision.confidence < 0.7
            and product_capability != "chat"
        ):
            trace.add(
                "governance",
                "ASK_CONFIRMATION",
                reason="Intent confidence is below execution threshold.",
            )
            return self._response(
                request,
                trace,
                "confirmation_required",
                "Confirmation required.",
                decision,
            )

        # Intent metadata may have discovered a cwd workspace without this
        # Runtime's host root. Only the request's explicit selector belongs here.
        workspace = resolve_workspace(request.workspace, root=self.workspace_root)
        trace.add(
            "workspace", workspace.workspace_id or "ambiguous", data=workspace.__dict__
        )
        if workspace.ambiguous:
            return self._response(
                request,
                trace,
                "workspace_ambiguous",
                "Workspace selection is ambiguous.",
                decision,
            )

        decision = replace(decision, workspace=workspace.workspace_id)
        # The resolver owns execution scope. Request metadata cannot retarget
        # file tools, even when context collection is unavailable or empty.
        request = replace(
            request,
            workspace=workspace.workspace_id,
            constraints={**request.constraints, "workspace_path": workspace.path},
        )
        if request.workspace_file_refs:
            self.events.emit(
                RunEvent(
                    run_id=request.request_id,
                    task_id=request.request_id,
                    event_type="runtime.input.bound",
                    payload={
                        "request_binding_sha256": self._input_request_binding(request)
                    },
                )
            )
            self._emit(
                request.request_id,
                "context.input.selected",
                {
                    "sources": [
                        {
                            "source_id": ref.source_id,
                            "source_version": ref.sha256,
                            "status": "selected",
                            "was_read": False,
                        }
                        for ref in request.workspace_file_refs
                    ]
                },
            )

        context_snapshot = self._build_context(request, decision.intent, workspace.path)
        context_status = str(context_snapshot.get("status") or "loaded")
        context_evidence = {
            "snapshot_id": context_snapshot.get("snapshot_id", ""),
            "status": context_status,
            "delivery_status": context_snapshot.get("delivery_status", context_status),
            "item_count": context_snapshot.get("item_count", 0),
            "checksum": context_snapshot.get("checksum", ""),
            "truncated": context_snapshot.get("truncated", False),
            "selected_input": context_snapshot.get("selected_input", []),
            "admission_decision_id": context_snapshot.get("admission_decision_id")
            or (context_snapshot.get("metadata", {}).get("context_binding") or {}).get(
                "admission_decision_id", ""
            ),
        }
        # Source content belongs to the live admitted input, not general Run
        # telemetry. The Gateway records a content-free input manifest later.
        trace.add("context", context_status, data=context_evidence)
        self._emit(request.request_id, "context.loaded", context_evidence)
        if context_status == "budget_exceeded":
            return self._response(
                request,
                trace,
                "context_budget_exceeded",
                "Required context exceeds the admitted input bound; revise the task or budget.",
                decision,
                result={"context_snapshot": context_snapshot},
            )
        if request.workspace_file_refs:
            # Explicit selected input must never degrade to a source-free call.
            if context_snapshot.get("delivery_status") != "loaded":
                return self._response(
                    request,
                    trace,
                    "selected_input_rejected",
                    "Selected saved input could not be admitted.",
                    decision,
                    result={
                        "selected_input": context_snapshot.get("selected_input", [])
                    },
                )

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

        runtime_decision = self._decide(
            request, workspace.workspace_id, decision.intent
        )
        trace.add(
            "decision",
            runtime_decision["selected"],
            reason=runtime_decision["reason"],
            data=runtime_decision,
        )

        governance = self._governance(request, decision.intent, workspace.path)
        trace.add(
            "governance",
            governance["status"],
            reason=governance["reason"],
            data=governance,
        )
        self._emit(
            request.request_id,
            "governance.evaluated",
            {
                "status": governance["status"],
                "decision_id": governance.get("decision_id", ""),
            },
        )
        if governance["status"] != "EXECUTE":
            return self._response(
                request,
                trace,
                governance["status"].lower(),
                governance["reason"],
                decision,
            )

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
        trace.add(
            "agent",
            execution["agent"],
            reason="Selected built-in runtime agent.",
            data={"capability": execution["capability"]},
        )
        trace.add(
            "capability",
            execution["status"],
            reason=execution["reason"],
            data=execution,
        )
        if execution.get("status") == "waiting_approval":
            product = dict(execution.get("result") or {})
            return self._response(
                request,
                trace,
                "waiting_approval",
                str(product.get("content") or execution["reason"]),
                decision,
                result={
                    "execution": execution,
                    "proposal_id": product.get("proposal_id", ""),
                    "approval_request_id": product.get("approval_request_id", ""),
                    "verification": {"ok": False, "status": "not_executed"},
                    "trace": trace.to_dict(),
                },
            )
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
            product_result.get("content") if isinstance(product_result, dict) else None
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
            response_result["citations"] = list(product_result.get("citations") or ())
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

    def _build_context(
        self, request: RuntimeRequest, intent: str, workspace_path: str
    ) -> dict[str, Any]:
        empty = {
            "snapshot_id": "",
            "item_count": 0,
            "items": [],
            "truncated": False,
            "selected_input": [
                {
                    "source_id": ref.source_id,
                    "source_version": ref.sha256,
                    "status": "rejected",
                    "was_read": False,
                }
                for ref in request.workspace_file_refs
            ],
        }
        try:
            from nous_runtime.context.builder import build_context
            from nous_runtime.context.selected_input import SelectedWorkspaceInput
            from nous_runtime.context.schema import ContextSource
            from nous_runtime.context.security import ContextAccessRequest, ContextGuard
            from nous_runtime.context.types import BuildRequest
            from nous_runtime.governance.contracts import AuthorizationContext

            context = getattr(request, "authenticated_context", None)
            if not isinstance(context, AuthorizationContext):
                return {**empty, "status": "no_source_access"}
            actor_type = {
                "user": "user",
                "agent": "agent",
                "service": "system",
                "automation": "system",
            }.get(context.subject_type, "")
            guard = ContextGuard(workspace_path, gate=self.gate)
            purpose = (
                f"Provide context for runtime request {request.request_id} ({intent})"
            )
            admission = guard.authorize(
                ContextAccessRequest(
                    actor=context.subject_id,
                    actor_type=actor_type,
                    context_id=f"runtime-context:{request.request_id}",
                    purpose=purpose,
                    requested_sources=tuple(source.value for source in ContextSource),
                    authorization_context=context,
                )
            )
            if not admission.allowed:
                return {
                    **empty,
                    "status": "no_source_access",
                    "admission_decision_id": admission.decision_id,
                }
            binding = {
                "subject_type": context.subject_type,
                "subject_id": context.subject_id,
                "context_id": context.context_id,
                "workspace": str(Path(workspace_path).resolve()),
                "purpose_sha256": hashlib.sha256(purpose.encode("utf-8")).hexdigest(),
                # A changed admission requires fresh source selection. This
                # conservative permission version does not itself grant access.
                "admission_decision_id": admission.decision_id,
                "granted_sources": list(admission.granted_sources),
            }
            build_metadata = {
                "runtime_request_id": request.request_id,
                "context_guard": guard,
                "authorization_context": context,
                "actor_type": actor_type,
                "purpose": purpose,
                "context_binding": binding,
            }
            if "context_max_input_tokens" in request.constraints:
                build_metadata["max_input_tokens"] = request.constraints[
                    "context_max_input_tokens"
                ]
            if "context_token_budgets" in request.constraints:
                build_metadata["token_budgets"] = request.constraints[
                    "context_token_budgets"
                ]

            reader = None
            if request.workspace_file_refs:
                from nous_runtime.governance import get_gate

                reader = SelectedWorkspaceInput(
                    workspace_path,
                    request.workspace_file_refs,
                    authorization_context=context,
                    purpose=purpose,
                    work_id=request.request_id,
                    gate=self.gate or get_gate(),
                )
                object.__setattr__(request, "_selected_input", reader)

            snapshot = build_context(
                BuildRequest(
                    intent=intent,
                    user_id=request.user_id,
                    context_hint=request.user_input,
                    sources=admission.granted_sources,
                    max_items=request.constraints.get("context_max_items", 100),
                    metadata=build_metadata,
                ),
                workspace=workspace_path,
                **({"extra_providers": (reader,)} if reader is not None else {}),
            )
            if reader is not None:
                reader.require_collected()
                reader.prepare_snapshot(snapshot)
                self._emit(
                    request.request_id,
                    "context.input.read",
                    {"sources": reader.provenance()},
                )
            snapshot = replace(
                snapshot,
                metadata={
                    **snapshot.metadata,
                    "context_binding": binding,
                    "source_versions": {
                        item.source_version_key: item.source_version
                        for item in snapshot.items
                    },
                },
            )
            payload = snapshot.to_dict()
            return {
                **payload,
                "snapshot_id": snapshot.id,
                "delivery_status": "loaded",
                "truncated": bool(snapshot.metadata.get("truncation_explanation")),
                **(
                    {"selected_input": reader.provenance()}
                    if reader is not None
                    else {}
                ),
            }
        except ContextBudgetError:
            return {
                **empty,
                "status": "budget_exceeded",
                "error": "Required objective or governance context exceeds the admitted input bound.",
            }
        except Exception:
            return {
                **empty,
                "status": "context_error",
                "error": "Context could not be prepared.",
                "selected_input": request._selected_input.reject()
                if request._selected_input is not None
                else empty["selected_input"],
            }

    @staticmethod
    def _input_request_binding(request: RuntimeRequest) -> str:
        import json

        value = {
            "request": request.to_dict(),
            "workspace_path": request.constraints.get("workspace_path"),
            "context_id": getattr(request.authenticated_context, "context_id", ""),
        }
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()

    def _selected_request_active(self, request: RuntimeRequest, intent: str) -> bool:
        # Reload the existing Run owner's events so another API process's
        # cancel/pause or a prior terminal request cannot be hidden by a cache.
        events = self.events.load_events(request.request_id)
        bindings = [
            event.payload.get("request_binding_sha256")
            for event in events
            if event.event_type == "runtime.input.bound"
        ]
        if bindings != [self._input_request_binding(request)]:
            return False
        fresh = EventStream(self.workspace_root or ".").get_run(request.request_id)
        if (
            fresh is None
            or fresh.task_id != request.request_id
            or fresh.state not in {RunState.RUNNING, RunState.EXECUTING}
        ):
            return False
        return (
            self._governance(
                request, intent, str(request.constraints.get("workspace_path") or "")
            )["status"]
            == "EXECUTE"
        )

    def _plan(
        self,
        request: RuntimeRequest,
        intent: str,
        workspace_id: str,
        analysis: Any = None,
    ) -> dict[str, Any]:
        analysis = analysis or getattr(self, "_active_intent_analysis", None)
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
            "max_parallel_lanes": int(workload_profile.get("max_parallel_lanes") or 1),
        }

    def _decide(
        self, request: RuntimeRequest, workspace_id: str, intent: str
    ) -> dict[str, Any]:
        try:
            from nous_runtime.intelligence.engine import default_engine
            from nous_runtime.intelligence.models import (
                DecisionContext,
                DecisionRequest,
                DecisionType,
            )

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
            return {
                "decision_id": "",
                "selected": "default",
                "confidence": 0.0,
                "reason": str(exc),
            }

    def _governance(
        self, request: RuntimeRequest, intent: str, workspace_path: str
    ) -> dict[str, str]:
        try:
            from nous_runtime.governance import (
                ActionProposal,
                AuthorizationContext,
                get_gate,
            )

            self._ensure_builtin_capability()
            proposal = ActionProposal(
                action_type="runtime.pipeline",
                capability_id=self._requested_capability(request),
                target_workspace=workspace_path,
                side_effect_class="read_only",
                reversibility="reversible",
                parameter_summary=intent,
            )
            context = (
                request.authenticated_context
                if isinstance(request.authenticated_context, AuthorizationContext)
                else (
                    AuthorizationContext.from_dict(request.authorization_context)
                    if request.authorization_context
                    else AuthorizationContext(
                        subject_type="user",
                        subject_id=request.user_id,
                        authn_method="runtime_session",
                        authn_confidence=0.8,
                        session_locality="local",
                    )
                )
            )
            decision = (self.gate or get_gate()).evaluate(proposal, context)
            mode = str(decision.action_mode)
            if mode not in {
                "EXECUTE",
                "RECOMMEND",
                "ASK_APPROVAL",
                "ESCALATE",
                "DENY",
            } or (mode == "EXECUTE" and getattr(decision, "allowed", None) is not True):
                return {
                    "status": "DENY",
                    "reason": "Governance did not return explicit execution admission",
                    "decision_id": str(getattr(decision, "decision_id", "")),
                }
            return {
                "status": mode,
                "reason": str(decision.reason_message or decision.reason_code),
                "decision_id": str(decision.decision_id),
            }
        except Exception as exc:
            return {
                "status": "DENY",
                "reason": f"governance unavailable: {type(exc).__name__}",
                "decision_id": "",
            }

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
                                "context_snapshot": dict(context_snapshot or {}),
                                "event_stream": self.events,
                                "_governance_gate": self.gate,
                                "_selected_input": request._selected_input,
                                "_selected_request_active": lambda: (
                                    self._selected_request_active(request, intent)
                                ),
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
                    "status": str(
                        result.get("status") or ("success" if ok else "failed")
                    ),
                    "agent": str(result.get("agent") or "runtime.product"),
                    "capability": product,
                    "reason": str(
                        result.get("reason") or "Product capability executed."
                    ),
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

                authorization_context = AuthorizationContext.from_dict(
                    request.authorization_context
                )
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
                agent_result.ok and getattr(observation, "status", "") == "success"
            )
            errors = list(getattr(observation, "errors", ()) or ())
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
                "agent_events": [dict(item) for item in agent_result.events],
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
            "agent": str((agent or {}).get("agent_id") or "runtime.builtin"),
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
                for issue in (report.issues if report is not None else ())
            ],
            "repair_count": len(run.repairs),
            "error": run.error,
        }

    def _evaluate(
        self,
        request: RuntimeRequest,
        workspace_path: str,
        trace_id: str,
        execution: dict[str, Any],
    ) -> dict[str, Any]:
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

    def _collect_experience(
        self, workspace_path: str, execution: dict[str, Any], evaluation: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from nous_runtime.experience.collector import ExperienceCollector

            experiences = ExperienceCollector(workspace_path).collect_from_agent(
                execution["agent"],
                execution["capability"],
                execution["ok"],
                error="" if execution["ok"] else execution["reason"],
            )
            return {
                "status": "collected",
                "count": len(experiences),
                "evaluation_status": evaluation.get("status", ""),
            }
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
            errors=()
            if status in {"ok", "confirmation_required", "waiting_approval"}
            else (message,),
        )
        self._emit(
            request.request_id,
            "runtime.response.ready",
            {
                "request_id": request.request_id,
                "trace_id": trace.trace_id,
                "status": status,
            },
        )
        terminal_event = (
            "run.waiting_approval"
            if status == "waiting_approval"
            else (
                "run.completed"
                if status
                in {
                    "ok",
                    "confirmation_required",
                }
                else "run.failed"
            )
        )
        self._emit(
            request.request_id,
            terminal_event,
            {
                "state": "WAITING_FOR_APPROVAL"
                if status == "waiting_approval"
                else "COMPLETED"
                if terminal_event == "run.completed"
                else "FAILED",
                "status": status,
            },
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
                        ""
                        if status in {"ok", "confirmation_required"}
                        else message[:500]
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
            from nous_runtime.compat.capability import (
                get_capability,
                register_capability,
            )

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

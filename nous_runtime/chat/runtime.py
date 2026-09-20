"""Chat entry point over Conversation Store and the unified Runtime Pipeline."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.chat.models import ChatIntent, ChatRequest, ChatResponse
from nous_runtime.chat.agent_tools import mutation_is_explicit
from nous_runtime.chat.router import classify_chat
from nous_runtime.conversation import (
    Citation,
    ConversationMessage,
    ConversationStore,
)
from nous_runtime.runtime.orchestrator import RuntimeOrchestrator
from nous_runtime.runtime.request import RuntimeRequest

_log = logging.getLogger("nous.chat.runtime")


class ChatRuntime:
    def __init__(
        self,
        root: str = ".",
        *,
        orchestrator: RuntimeOrchestrator | None = None,
        model_facade: Any = None,
        project_execution: Any = None,
    ) -> None:
        self.root = root
        self.conversations = ConversationStore(root)
        self.project_execution = project_execution
        if orchestrator is not None:
            self.orchestrator = orchestrator
            return
        facade = model_facade
        if facade is None:
            # The first chat request must not observe the Gateway before the
            # Runtime has loaded Provider configuration.  Bootstrap is
            # idempotent and RuntimeOrchestrator reuses the same instance.
            from nous_runtime.runtime.bootstrap import NousRuntime

            NousRuntime.bootstrap(workspace_root=root)
            from nous_runtime.model_runtime.facade import get_gateway_facade

            facade = get_gateway_facade(required=False)
        handlers = {}
        if facade is not None:
            from nous_runtime.model_runtime.bridges import GatewayChatHandler

            handlers["chat"] = GatewayChatHandler(
                facade,
                checkpoint_root=root,
            )
        self.orchestrator = RuntimeOrchestrator(
            workspace_root=root,
            product_handlers=handlers,
        )
        if self.project_execution is None:
            from nous_runtime.connectivity.project import ProjectExecutionService

            self.project_execution = ProjectExecutionService()

    def send(
        self,
        request: ChatRequest,
        *,
        authorization_context: dict[str, Any] | None = None,
        governance_surface: str = "local_cli",
    ) -> ChatResponse:
        if not request.text.strip():
            raise ValueError("chat text is required")
        conversation_id = request.conversation_id
        if conversation_id:
            conversation = self.conversations.get(
                conversation_id,
                workspace_id=request.workspace_id,
                owner_id=request.owner_id,
            )
            if conversation is None:
                raise PermissionError(
                    "conversation is unavailable in this workspace "
                    "and owner scope"
                )
        else:
            conversation = self.conversations.create(
                request.workspace_id,
                request.owner_id,
                title=request.text[:80],
            )
            conversation_id = conversation.conversation_id
        intent = classify_chat(request.text)
        self.conversations.append(
            ConversationMessage(
                conversation_id,
                "user",
                request.text,
                attachment_ids=request.attachment_ids,
            )
        )
        if intent == ChatIntent.APPROVAL_RESPONSE:
            message = (
                "Approval responses require an authenticated approval "
                "control path."
            )
            self.conversations.append(
                ConversationMessage(
                    conversation_id,
                    "assistant",
                    message,
                    metadata={
                        "intent": intent.value,
                        "requires_trusted_approval": True,
                    },
                )
            )
            return ChatResponse(
                conversation_id,
                intent,
                "approval_control_required",
                message,
                requires_trusted_approval=True,
            )
        context = self.conversations.context_window(conversation_id)
        agent_mode = request.agent_mode if request.agent_mode in {
            "agent",
            "read_only",
            "chat",
        } else "agent"
        promoted = intent in {
            ChatIntent.CODE_TASK,
            ChatIntent.WORKFLOW_REQUEST,
            ChatIntent.DEVICE_ACTION,
        }
        workload_profile = self._workload_profile(
            intent,
            authorization_context or {},
        )
        runtime_request = RuntimeRequest(
            request.text,
            workspace=request.workspace_id,
            session=conversation_id,
            user_id=request.owner_id,
            constraints={
                "product_capability": "chat",
                "chat_intent": intent.value,
                "conversation_summary": context["summary"],
                "conversation_message_ids": [
                    item["message_id"] for item in context["messages"]
                ],
                "conversation_messages": [
                    {
                        "role": str(item.get("role") or ""),
                        "content": str(item.get("content") or ""),
                    }
                    for item in context["messages"]
                ],
                "model_id": request.model_id,
                "workspace_path": self.root,
                "agent_mode": agent_mode,
                "mutation_authorized": (
                    agent_mode == "agent"
                    and mutation_is_explicit(request.text)
                ),
                "workload_profile": workload_profile,
            },
            authorization_context=dict(authorization_context or {}),
            governance_surface=governance_surface,
            request_id=request.request_id,
        )
        project_binding = None
        if promoted and self.project_execution is not None:
            try:
                project_binding = self.project_execution.begin(
                    conversation_id=conversation_id,
                    objective=request.text,
                    owner=request.owner_id,
                    run_id=runtime_request.request_id,
                    required_capability=self._project_capability(intent),
                    target_node=str(
                        (authorization_context or {}).get("target_node") or ""
                    ),
                    risk_level=(
                        "medium" if intent == ChatIntent.DEVICE_ACTION else "low"
                    ),
                    params={"workload_profile": workload_profile},
                )
            except Exception as exc:
                # Project recording must not create a second failure path for
                # the canonical Runtime executor.
                _log.warning("Could not bind chat request to project: %s", exc)
        response = self.orchestrator.run(runtime_request)
        project_link: dict[str, Any] = {}
        if project_binding is not None:
            try:
                project_link = self.project_execution.finish(project_binding, response)
            except Exception as exc:
                _log.warning("Could not persist project outcome: %s", exc)
        message = response.message
        citations = tuple(
            Citation(
                str(item.get("source_id") or ""),
                str(item.get("snippet") or ""),
                str(item.get("uri") or ""),
            )
            for item in response.result.get("citations") or ()
            if item.get("source_id")
        )
        self.conversations.append(
            ConversationMessage(
                conversation_id,
                "assistant",
                message,
                event_id=response.trace_id,
                run_id=str(response.result.get("run_id") or ""),
                task_id=str(response.result.get("task_id") or ""),
                citations=citations,
                metadata={
                    "intent": intent.value,
                    "trace_id": response.trace_id,
                    "runtime_status": response.status,
                    "task_promoted": promoted,
                    "project_id": project_link.get("project_id", ""),
                    "work_item_id": project_link.get("work_item_id", ""),
                    "checkpoint_id": project_link.get("checkpoint_id", ""),
                    "agent_run_id": project_link.get("agent_run_id", ""),
                    "agent_checkpoint_id": project_link.get(
                        "agent_checkpoint_id",
                        "",
                    ),
                },
            )
        )
        response_data = response.to_dict()
        if project_link:
            response_data["project_execution"] = project_link
        return ChatResponse(
            conversation_id,
            intent,
            response.status,
            message,
            response.trace_id,
            promoted,
            False,
            response_data,
        )

    @staticmethod
    def _project_capability(intent: ChatIntent) -> str:
        return {
            ChatIntent.CODE_TASK: "workspace.code",
            ChatIntent.WORKFLOW_REQUEST: "workflow.execute",
            ChatIntent.DEVICE_ACTION: "device.execute",
        }.get(intent, "runtime.execute")

    @classmethod
    def _workload_profile(
        cls,
        intent: ChatIntent,
        authorization_context: dict[str, Any],
    ) -> dict[str, Any]:
        from nous_runtime.security.workloads import WorkloadKind, WorkloadProfile

        target_node = str(authorization_context.get("target_node") or "")
        default_lanes = (
            4
            if intent in {ChatIntent.CODE_TASK, ChatIntent.WORKFLOW_REQUEST}
            else 1
        )
        raw_lanes = authorization_context.get(
            "max_parallel_lanes",
            default_lanes,
        )
        try:
            max_parallel_lanes = max(1, min(int(raw_lanes), 64))
        except (TypeError, ValueError):
            max_parallel_lanes = 1
        profile = WorkloadProfile(
            kind=(
                WorkloadKind.DEVICE
                if intent == ChatIntent.DEVICE_ACTION
                else WorkloadKind.COMPUTE
            ),
            action="execute",
            required_capabilities=(cls._project_capability(intent),),
            target_nodes=(target_node,) if target_node else (),
            max_parallel_lanes=max_parallel_lanes,
        )
        return profile.to_dict()

    def export(
        self,
        conversation_id: str,
        *,
        workspace_id: str,
        owner_id: str,
    ) -> dict[str, Any]:
        if (
            self.conversations.get(
                conversation_id,
                workspace_id=workspace_id,
                owner_id=owner_id,
            )
            is None
        ):
            raise PermissionError("conversation is unavailable")
        return self.conversations.export(conversation_id)

    def delete(
        self,
        conversation_id: str,
        *,
        workspace_id: str,
        owner_id: str,
    ) -> bool:
        if (
            self.conversations.get(
                conversation_id,
                workspace_id=workspace_id,
                owner_id=owner_id,
            )
            is None
        ):
            raise PermissionError("conversation is unavailable")
        return self.conversations.delete(conversation_id)

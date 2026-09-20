# -*- coding: utf-8 -*-
"""
Session/Task State Machine Bridge — Legacy Path Consolidation.

Bridges brain.py's session dicts to nous_runtime.kernel.session.Session
and nous_runtime.kernel.task.Task models with full state machine integration.

Design:
  - LegacySessionWrapper: dual-write wrapper (dict + Session object)
  - TaskBridge: creates Task + TaskFingerprint + ExecutionTicket per run_turn
  - All state transitions are validated through the StateMachine
  - Compat entry points emit DeprecationWarning
"""

from __future__ import annotations

import logging
import time
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("session_task_bridge")

# Metrics
legacy_session_sync_total: int = 0
legacy_task_create_total: int = 0



# LegacySessionWrapper — dual-write dict → Session


class LegacySessionWrapper:
    """Wraps a legacy session dict, providing dual-write to the new Session model.

    Reads from the dict for performance. Writes go to both dict and (best-effort)
    the new Session/Conversation model for gradual migration.
    """

    def __init__(self, legacy_dict: dict[str, Any]) -> None:
        self._dict = legacy_dict
        self._session_obj: Any = None  # Lazy-init Session object
        self._conversation_obj: Any = None  # Lazy-init Conversation object

    # Dict-like access
    def __getitem__(self, key: str) -> Any:
        return self._dict[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._dict[key] = value
        self._sync_to_models(key, value)

    def __contains__(self, key: str) -> bool:
        return key in self._dict

    def get(self, key: str, default: Any = None) -> Any:
        return self._dict.get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        return self._dict.pop(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        return self._dict.setdefault(key, default)

    @property
    def raw_dict(self) -> dict[str, Any]:
        return self._dict

    # Session/Conversation model sync
    def _get_or_create_session(self):
        """Lazy-init the Session object."""
        if self._session_obj is not None:
            return self._session_obj
        try:
            from nous_runtime.kernel.session import Session
            sid = self._dict.get("_transcript_sid", "") or str(uuid.uuid4().hex[:12])
            self._session_obj = Session(
                user_id=str(self._dict.get("_source_client", "legacy")),
                device_id=str(self._dict.get("target_device", "")),
                metadata={
                    "api_version": "1.0",
                    "namespace": "remote_terminal",
                    "labels": {"source": "legacy_bridge"},
                },
            )
            # Override object_id with the transcript sid for consistency
            self._session_obj.metadata.object_id = sid
        except ImportError:
            pass
        except Exception as e:
            _log.debug("Failed to create Session object: %s", e)
        return self._session_obj

    def _get_or_create_conversation(self):
        """Lazy-init the Conversation object."""
        if self._conversation_obj is not None:
            return self._conversation_obj
        try:
            from nous_runtime.kernel.session import Conversation, InteractionMode
            self._conversation_obj = Conversation(
                user_id=str(self._dict.get("_source_client", "legacy")),
                title=self._dict.get("title", ""),
                mode=InteractionMode.DISCUSS,
            )
        except ImportError:
            pass
        except Exception as e:
            _log.debug("Failed to create Conversation object: %s", e)
        return self._conversation_obj

    def _sync_to_models(self, key: str, value: Any) -> None:
        """Best-effort dual-write when key fields change."""
        global legacy_session_sync_total
        legacy_session_sync_total += 1
        try:
            session = self._get_or_create_session()
            conversation = self._get_or_create_conversation()
            if session is None or conversation is None:
                return

            if key == "messages" and isinstance(value, list):
                # Sync last message to conversation
                for msg in value[-3:]:  # Last 3 messages only
                    if isinstance(msg, dict):
                        try:
                            conversation.add_message(
                                role=str(msg.get("role", "user")),
                                content=str(msg.get("content", ""))[:2000],
                                tool_calls=msg.get("tool_calls", []),
                            )
                        except Exception:
                            pass
            elif key == "summary" and isinstance(value, str) and value:
                conversation.summary = value[:5000]
            elif key == "_mode_profile" and isinstance(value, str):
                from nous_runtime.kernel.session import InteractionMode
                mode_map = {
                    "code": InteractionMode.EXECUTE,
                    "write": InteractionMode.EXECUTE,
                    "study": InteractionMode.DISCUSS,
                    "full": InteractionMode.EXECUTE,
                }
                conversation.mode = mode_map.get(value, InteractionMode.DISCUSS)
        except ImportError:
            pass
        except Exception:
            pass  # Best-effort; never block legacy operations



# TaskBridge — create Task/ExecutionTicket per run_turn


@dataclass
class TaskBridgeResult:
    """Result of creating a Task through the bridge."""
    task_id: str = ""
    ticket: Any = None  # ExecutionTicket
    task_obj: Any = None  # Task
    plan_artifact: Any = None  # PlanArtifact
    created: bool = False


def create_run_turn_task(
    session: LegacySessionWrapper | dict[str, Any],
    user_text: str,
    model: str | None,
    max_steps: int = 100,
) -> TaskBridgeResult:
    """Create a Task + ExecutionTicket for a run_turn invocation.

    This is the canonical entry point for integrating the legacy run_turn
    with the new Task state machine. It creates:
      1. A Task in CREATED state
      2. A TaskFingerprint describing requirements
      3. An ExecutionTicket authorizing execution
      4. A PlanArtifact (if planner available)

    Returns TaskBridgeResult with all created objects.
    """
    warnings.warn(
        "create_run_turn_task is a compat bridge. "
        "New code should use nous_runtime.kernel.task.Task directly.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_task_create_total
    legacy_task_create_total += 1

    if isinstance(session, LegacySessionWrapper):
        session_dict = session.raw_dict
    else:
        session_dict = session

    result = TaskBridgeResult()

    try:
        from nous_runtime.kernel.task import (
            Task, TaskPhase, TaskFingerprint, TaskBudget, ExecutionTicket,
        )
        from nous_runtime.kernel.state_machine import StateMachine

        # Create fingerprint
        fingerprint = TaskFingerprint(
            task_type="run_turn",
            required_capabilities=["model.chat", "model.tool_calling"],
            requires_verification=True,
            requires_approval=True,
            risk_level="medium",
            estimated_tokens=4096,
        )

        # Create budget
        budget = TaskBudget(
            max_model_calls=max_steps,
            max_execution_seconds=600,
            max_retries=2,
        )

        # Create task
        task_id = str(uuid.uuid4().hex[:16])
        task = Task(
            fingerprint=fingerprint,
            budget=budget,
            target_node_id=str(session_dict.get("target_device", "")),
            assigned_model_id=str(model or ""),
            total_steps=max_steps,
            metadata={
                "api_version": "1.0",
                "namespace": "remote_terminal",
                "labels": {"source": "run_turn_bridge"},
            },
        )
        # Set the task ID
        task.metadata.object_id = task_id

        # Initialize state machine
        task.phase_sm = StateMachine(
            transitions=TASK_TRANSITIONS,
            current=TaskPhase.CREATED,
        )

        # Create execution ticket
        ticket = ExecutionTicket(
            plan_id="",
            task_id=task_id,
            approved_by="auto",  # Legacy compat: auto-approve
            approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            target_node_id=str(session_dict.get("target_device", "")),
            assigned_model_id=str(model or ""),
            budget={"max_tokens": budget.max_tokens, "max_cost_cents": budget.max_cost_cents},
            expires_at="",
        )

        # Try to create a PlanArtifact
        plan = None
        try:
            from remote_terminal.plan_artifact import PlanArtifact, PlannedTask
            planned_tasks = [
                PlannedTask(
                    task_id=f"{task_id}-step-1",
                    capability_id="model.chat",
                    params={"user_text": user_text[:500], "model": model or "default"},
                    depends_on=[],
                    expected_output_schema={"type": "object"},
                ),
            ]
            plan = PlanArtifact(
                plan_id=f"plan-{task_id}",
                version="1.0.0",
                tasks=planned_tasks,
                dependencies={},
                estimated_cost={"tokens": 4096},
            )
            ticket.plan_id = plan.plan_id
        except ImportError:
            pass
        except Exception as e:
            _log.debug("Failed to create PlanArtifact: %s", e)

        result.task_id = task_id
        result.ticket = ticket
        result.task_obj = task
        result.plan_artifact = plan
        result.created = True

    except ImportError:
        _log.debug("nous_runtime.kernel.task not available")
    except Exception as e:
        _log.warning("Failed to create run_turn Task: %s", e)

    return result


# Task state transitions

# Valid transitions copied from nous_runtime.kernel.task for use when
# nous_runtime is not importable (graceful degradation).
TASK_TRANSITIONS = {
    "created": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"planning", "cancelled"}),
    "planning": frozenset({"awaiting_approval", "failed", "cancelled"}),
    "awaiting_approval": frozenset({"dispatching", "planning", "cancelled"}),
    "dispatching": frozenset({"running", "waiting_for_node", "waiting_for_model", "cancelled"}),
    "running": frozenset({"verifying", "paused", "failed", "cancelled",
                           "waiting_for_model", "waiting_for_node", "recovering"}),
    "waiting_for_model": frozenset({"running", "failed", "cancelled"}),
    "waiting_for_node": frozenset({"running", "failed", "cancelled"}),
    "verifying": frozenset({"completed", "completed_with_warnings",
                             "failed_verification", "recovering"}),
    "paused": frozenset({"running", "cancelled", "failed"}),
    "recovering": frozenset({"running", "failed", "cancelled"}),
    "completed": frozenset(),
    "completed_with_warnings": frozenset(),
    "failed": frozenset({"recovering", "queued", "cancelled"}),
    "failed_verification": frozenset({"recovering", "cancelled"}),
    "cancelled": frozenset(),
}


def emit_task_transition(
    task_obj: Any,
    from_phase: str,
    to_phase: str,
    reason: str = "",
    triggered_by: str = "run_turn",
) -> bool:
    """Record a task state transition. Returns True if valid, False if blocked."""
    warnings.warn(
        "emit_task_transition is a compat bridge. "
        "Use Task.phase_sm.transition() directly.",
        DeprecationWarning, stacklevel=2,
    )
    if task_obj is None or not hasattr(task_obj, "phase_sm"):
        return False

    try:
        valid_targets = TASK_TRANSITIONS.get(from_phase, frozenset())
        if to_phase not in valid_targets:
            _log.warning(
                "Invalid task transition: %s → %s (valid: %s)",
                from_phase, to_phase, ", ".join(sorted(valid_targets)),
            )
            return False

        task_obj.phase_sm.transition(
            to_phase,
            reason=reason,
            triggered_by=triggered_by,
        )
        _log.info("Task %s: %s → %s (%s)", getattr(task_obj.metadata, "object_id", "?"),
                  from_phase, to_phase, reason)
        return True
    except Exception as e:
        _log.warning("Task transition failed: %s", e)
        return False


# Session sync helper

def sync_legacy_session_to_models(session_dict: dict[str, Any]) -> LegacySessionWrapper:
    """Convert a legacy session dict to the wrapped dual-write form."""
    warnings.warn(
        "sync_legacy_session_to_models is a compat bridge.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_session_sync_total
    legacy_session_sync_total += 1
    return LegacySessionWrapper(session_dict)

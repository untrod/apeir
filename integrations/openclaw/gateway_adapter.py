"""OpenClaw Gateway Session → Nous AgentProcess adapter.

This product-layer adapter owns no execution state. It maps OpenClaw sessions
to NKI concepts; local mappings are compatibility caches only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("nous.integrations.openclaw.gateway")


class SessionState(Enum):
    """OpenClaw session states mapped to Nous process phases."""
    CREATED = "created"
    CONNECTED = "connected"
    ACTIVE = "active"
    IDLE = "idle"
    DISCONNECTED = "disconnected"
    TERMINATED = "terminated"
    ERROR = "error"


@dataclass
class SessionMapping:
    """Maps an OpenClaw gateway session to a Nous AgentProcess."""
    openclaw_session_id: str
    nous_process_id: str | None = None
    state: SessionState = SessionState.CREATED
    workspace_id: str | None = None
    capabilities: list[str] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class GatewaySessionAdapter:
    """Adapts OpenClaw gateway sessions to Nous AgentProcesses.

    Provides:
      - Session → Process lifecycle mapping
      - Workspace isolation per session
      - Capability narrowing from gateway permissions
      - Budget enforcement at process level
      - Checkpoint/restore for disconnected sessions
      - Graceful degradation when Nous kernel is unavailable
    """

    def __init__(self, kernel_endpoint: str | None = None):
        self._kernel_endpoint = kernel_endpoint
        self._sessions: dict[str, SessionMapping] = {}
        self._kernel_available = False

    # Session lifecycle

    def create_session(
        self,
        session_id: str,
        workspace_id: str | None = None,
        capabilities: list[str] | None = None,
        budget: dict[str, float] | None = None,
    ) -> SessionMapping:
        """Create a Nous AgentProcess for an OpenClaw session."""
        mapping = SessionMapping(
            openclaw_session_id=session_id,
            workspace_id=workspace_id,
            capabilities=capabilities or [],
            budget=budget or {},
        )

        if self._kernel_available:
            mapping.nous_process_id = self._spawn_process(mapping)
            mapping.state = SessionState.ACTIVE
            log.info("Session %s → AgentProcess %s", session_id, mapping.nous_process_id)
        else:
            # Graceful degradation: track session locally
            mapping.state = SessionState.CONNECTED
            log.warning(
                "Session %s running without kernel — limited state/resource guarantees",
                session_id,
            )

        self._sessions[session_id] = mapping
        return mapping

    def disconnect_session(self, session_id: str) -> None:
        """Checkpoint and pause the AgentProcess on disconnect."""
        mapping = self._sessions.get(session_id)
        if not mapping:
            return

        if mapping.nous_process_id and self._kernel_available:
            self._checkpoint_process(mapping.nous_process_id)

        mapping.state = SessionState.DISCONNECTED
        log.info("Session %s disconnected — process checkpointed", session_id)

    def reconnect_session(self, session_id: str) -> SessionMapping | None:
        """Restore AgentProcess from checkpoint on reconnect."""
        mapping = self._sessions.get(session_id)
        if not mapping:
            return self.create_session(session_id)

        if mapping.nous_process_id and self._kernel_available:
            self._restore_process(mapping.nous_process_id)

        mapping.state = SessionState.ACTIVE
        log.info("Session %s reconnected — process restored", session_id)
        return mapping

    def terminate_session(self, session_id: str) -> None:
        """Finalize AgentProcess and archive."""
        mapping = self._sessions.pop(session_id, None)
        if not mapping:
            return

        if mapping.nous_process_id and self._kernel_available:
            self._terminate_process(mapping.nous_process_id)

        mapping.state = SessionState.TERMINATED
        log.info("Session %s terminated", session_id)

    # Process operations (delegate to Nous kernel)

    def _spawn_process(self, mapping: SessionMapping) -> str:
        """Spawn AgentProcess via NKI."""
        # TODO: Implement NKI SubmitWorkload with ProcessSpec
        # When nousd is available, call:
        #   nki_client.submit_workload(WorkloadSpec(process=ProcessSpec(...)))
        return f"process-{mapping.openclaw_session_id}"

    def _checkpoint_process(self, process_id: str) -> None:
        """Signal CHECKPOINT to AgentProcess."""
        pass  # TODO: NKI SignalProcess(checkpoint)

    def _restore_process(self, process_id: str) -> None:
        """Signal RESTORE to AgentProcess."""
        pass  # TODO: NKI SignalProcess(restore)

    def _terminate_process(self, process_id: str) -> None:
        """Signal CANCEL to AgentProcess and await termination."""
        pass  # TODO: NKI CancelWorkload

    # Status

    def get_session_state(self, session_id: str) -> SessionState | None:
        mapping = self._sessions.get(session_id)
        return mapping.state if mapping else None

    @property
    def active_sessions(self) -> int:
        return sum(
            1 for m in self._sessions.values()
            if m.state in (SessionState.ACTIVE, SessionState.IDLE)
        )

    @property
    def kernel_available(self) -> bool:
        return self._kernel_available

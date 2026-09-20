# -*- coding: utf-8 -*-
"""
Protocol contracts — versioned, immutable message types for connectivity.

Every network message carries:
  message_id, schema_version, protocol_version, message_type,
  source_id, target_id, created_at, expires_at, sequence_number,
  idempotency_key, payload, signature
"""

from .envelope import ProtocolEnvelope
from .identity import NodeIdentity, NodeManifest
from .session import NodeSession
from .pairing import PairingCode, PairingRequest, PairingApproval
from .heartbeat import Heartbeat
from .task import (
    TaskSubmission, TaskAssignment, TaskAcknowledgement,
    TaskEvent, TaskResult, TaskCancellation,
    TaskState,
)
from .error import ProtocolError
from .serialization import (
    deterministic_json,
    deterministic_hash,
    redacted_serialization,
    validate_bounded_payload,
)

__all__ = [
    "ProtocolEnvelope",
    "NodeIdentity",
    "NodeManifest",
    "NodeSession",
    "PairingCode",
    "PairingRequest",
    "PairingApproval",
    "Heartbeat",
    "TaskSubmission",
    "TaskAssignment",
    "TaskAcknowledgement",
    "TaskEvent",
    "TaskResult",
    "TaskCancellation",
    "TaskState",
    "ProtocolError",
    "deterministic_json",
    "deterministic_hash",
    "redacted_serialization",
    "validate_bounded_payload",
]

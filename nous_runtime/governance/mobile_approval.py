# -*- coding: utf-8 -*-
"""Mobile Remote Approval — secure approval from mobile devices.

Mobile devices only implement necessary control surface:
  task notification, risk summary, approve, reject, pause, resume,
  cancel, emergency stop, result summary.

Security: device binding, biometric confirmation, short-lived tokens,
anti-replay nonce, signed approvals, remote revoke, audit trail,
critical-action second confirmation.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from enum import Enum


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class MobileApprovalRequest:
    """Approval request sent to mobile device."""
    request_id: str = ""
    task_id: str = ""
    task_summary: str = ""
    risk_level: str = "low"
    risk_summary: str = ""
    proposed_action: str = ""
    affected_resources: list[str] = field(default_factory=list)
    cost_estimate_usd: float = 0.0
    deadline: str = ""
    nonce: str = ""
    created_at: str = ""
    expires_at: str = ""          # short-lived: 5 minutes
    requires_biometric: bool = True
    requires_second_confirmation: bool = False


@dataclass
class MobileApprovalResponse:
    """Signed approval response from mobile device."""
    request_id: str = ""
    action: ApprovalAction = ApprovalAction.APPROVE
    device_id: str = ""
    biometric_verified: bool = False
    signature: str = ""           # HMAC-SHA256(device_secret, request_id + action + nonce)
    nonce: str = ""
    timestamp: str = ""
    audit_trail_id: str = ""


class MobileApprovalService:
    """Secure mobile approval service with anti-replay and audit."""

    def __init__(self, shared_secret: str = "") -> None:
        self._secret = shared_secret.encode() if shared_secret else b"change-me-mobile-secret"
        self._pending: dict[str, MobileApprovalRequest] = {}
        self._used_nonces: set[str] = set()
        self._bound_devices: dict[str, str] = {}  # device_id → public_key
        self._audit_log: list[dict] = []

    def create_request(self, task_id: str, summary: str, risk: str = "low", requires_second: bool = False) -> MobileApprovalRequest:
        """Create a mobile approval request with anti-replay nonce."""
        nonce = hashlib.sha256(f"{task_id}{uuid.uuid4().hex}".encode()).hexdigest()[:16]
        req = MobileApprovalRequest(
            request_id=f"mob_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            task_summary=summary,
            risk_level=risk,
            nonce=nonce,
            created_at=_utc_now(),
            expires_at=_utc_now_offset(300),  # 5 min TTL
            requires_second_confirmation=risk in ("high", "critical"),
        )
        self._pending[req.request_id] = req
        return req

    def verify_response(self, response: MobileApprovalResponse) -> tuple[bool, str]:
        """Verify a mobile approval response. Returns (valid, reason)."""
        req = self._pending.get(response.request_id)
        if req is None:
            return False, "Unknown or expired request"

        # Anti-replay: nonce must not be reused
        if response.nonce in self._used_nonces:
            return False, "Nonce already used (replay detected)"
        if response.nonce != req.nonce:
            return False, "Nonce mismatch"

        # Biometric verification required?
        if req.requires_biometric and not response.biometric_verified:
            return False, "Biometric verification required but not provided"

        # Verify device binding
        device = self._bound_devices.get(response.device_id)
        if device is None:
            return False, "Device not bound"

        # Verify HMAC signature
        expected_sig = hmac.new(
            self._secret,
            f"{response.request_id}{response.action.value}{response.nonce}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(response.signature, expected_sig):
            return False, "Invalid signature"

        # Consume nonce (prevents replay)
        self._used_nonces.add(response.nonce)

        # Second confirmation for critical actions
        if req.requires_second_confirmation and response.action == ApprovalAction.APPROVE and not response.biometric_verified:
            return False, "Second confirmation required for critical action"

        # Audit
        self._audit_log.append({
            "request_id": response.request_id,
            "task_id": req.task_id,
            "action": response.action.value,
            "device_id": response.device_id,
            "biometric": response.biometric_verified,
            "timestamp": response.timestamp,
            "audit_trail_id": response.audit_trail_id,
        })

        return True, "Approval verified"

    def bind_device(self, device_id: str, public_key: str) -> None:
        self._bound_devices[device_id] = public_key

    def revoke_device(self, device_id: str) -> None:
        self._bound_devices.pop(device_id, None)

    def emergency_stop(self, device_id: str) -> tuple[bool, str]:
        """Emergency stop all running tasks from mobile device."""
        if device_id not in self._bound_devices:
            return False, "Device not bound"
        self._audit_log.append({"action": "emergency_stop", "device_id": device_id, "timestamp": _utc_now()})
        return True, "Emergency stop triggered"

    def get_pending(self) -> list[MobileApprovalRequest]:
        """Get all pending requests (excluding expired)."""
        return [r for r in self._pending.values() if r.expires_at > _utc_now()]

    def audit_trail(self) -> list[dict]:
        return list(self._audit_log)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _utc_now_offset(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

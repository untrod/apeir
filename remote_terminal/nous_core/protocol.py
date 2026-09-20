# -*- coding: utf-8 -*-
"""
Unified Message Envelope — shared message format for all Nous protocols.

Every message in the Nous ecosystem uses this envelope, regardless of
transport (HTTP, WebSocket, MQTT, UART, CAN).

Protocols: NKP (Kernel), NEP (Edge), NFP (Federation), NSP (Skill/Provider)

Usage:
  from nous_core.protocol import Envelope, ErrorCode, Protocol

  msg = Envelope(
      protocol=Protocol.NEP,
      msg_type="HELLO",
      source="esp32_arm_01",
      target="main_brain",
      payload={"capabilities": ["gpio.led.set", "sensor.read"]},
  )
  wire = msg.to_json()
  parsed = Envelope.from_json(wire)
"""

from __future__ import annotations

import hashlib as _hashlib
import hmac as _hmac
import json as _json
from dataclasses import dataclass, field, asdict
from typing import Any

from . import ids as _ids
from . import time as _time


# Protocol identifiers

class Protocol:
    NKP = "NKP"  # Nous Kernel Protocol
    NEP = "NEP"  # Nous Edge Protocol
    NFP = "NFP"  # Nous Federation Protocol
    NSP = "NSP"  # Nous Skill / Provider Protocol

    ALL = {NKP, NEP, NFP, NSP}


# Error codes

class ErrorCode:
    OK = 0
    AUTH_FAILED = 1
    CAP_NOT_FOUND = 2
    RISK_BLOCKED = 3
    TIMEOUT = 4
    DEVICE_OFFLINE = 5
    RATE_LIMITED = 6
    INVALID_MSG = 7
    INTERNAL = 8

    _MESSAGES = {
        0: "Success",
        1: "Authentication failed",
        2: "Capability not found",
        3: "Risk policy blocked",
        4: "Execution timeout",
        5: "Device offline",
        6: "Rate limited",
        7: "Invalid message",
        8: "Internal error",
    }

    @classmethod
    def message(cls, code: int) -> str:
        return cls._MESSAGES.get(code, "Unknown error")


# Message types per protocol

MESSAGE_TYPES: dict[str, set[str]] = {
    Protocol.NKP: {"EVENT", "JOB_CREATE", "JOB_QUERY", "CAP_INVOKE",
                   "DEVICE_QUERY", "AUDIT_QUERY", "HEALTH"},
    Protocol.NEP: {"HELLO", "CAPS", "HEARTBEAT", "JOB", "RESULT",
                   "ALERT", "ACK", "STOP"},
    Protocol.NFP: {"HELLO", "CAPS_EXCHANGE", "TASK_DELEGATE",
                   "RESULT", "AUDIT_SYNC", "HEARTBEAT"},
    Protocol.NSP: {"MODULE_REGISTER", "CAP_DECLARE", "CAP_INVOKE",
                   "RESULT", "ERROR"},
}


# The Envelope

@dataclass
class Envelope:
    protocol: str = ""          # NKP, NEP, NFP, NSP
    version: str = "0.1"
    msg_type: str = ""          # HELLO, CAPS, JOB, RESULT, etc.
    source: str = ""            # sender node/device ID
    target: str = ""            # recipient node/device ID
    payload: dict[str, Any] = field(default_factory=dict)
    msg_id: str = ""            # auto-generated if empty
    timestamp: str = ""         # auto-generated if empty
    correlation_id: str = ""    # links related messages
    signature: str = ""         # HMAC signature

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = _ids.make_id("msg")
        if not self.timestamp:
            self.timestamp = _time.utc_now()

    def to_json(self) -> str:
        """Serialize to JSON wire format."""
        return _json.dumps(asdict(self), ensure_ascii=False)

    def sign(self, secret: str):
        """Sign the envelope with HMAC-SHA256."""
        payload_str = _json.dumps(self.payload, ensure_ascii=False, sort_keys=True)
        msg = f"{self.protocol}:{self.msg_type}:{self.source}:{self.target}:{self.timestamp}:{payload_str}"
        self.signature = _hmac.new(
            secret.encode(), msg.encode(), _hashlib.sha256
        ).hexdigest()

    def verify(self, secret: str) -> bool:
        """Verify HMAC signature."""
        if not self.signature:
            return False
        expected = _hmac.new(
            secret.encode(),
            f"{self.protocol}:{self.msg_type}:{self.source}:{self.target}:{self.timestamp}:{_json.dumps(self.payload, ensure_ascii=False, sort_keys=True)}".encode(),
            _hashlib.sha256,
        ).hexdigest()
        return _hmac.compare_digest(expected, self.signature)

    def is_valid(self) -> bool:
        """Basic validation: protocol, type, source, target."""
        if self.protocol not in Protocol.ALL:
            return False
        allowed_types = MESSAGE_TYPES.get(self.protocol, set())
        if self.msg_type not in allowed_types:
            return False
        if not self.source or not self.target:
            return False
        return True

    @classmethod
    def from_json(cls, data: str | bytes | dict) -> Envelope:
        """Parse from JSON string, bytes, or dict. Accepts both short and long field names."""
        if isinstance(data, (str, bytes)):
            d = _json.loads(data) if isinstance(data, str) else _json.loads(data.decode())
        else:
            d = data
        # Accept both "type"/"id" (spec style) and "msg_type"/"msg_id" (code style)
        return cls(
            protocol=d.get("protocol", ""),
            version=d.get("version", "0.1"),
            msg_type=d.get("msg_type") or d.get("type", ""),
            source=d.get("source", ""),
            target=d.get("target", ""),
            payload=d.get("payload", {}),
            msg_id=d.get("msg_id") or d.get("id", ""),
            timestamp=d.get("timestamp", ""),
            correlation_id=d.get("correlation_id", ""),
            signature=d.get("signature", ""),
        )

    @classmethod
    def response(cls, original: Envelope, msg_type: str,
                 payload: dict, error_code: int = 0) -> Envelope:
        """Create a response envelope for a request."""
        return cls(
            protocol=original.protocol,
            msg_type=msg_type,
            source=original.target,
            target=original.source,
            correlation_id=original.correlation_id,
            payload={"error_code": error_code, "error_msg": ErrorCode.message(error_code),
                     **payload},
        )

    @classmethod
    def error(cls, original: Envelope, code: int) -> Envelope:
        """Create an error response."""
        return cls.response(original, "ERROR", {}, code)

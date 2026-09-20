# -*- coding: utf-8 -*-
"""PairingCode, PairingRequest, PairingApproval -node pairing contracts."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time

import hmac as _hmac

from .serialization import redacted_serialization

# Pairing code configuration
PAIRING_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # Excludes O/0/I/1
PAIRING_CODE_LENGTH = 8
PAIRING_CODE_TTL_SECONDS = 300  # 5 minutes
MAX_PAIRING_ATTEMPTS = 5


def generate_pairing_code() -> str:
    """Generate a random pairing code (8 alphanumeric chars, no O/0/I/1)."""
    return "".join(secrets.choice(PAIRING_CODE_CHARS) for _ in range(PAIRING_CODE_LENGTH))


def hash_pairing_code(code: str) -> str:
    """SHA-256 hash of a pairing code (for storage)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PairingCode:
    """One-time pairing code for node registration."""

    code_hash: str  # SHA-256 of the plaintext code
    created_at: str
    expires_at: str
    created_by: str  # user identifier
    attempts: int = 0

    @classmethod
    def create(cls, created_by: str = "cli") -> tuple[str, PairingCode]:
        """Generate a new pairing code. Returns (plaintext_code, PairingCode)."""
        code = generate_pairing_code()
        now = _time.utc_now()
        # Calculate expiry
        import datetime as _dt
        exp = _dt.datetime.now(tz=_dt.timezone.utc) + _dt.timedelta(
            seconds=PAIRING_CODE_TTL_SECONDS
        )
        expires_at = exp.strftime("%Y-%m-%dT%H:%M:%SZ")
        return code, cls(
            code_hash=hash_pairing_code(code),
            created_at=now,
            expires_at=expires_at,
            created_by=created_by,
        )

    def is_expired(self) -> bool:
        return _time.utc_now_epoch() > _time.parse_iso(self.expires_at)

    def is_exhausted(self) -> bool:
        return self.attempts >= MAX_PAIRING_ATTEMPTS

    def with_attempt(self) -> PairingCode:
        return PairingCode(
            code_hash=self.code_hash,
            created_at=self.created_at,
            expires_at=self.expires_at,
            created_by=self.created_by,
            attempts=self.attempts + 1,
        )

    def verify(self, plaintext: str) -> bool:
        """Verify a plaintext code against this hash. Constant-time comparison."""
        return _hmac.compare_digest(
            self.code_hash, hash_pairing_code(plaintext)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "created_by": self.created_by,
            "attempts": self.attempts,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairingCode:
        return cls(
            code_hash=data.get("code_hash", ""),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at", ""),
            created_by=data.get("created_by", ""),
            attempts=data.get("attempts", 0),
        )


@dataclass(frozen=True)
class PairingRequest:
    """Sent by Node to request pairing."""

    pairing_code: str  # plaintext -redacted in logs
    node_identity: dict[str, Any]  # NodeIdentity as dict

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairing_code": self.pairing_code,
            "node_identity": self.node_identity,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairingRequest:
        return cls(
            pairing_code=data.get("pairing_code", ""),
            node_identity=data.get("node_identity", {}),
        )


@dataclass(frozen=True)
class PairingApproval:
    """Sent by Control Plane when pairing is approved."""

    credential_id: str
    node_id: str
    public_key: str
    issued_at: str
    expires_at: str
    status: str = "active"

    @classmethod
    def create(cls, node_id: str, public_key: str) -> PairingApproval:
        import datetime as _dt
        now = _time.utc_now()
        exp = _dt.datetime.now(tz=_dt.timezone.utc) + _dt.timedelta(days=365)
        return cls(
            credential_id=_ids.make_id("cred"),
            node_id=node_id,
            public_key=public_key,
            issued_at=now,
            expires_at=exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_id": self.credential_id,
            "node_id": self.node_id,
            "public_key": self.public_key,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "status": self.status,
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        return redacted_serialization(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairingApproval:
        return cls(
            credential_id=data.get("credential_id", ""),
            node_id=data.get("node_id", ""),
            public_key=data.get("public_key", ""),
            issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at", ""),
            status=data.get("status", "active"),
        )


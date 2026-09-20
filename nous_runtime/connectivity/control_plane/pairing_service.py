# -*- coding: utf-8 -*-
"""PairingService — one-time pairing code management and node approval."""

from __future__ import annotations

import logging


from ..protocol.pairing import (
    PairingCode, PairingApproval, PairingRequest,
    PAIRING_CODE_TTL_SECONDS,
)
from ..protocol.error import ErrorCode

_log = logging.getLogger("nous.control_plane.pairing")


class PairingService:
    """Manages one-time pairing codes and node approval flow."""

    def __init__(self):
        self._pending_codes: dict[str, PairingCode] = {}  # code_hash -> PairingCode
        self._used_hashes: set[str] = set()  # prevents replay

    def create_code(self, created_by: str = "cli") -> str:
        """Create a new pairing code. Returns the plaintext code."""
        plaintext, code = PairingCode.create(created_by=created_by)
        self._pending_codes[code.code_hash] = code
        _log.info("Pairing code created by %s (expires in %ds)", created_by, PAIRING_CODE_TTL_SECONDS)
        return plaintext

    def validate_code(self, plaintext: str) -> tuple[bool, str]:
        """
        Validate a pairing code submission.
        Returns (is_valid, error_reason).
        """
        from ..protocol.pairing import hash_pairing_code

        code_hash = hash_pairing_code(plaintext)

        # Replay check
        if code_hash in self._used_hashes:
            return False, ErrorCode.PAIRING_FAILED + ":code_replayed"

        # Existence check
        code = self._pending_codes.get(code_hash)
        if not code:
            return False, ErrorCode.PAIRING_FAILED + ":code_invalid"

        # Expiration check
        if code.is_expired():
            self._pending_codes.pop(code_hash, None)
            return False, ErrorCode.PAIRING_FAILED + ":code_expired"

        # Attempts check
        if code.is_exhausted():
            self._pending_codes.pop(code_hash, None)
            return False, ErrorCode.PAIRING_FAILED + ":code_exhausted"

        # Record attempt
        self._pending_codes[code_hash] = code.with_attempt()

        # Valid — but code is NOT consumed yet (consumed on explicit approval)
        return True, ""

    def consume_code(self, plaintext: str) -> bool:
        """Mark a pairing code as consumed (called after successful pairing)."""
        from ..protocol.pairing import hash_pairing_code

        code_hash = hash_pairing_code(plaintext)
        self._pending_codes.pop(code_hash, None)
        self._used_hashes.add(code_hash)
        return True

    def approve_pairing(
        self, request: PairingRequest, plaintext_code: str
    ) -> tuple[PairingApproval | None, str]:
        """
        Approve a pairing request. Returns (approval, error_reason).
        Consumes the pairing code on success.
        """
        # Validate code
        valid, reason = self.validate_code(plaintext_code)
        if not valid:
            return None, reason

        # Verify the code matches (constant-time)
        code_hash = list(self._pending_codes.keys())
        # Find matching code
        matching = None
        for ch in code_hash:
            c = self._pending_codes.get(ch)
            if c and c.verify(plaintext_code):
                matching = c
                break

        if not matching:
            return None, ErrorCode.PAIRING_FAILED + ":code_mismatch"

        # Parse node identity from request
        identity_data = request.node_identity
        node_id = identity_data.get("node_id", "")
        public_key = identity_data.get("public_key", "")

        if not node_id or not public_key:
            return None, ErrorCode.PAIRING_FAILED + ":invalid_identity"

        # Create approval
        approval = PairingApproval.create(node_id=node_id, public_key=public_key)

        # Consume the code
        self.consume_code(plaintext_code)

        _log.info("Pairing approved for node %s", node_id)
        return approval, ""

    def cleanup_expired(self) -> int:
        """Remove expired codes. Returns count of codes removed."""
        removed = 0
        for code_hash in list(self._pending_codes.keys()):
            code = self._pending_codes.get(code_hash)
            if code and code.is_expired():
                self._pending_codes.pop(code_hash, None)
                removed += 1
        return removed

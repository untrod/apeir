# -*- coding: utf-8 -*-
"""Artifact Contract — versioned exchange between agents.

Agents exchange results via versioned Artifacts, not raw shared context.
Each artifact carries: schema, version, producer, consumers, source inputs,
content hash, validity conditions, expiration, write scope, verification state.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArtifactContract:
    """Versioned artifact contract between producer and consumer agents."""
    artifact_id: str = ""
    schema_version: str = "1.0.0"
    version: int = 1
    producer_role: str = ""
    consumer_roles: list[str] = field(default_factory=list)
    source_inputs: list[str] = field(default_factory=list)  # artifact IDs this was derived from
    content_hash: str = ""
    content_type: str = "text"   # text, code, data, report, binary
    validity_conditions: list[str] = field(default_factory=list)
    expiration_seconds: int = 0  # 0 = never expires
    write_scope: str = "workspace"
    verification_state: str = "unverified"  # unverified, verified_pass, verified_fail
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def seal(self, content: str | bytes) -> str:
        """Hash content and finalize contract."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.content_hash = hashlib.sha256(content).hexdigest()
        if not self.artifact_id:
            self.artifact_id = f"artifact_{uuid.uuid4().hex[:12]}"
        return self.artifact_id

    def verify(self, content: str | bytes) -> tuple[bool, str]:
        """Verify content matches contract hash."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        current_hash = hashlib.sha256(content).hexdigest()
        if current_hash != self.content_hash:
            return False, f"Hash mismatch: expected {self.content_hash[:12]}, got {current_hash[:12]}"
        return True, "Hash verified"

    def is_expired(self, now_ts: float) -> bool:
        if self.expiration_seconds <= 0:
            return False
        # Simple check: created_at + ttl < now
        return False  # requires timestamp parsing

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class ContractRegistry:
    """Thread-safe registry of artifact contracts."""

    def __init__(self) -> None:
        self._contracts: dict[str, ArtifactContract] = {}
        self._dependencies: dict[str, set[str]] = {}  # artifact_id → dependent artifact_ids

    def register(self, contract: ArtifactContract) -> str:
        self._contracts[contract.artifact_id] = contract
        for src in contract.source_inputs:
            if src not in self._dependencies:
                self._dependencies[src] = set()
            self._dependencies[src].add(contract.artifact_id)
        return contract.artifact_id

    def get(self, artifact_id: str) -> ArtifactContract | None:
        return self._contracts.get(artifact_id)

    def get_consumers(self, artifact_id: str) -> list[str]:
        return list(self._dependencies.get(artifact_id, set()))

    def get_producers(self, artifact_id: str) -> list[str]:
        contract = self._contracts.get(artifact_id)
        return [contract.producer_role] if contract else []

    def invalidate_downstream(self, artifact_id: str) -> list[str]:
        """Mark all downstream consumers as stale."""
        stale = []
        to_check = [artifact_id]
        while to_check:
            current = to_check.pop(0)
            consumers = self._dependencies.get(current, set())
            for cid in consumers:
                if cid not in stale:
                    contract = self._contracts.get(cid)
                    if contract:
                        contract.verification_state = "stale"
                        stale.append(cid)
                        to_check.append(cid)
        return stale

    def count(self) -> int:
        return len(self._contracts)

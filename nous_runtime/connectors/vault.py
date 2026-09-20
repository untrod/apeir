"""Credential-vault boundaries for connectors."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class ConnectorCredential:
    value: str
    scopes: tuple[str, ...] = ()
    expires_at: str = ""

    @property
    def expired(self) -> bool:
        if not self.expires_at:
            return False
        value = self.expires_at.replace("Z", "+00:00")
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc)


class TokenVault(Protocol):
    def get(self, credential_ref: str) -> ConnectorCredential | None: ...
    def revoke(self, credential_ref: str) -> None: ...


class EnvironmentTokenVault:
    """Resolve token values from environment references without persistence."""

    def get(self, credential_ref: str) -> ConnectorCredential | None:
        if not credential_ref.startswith("env:"):
            return None
        value = os.environ.get(credential_ref[4:], "")
        return ConnectorCredential(value) if value else None

    def revoke(self, credential_ref: str) -> None:
        return None


class MemoryTokenVault:
    """Deterministic test vault. It is not a production secret store."""

    def __init__(self) -> None:
        self._items: dict[str, ConnectorCredential] = {}

    def put(self, reference: str, credential: ConnectorCredential) -> None:
        self._items[reference] = credential

    def get(self, credential_ref: str) -> ConnectorCredential | None:
        return self._items.get(credential_ref)

    def revoke(self, credential_ref: str) -> None:
        self._items.pop(credential_ref, None)
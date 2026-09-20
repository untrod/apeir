"""Connector adapter protocol and deterministic errors."""

from __future__ import annotations

from typing import Any, Protocol

from nous_runtime.connectors.models import ConnectorRequest, ConnectorResult
from nous_runtime.connectors.vault import ConnectorCredential


class ConnectorError(RuntimeError):
    retryable = False


class ConnectorRateLimitError(ConnectorError):
    retryable = True


class ConnectorTemporaryError(ConnectorError):
    retryable = True


class ConnectorAdapter(Protocol):
    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult: ...
    def health(self) -> dict[str, Any]: ...
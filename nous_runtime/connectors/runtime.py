"""Governed Connector Runtime execution service."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

from nous_runtime.connectors.base import ConnectorAdapter, ConnectorError
from nous_runtime.connectors.models import ConnectorRequest, ConnectorResult, ConnectorRisk
from nous_runtime.connectors.store import ConnectorStore
from nous_runtime.connectors.vault import TokenVault
from nous_runtime.governance import ActionProposal, AuthorizationContext, get_gate


class ConnectorRuntime:
    def __init__(self, store: ConnectorStore, vault: TokenVault, *, gate: Any = None, timeout_seconds: float = 30.0):
        self.store = store
        self.vault = vault
        self.gate = gate
        if timeout_seconds <= 0:
            raise ValueError("connector timeout must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self._adapters: dict[str, ConnectorAdapter] = {}
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def bind(self, connector_id: str, adapter: ConnectorAdapter) -> None:
        self._adapters[connector_id] = adapter

    def execute(self, request: ConnectorRequest, *, context: AuthorizationContext) -> ConnectorResult:
        registration = self.store.get(request.connector_id)
        if registration is None:
            return ConnectorResult(False, error_code="CONNECTOR_NOT_FOUND", message="Connector is not registered.")
        manifest, credential_ref, revoked = registration
        if revoked:
            return ConnectorResult(False, error_code="CONNECTOR_REVOKED", message="Connector is revoked.")
        action = manifest.action(request.action)
        if action is None:
            return ConnectorResult(False, error_code="ACTION_NOT_DECLARED", message="Connector action is not declared.")
        if not set(action.required_scopes).issubset(set(manifest.granted_scopes)):
            return ConnectorResult(False, error_code="SCOPE_DENIED", message="Required connector scope was not granted.")
        adapter = self._adapters.get(request.connector_id)
        if adapter is None:
            return ConnectorResult(False, error_code="ADAPTER_UNAVAILABLE", message="Connector adapter is unavailable.")
        credential = self.vault.get(credential_ref) if credential_ref else None
        if credential_ref and (credential is None or not credential.value):
            return ConnectorResult(False, error_code="CREDENTIAL_UNAVAILABLE", message="Connector credential is unavailable.")
        if credential is not None and credential.expired:
            return ConnectorResult(False, error_code="CREDENTIAL_EXPIRED", message="Connector credential is expired.")
        if credential is not None and not set(action.required_scopes).issubset(set(credential.scopes or manifest.granted_scopes)):
            return ConnectorResult(False, error_code="CREDENTIAL_SCOPE_DENIED", message="Credential scope is insufficient.")
        if not self._allow_rate(request.connector_id, manifest.rate_limit_per_minute):
            return ConnectorResult(False, error_code="RATE_LIMITED", message="Connector rate limit exceeded.")
        if action.risk == ConnectorRisk.WRITE:
            decision = (self.gate or get_gate()).evaluate(
                ActionProposal(
                    action_type="connector.execute",
                    capability_id=f"connector.{request.connector_id}.{request.action}",
                    params=request.params,
                    target_workspace=request.workspace_id,
                    affected_resources=(f"connector:{request.connector_id}",),
                    external_recipients=(request.connector_id,),
                    side_effect_class="external_write",
                    reversibility="unknown",
                    retry_behavior="idempotent" if action.idempotent else "non_idempotent",
                ),
                context,
            )
            if decision.action_mode != "EXECUTE":
                return ConnectorResult(False, error_code="AUTHORIZATION_REQUIRED", message=str(decision.reason_message or decision.reason_code))
        cached = self.store.get_idempotent(request.connector_id, request.idempotency_key)
        if cached is not None:
            return ConnectorResult(ok=bool(cached["ok"]), items=tuple(cached.get("items") or ()), next_cursor=str(cached.get("next_cursor") or ""), error_code=str(cached.get("error_code") or ""), message=str(cached.get("message") or ""), attempts=int(cached.get("attempts") or 1))
        result = self._invoke(adapter, request, credential, retries=manifest.max_retries if action.idempotent else 0)
        if result.ok and result.next_cursor:
            self.store.set_cursor(request.connector_id, result.next_cursor)
        self.store.set_health(request.connector_id, adapter.health())
        self.store.save_idempotent(request.connector_id, request.idempotency_key, {"ok": result.ok, "items": list(result.items), "next_cursor": result.next_cursor, "error_code": result.error_code, "message": result.message, "attempts": result.attempts})
        return result

    def _invoke(self, adapter: ConnectorAdapter, request: ConnectorRequest, credential: Any, *, retries: int) -> ConnectorResult:
        attempts = 0
        while True:
            attempts += 1
            try:
                result = self._execute_bounded(adapter, request, credential)
                if result is None:
                    return ConnectorResult(
                        False,
                        error_code="CONNECTOR_TIMEOUT",
                        message=f"Connector exceeded {self.timeout_seconds:g} seconds.",
                        attempts=attempts,
                    )
                return ConnectorResult(result.ok, result.items, result.next_cursor, result.error_code, result.message, attempts)
            except ConnectorError as exc:
                if not exc.retryable or attempts > retries + 1:
                    return ConnectorResult(False, error_code="CONNECTOR_ERROR", message=str(exc), attempts=attempts)
                time.sleep(min(0.01 * (2 ** (attempts - 1)), 0.1))
            except Exception as exc:
                return ConnectorResult(
                    False,
                    error_code="CONNECTOR_FAILURE",
                    message=f"Connector failed: {type(exc).__name__}",
                    attempts=attempts,
                )

    def _execute_bounded(
        self,
        adapter: ConnectorAdapter,
        request: ConnectorRequest,
        credential: Any,
    ) -> ConnectorResult | None:
        completed = threading.Event()
        result: list[ConnectorResult] = []
        failure: list[Exception] = []

        def invoke() -> None:
            try:
                result.append(adapter.execute(request, credential))
            except Exception as exc:
                failure.append(exc)
            finally:
                completed.set()

        threading.Thread(
            target=invoke,
            name=f"nous-connector-{request.connector_id}",
            daemon=True,
        ).start()
        if not completed.wait(self.timeout_seconds):
            return None
        if failure:
            raise failure[0]
        return result[0]

    def _allow_rate(self, connector_id: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            calls = self._calls[connector_id]
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= limit:
                return False
            calls.append(now)
            return True
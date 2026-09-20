"""Portable helpers for submitting integration observations through NKI."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Protocol


class OperationClientProtocol(Protocol):
    async def execute_operation(
        self, operation: dict[str, Any], idempotency_key: str = ""
    ) -> dict[str, Any]: ...


def observation_operation(
    *,
    adapter: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
    timeout_ms: int = 10_000,
) -> dict[str, Any]:
    """Build an effect-free, idempotent observation operation."""
    body = {
        "schema_version": 1,
        "kind": "integration_observation",
        "adapter": str(adapter),
        "payload": _safe_payload(payload),
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{adapter}\n{idempotency_key}\n{encoded}".encode("utf-8")
    ).hexdigest()
    operation_id = f"integration-{digest}"
    return {
        "operation_id": operation_id,
        "workload_id": f"workload-{operation_id}",
        "step_id": "record-observation",
        "backend": "reference",
        "execution_domain": "reference",
        "model": "integration-observation-v1",
        "endpoint": "",
        "credential_env": "",
        "provider_entrypoint": "",
        "input": encoded,
        "delivery": "IDEMPOTENT",
        "snapshot": {
            "model_revision": "none",
            "provider_revision": "reference-v1",
            "prompt_revision": "none",
            "tool_revision": "none",
            "knowledge_revision": "none",
            "policy_revision": "integration-observation-v1",
            "capability_revision": f"integration.{adapter}.observe-v1",
            "context_revision": "none",
        },
        "timeout_ms": max(1, min(int(timeout_ms), 120_000)),
    }


def _safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > 256 * 1024:
        raise ValueError("integration observation exceeds 256 KiB")
    _reject_sensitive_fields(value)
    return value


def _reject_sensitive_fields(value: Any) -> None:
    sensitive = {"api_key", "authorization", "password", "secret", "token"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in sensitive or any(
                normalized.endswith(f"_{marker}") for marker in sensitive
            ):
                raise ValueError(
                    "integration observations must not contain credential material"
                )
            _reject_sensitive_fields(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_sensitive_fields(child)


__all__ = ["OperationClientProtocol", "observation_operation"]

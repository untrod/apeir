"""Exercise the existing NKI client against an owned native-smoke Kernel.

No external model is contacted: the only model operation deliberately uses a
credential reference forbidden by the smoke Kernel's empty allowlist. Recovery
queries that original failed workload and never submits another operation.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

from compat.nki_client import NKIClient, NKIError, NKIRequest, NKI_VERSION


class HealthRequest(NKIRequest):
    def __init__(self, version: int):
        super().__init__(method="HealthCheck", payload={"deep": True})
        self.version = version

    def to_dict(self):
        value = super().to_dict()
        value["nki_version"] = self.version
        return value


async def _expect_error(call, code: str, *, message: str = "") -> None:
    try:
        await asyncio.wait_for(call(), timeout=5)
    except NKIError as error:
        assert error.code == code, "Kernel returned an unexpected rejection code"
        if message:
            assert message in error.message, "Kernel rejected at an unexpected boundary"
    else:
        raise AssertionError("Kernel accepted a request that must be rejected")


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def qualify(endpoint: str, previous: dict | None = None) -> dict:
    address = urlsplit(endpoint)
    assert (
        address.scheme == "tcp"
        and address.hostname == "127.0.0.1"
        and address.port
        and not address.username
        and not address.password
        and not address.path
        and not address.query
        and not address.fragment
    ), "Native smoke must target its owned loopback Kernel only"
    token = os.environ.get("NOUS_NKI_TOKEN", "")
    assert len(token) >= 32, "Native smoke requires an authenticated Kernel"
    assert os.environ.get("NOUS_ALLOWED_CREDENTIALS") == "", (
        "The smoke model's credential must not be admitted"
    )
    started = time.monotonic()
    client = NKIClient(endpoint)
    await asyncio.wait_for(client._connect(), timeout=5)
    try:
        health = await asyncio.wait_for(client.health_check(deep=True), timeout=5)
        assert health.get("state") == "READY"
        assert health.get("node", {}).get("connection") == "CONNECTED"
        capabilities = health["node"]["capabilities"]
        versions = []
        for version in range(1, NKI_VERSION + 1):
            assert f"nki.v{version}" in capabilities
            result = await asyncio.wait_for(
                client._send(HealthRequest(version)), timeout=5
            )
            assert result.get("state") == "READY"
            versions.append(version)

        if previous is None:
            for version in (0, NKI_VERSION + 1):
                await _expect_error(
                    lambda version=version: client._send(HealthRequest(version)),
                    "NKI_VERSION_UNSUPPORTED",
                )
            try:
                for invalid in ("", uuid.uuid4().hex + uuid.uuid4().hex):
                    os.environ["NOUS_NKI_TOKEN"] = invalid
                    await _expect_error(client.health_check, "UNAUTHENTICATED")
            finally:
                os.environ["NOUS_NKI_TOKEN"] = token

            identity = "native-smoke-denied-model-" + uuid.uuid4().hex
            operation = {
                "operation_id": identity,
                "workload_id": identity,
                "step_id": "credential-denial",
                "backend": "openai-compatible",
                "execution_domain": "remote",
                "model": "never-invoke",
                "endpoint": "http://127.0.0.1:9/v1/chat/completions",
                "credential_env": "APEIR_NATIVE_SMOKE_NEVER_ALLOWED",
                "input": json.dumps(
                    {
                        "schema_version": 1,
                        "capability": "chat",
                        "messages": [{"role": "user", "content": "smoke"}],
                    }
                ),
                "delivery": "AT_MOST_ONCE",
                "snapshot": {
                    name + "_revision": "native-smoke"
                    for name in (
                        "model",
                        "provider",
                        "prompt",
                        "tool",
                        "knowledge",
                        "policy",
                        "capability",
                        "context",
                    )
                },
                "timeout_ms": 1000,
            }
            await _expect_error(
                lambda: client.execute_operation(operation, idempotency_key=identity),
                "PROVIDER_ERROR",
                message="credential reference is not authorized for provider use",
            )
        else:
            assert previous["status"] == "PASS"
            identity = previous["original_workload_id"]

        profile = await asyncio.wait_for(client.get_workload(identity), timeout=5)
        assert profile["workload_id"] == profile["operation_id"] == identity
        assert profile["failure_code"] == "PROVIDER_ERROR"
        assert profile["retry_count"] == 0
        digest = _digest(profile)
        if previous is not None:
            assert digest == previous["original_profile_sha256"], (
                "Original failed model evidence changed during restart"
            )
        return {
            "status": "PASS",
            "scope": "native component compatibility; not installation or sandbox qualification",
            "request_versions_exercised": versions,
            "kernel_runtime_version": health["runtime_version"],
            "invalid_versions_rejected": True if previous is None else None,
            "wrong_and_missing_nki_credentials_rejected": True
            if previous is None
            else None,
            "unauthorized_model_credential": "DENIED_BEFORE_PROVIDER_SPAWN",
            "original_workload_id": identity,
            "original_profile_sha256": digest,
            "original_failure_code": profile["failure_code"],
            "recovery_query_only": previous is not None,
            "model_operation_submissions": 0 if previous is not None else 1,
            "external_model_calls": 0,
            "elapsed_seconds": time.monotonic() - started,
        }
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    previous = json.loads(args.resume_from.read_text()) if args.resume_from else None
    try:
        result = asyncio.run(qualify(args.endpoint, previous))
    except Exception as error:
        # Never serialize exception text, tokens, frames, runtime databases or logs.
        result = {
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error_code": getattr(error, "code", "NATIVE_NKI_PROBE_FAILED"),
        }
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

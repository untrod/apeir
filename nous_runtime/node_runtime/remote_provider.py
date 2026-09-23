"""External-provider adapter from Kernel requests to the durable Node Relay spool."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(_canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _target_binding(config_path: Path, target_ref: str) -> dict[str, Any]:
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise ValueError("reality registry config is invalid")
    matches = [
        target["target_binding"]
        for target in value.get("targets", [])
        if isinstance(target, dict)
        and isinstance(target.get("target_binding"), dict)
        and target["target_binding"].get("target_ref") == target_ref
    ]
    if len(matches) != 1:
        raise ValueError("effect target does not resolve to one governed binding")
    return matches[0]


def execute_remote_provider(
    provider_request: dict[str, Any], environ: Mapping[str, str] = os.environ
) -> dict[str, Any]:
    if (
        provider_request.get("schema_version") != 2
        or provider_request.get("type") != "execute"
    ):
        raise ValueError("remote provider requires execute schema version 2")
    request = provider_request.get("request")
    if not isinstance(request, dict):
        raise TypeError("remote provider request is missing Kernel operation")
    operation_id = str(request.get("operation_id", ""))
    if not _SAFE_ID.fullmatch(operation_id):
        raise ValueError("remote provider operation_id is invalid")
    if request.get("delivery") != "AT_MOST_ONCE":
        raise ValueError("M2 remote provider currently requires AT_MOST_ONCE")
    effect = request.get("effect_contract")
    snapshot = request.get("snapshot")
    if not isinstance(effect, dict) or not isinstance(snapshot, dict):
        raise TypeError("remote provider requires effect contract and snapshot")
    relay_state = Path(environ["APEIR_RELAY_STATE_DIR"]).expanduser().resolve()
    reality_config = (
        Path(environ["APEIR_REALITY_CONFIG"]).expanduser().resolve(strict=True)
    )
    target = _target_binding(reality_config, str(effect.get("target", "")))
    input_text = request.get("input")
    if not isinstance(input_text, str):
        raise TypeError("remote provider input must be a JSON object string")
    arguments = json.loads(input_text)
    if not isinstance(arguments, dict):
        raise TypeError("remote provider input must decode to an object")
    input_digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    binding = {
        "intent_id": operation_id,
        "effect_contract_digest": hashlib.sha256(_canonical(effect)).hexdigest(),
        "target_ref": target["target_ref"],
        "target_binding_digest": hashlib.sha256(_canonical(target)).hexdigest(),
        "workload_id": str(request.get("workload_id", "")),
        "request_digest": input_digest,
        "provider_revision": str(snapshot.get("provider_revision", "")),
    }
    if not all(binding.values()):
        raise ValueError("remote provider Kernel binding is incomplete")
    spool_request = {
        "schema": "nous.remote-provider-request/v1",
        "operation_id": operation_id,
        "node_id": str(target.get("node_id", "")),
        "capability": str(request.get("model", "")),
        "arguments": arguments,
        "timeout_seconds": max(
            float(request.get("timeout_ms", 30_000)) / 1000.0, 0.001
        ),
        "delivery_semantics": "at_most_once",
        "binding": binding,
    }
    if not spool_request["node_id"] or not spool_request["capability"]:
        raise ValueError("remote provider target node and capability are required")
    request_path = relay_state / "provider-requests" / f"{operation_id}.json"
    result_path = relay_state / "provider-results" / f"{operation_id}.json"
    if request_path.is_file():
        existing = json.loads(request_path.read_text(encoding="utf-8"))
        if existing != spool_request:
            raise ValueError("remote provider operation binding collision")
    elif not result_path.is_file():
        _atomic_json(request_path, spool_request)
    deadline = time.monotonic() + max(
        float(request.get("timeout_ms", 30_000)) / 1000.0, 0.001
    )
    while not result_path.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "remote provider result timed out; operation outcome is unknown"
            )
        time.sleep(0.05)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise TypeError("remote provider result is invalid")
    if not result.get("ok"):
        return {
            "ok": False,
            "error": {
                "code": str(result.get("error_code") or "REMOTE_EXECUTION_FAILED"),
                "message": str(
                    result.get("error_message") or "remote execution failed"
                ),
            },
        }
    remote = result.get("remote_execution_receipt")
    if not isinstance(remote, dict) or any(
        remote.get(field) != value
        for field, value in {
            "operation_id": operation_id,
            "workload_id": binding["workload_id"],
            "intent_id": binding["intent_id"],
            "effect_contract_digest": binding["effect_contract_digest"],
            "target_ref": binding["target_ref"],
            "target_binding_digest": binding["target_binding_digest"],
            "request_digest": binding["request_digest"],
            "provider_revision": binding["provider_revision"],
        }.items()
    ):
        raise ValueError("remote provider result binding mismatch")
    return {
        "ok": True,
        "output": json.dumps(
            result.get("output"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "remote_execution_receipt": remote,
    }


def main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read())
        if not isinstance(request, dict):
            raise TypeError("provider request must be an object")
        response = execute_remote_provider(request)
    except TimeoutError as exc:
        response = {
            "ok": False,
            "error": {
                "code": "NOUS_NODE_UNCERTAIN_EFFECT",
                "message": str(exc),
            },
        }
    except (KeyError, OSError, TypeError, ValueError) as exc:
        response = {
            "ok": False,
            "error": {
                "code": "REMOTE_PROVIDER_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

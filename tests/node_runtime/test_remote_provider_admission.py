"""Remote spool admission contracts; signed transport remains covered separately."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from nous_runtime.node_runtime import remote_provider


@pytest.fixture
def bound_request(tmp_path):
    target = {"target_ref": "device://test", "node_id": "node-test"}
    config = tmp_path / "reality.json"
    config.write_text(
        json.dumps({"schema_version": 2, "targets": [{"target_binding": target}]}),
        encoding="utf-8",
    )
    environ = {
        "APEIR_RELAY_STATE_DIR": str(tmp_path / "relay"),
        "APEIR_REALITY_CONFIG": str(config),
    }
    request = {
        "schema_version": 2,
        "type": "execute",
        "request": {
            "operation_id": "operation-test",
            "workload_id": "work-test",
            "delivery": "AT_MOST_ONCE",
            "effect_contract": {"target": target["target_ref"]},
            "snapshot": {"provider_revision": "provider-test"},
            "input": '{"version":"2"}',
            "model": "firmware.test",
            "timeout_ms": 0,
        },
    }
    return request, environ


def _paths(environ):
    root = Path(environ["APEIR_RELAY_STATE_DIR"])
    return (
        root / "provider-requests" / "operation-test.json",
        root / "provider-results" / "operation-test.json",
    )


def _publish_result(request_path, result_path):
    spool = json.loads(request_path.read_text(encoding="utf-8"))
    remote_provider._atomic_json(
        result_path,
        {
            "ok": True,
            "output": {"version": "2"},
            "remote_execution_receipt": {
                **spool["binding"],
                "operation_id": spool["operation_id"],
            },
        },
    )


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        "NaN",
        "Infinity",
        "1e999",
        True,
        False,
        None,
        -1,
        "invalid",
        10**1000,
    ],
)
def test_invalid_timeout_cannot_publish_or_wait(bound_request, monkeypatch, value):
    request, environ = bound_request
    request["request"]["timeout_ms"] = value

    def forbidden_wait(_):
        pytest.fail("invalid timeout reached result polling")

    monkeypatch.setattr(remote_provider.time, "sleep", forbidden_wait)
    with pytest.raises(ValueError, match="timeout must be finite and nonnegative"):
        remote_provider.execute_remote_provider(request, environ)
    assert not Path(environ["APEIR_RELAY_STATE_DIR"]).exists()


@pytest.mark.parametrize(
    "value, expected", [(0, 0.001), (1000, 1.0), ("2500", 2.5), (0.5, 0.001)]
)
def test_valid_timeout_and_lost_response_preserve_original_request(
    bound_request, value, expected
):
    request, environ = bound_request
    request["request"]["timeout_ms"] = value
    # Avoid waiting for the positive timeout: publish the result during admission.
    original = remote_provider._atomic_json
    request_path, result_path = _paths(environ)

    def publish(path, record):
        original(path, record)
        if path == request_path:
            _publish_result(request_path, result_path)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(remote_provider, "_atomic_json", publish)
        assert remote_provider.execute_remote_provider(request, environ)["ok"]
    assert json.loads(request_path.read_text())["timeout_seconds"] == expected


def test_lost_response_then_restart_reconciles_without_republication(
    bound_request, monkeypatch
):
    request, environ = bound_request
    request_path, result_path = _paths(environ)
    with pytest.raises(TimeoutError, match="outcome is unknown"):
        remote_provider.execute_remote_provider(request, environ)
    original_bytes = request_path.read_bytes()
    _publish_result(request_path, result_path)

    def forbidden_publish(*_):
        pytest.fail("recovery must not republish a possible effect")

    monkeypatch.setattr(remote_provider, "_atomic_json", forbidden_publish)
    assert remote_provider.execute_remote_provider(request, environ)["ok"]
    assert request_path.read_bytes() == original_bytes
    # A fresh interpreter exercises durable recovery, not an in-memory cache.
    import os

    completed = subprocess.run(
        [sys.executable, "-m", "nous_runtime.node_runtime.remote_provider"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env={**os.environ, **environ},
        timeout=10,
        check=True,
    )
    assert json.loads(completed.stdout)["ok"]
    assert request_path.read_bytes() == original_bytes
    request_path.unlink()
    assert remote_provider.execute_remote_provider(request, environ)["ok"]
    assert not request_path.exists()


@pytest.mark.parametrize("field", ["input", "workload_id", "model", "timeout_ms"])
def test_changed_operation_binding_cannot_replace_original(bound_request, field):
    request, environ = bound_request
    with pytest.raises(TimeoutError):
        remote_provider.execute_remote_provider(request, environ)
    request_path, _ = _paths(environ)
    original_bytes = request_path.read_bytes()
    changed = copy.deepcopy(request)
    changed["request"][field] = 2 if field == "timeout_ms" else '"changed"'
    if field == "input":
        changed["request"][field] = '{"version":"3"}'
    with pytest.raises(ValueError, match="binding collision"):
        remote_provider.execute_remote_provider(changed, environ)
    assert request_path.read_bytes() == original_bytes


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_admission_has_one_immutable_request(
    bound_request, monkeypatch, different
):
    request, environ = bound_request
    other = copy.deepcopy(request)
    if different:
        other["request"]["input"] = '{"version":"3"}'
    request_path, result_path = _paths(environ)
    original_write = remote_provider._atomic_json
    original_lock = remote_provider.file_lock
    writing = threading.Event()
    release = threading.Event()
    second_attempt = threading.Event()
    writers = []

    @contextmanager
    def observed_lock(path):
        if writing.is_set():
            second_attempt.set()
        with original_lock(path):
            yield

    def paused_write(path, record):
        if path == request_path:
            writers.append(record)
            writing.set()
            assert release.wait(5)
        original_write(path, record)
        if path == request_path:
            _publish_result(request_path, result_path)

    monkeypatch.setattr(remote_provider, "file_lock", observed_lock)
    monkeypatch.setattr(remote_provider, "_atomic_json", paused_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(remote_provider.execute_remote_provider, request, environ)
        assert writing.wait(5)
        second = pool.submit(remote_provider.execute_remote_provider, other, environ)
        try:
            assert second_attempt.wait(5)
            assert not first.done() and not second.done()
        finally:
            release.set()
        assert first.result(timeout=5)["ok"]
        if different:
            with pytest.raises(ValueError, match="binding collision"):
                second.result(timeout=5)
        else:
            assert second.result(timeout=5)["ok"]
    assert len(writers) == 1
    assert json.loads(request_path.read_text())["arguments"] == {"version": "2"}
    assert not request_path.with_suffix(".json.tmp").exists()


def test_cached_result_still_requires_exact_receipt_binding(bound_request):
    request, environ = bound_request
    with pytest.raises(TimeoutError):
        remote_provider.execute_remote_provider(request, environ)
    request_path, result_path = _paths(environ)
    _publish_result(request_path, result_path)
    result = json.loads(result_path.read_text())
    result["remote_execution_receipt"]["request_digest"] = "tampered"
    remote_provider._atomic_json(result_path, result)
    with pytest.raises(ValueError, match="result binding mismatch"):
        remote_provider.execute_remote_provider(request, environ)

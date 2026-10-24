"""Probe-driver regressions; only a real EXE run can qualify native components."""

import asyncio
import json
import os
import sys
import uuid

import pytest

from compat.nki_client import NKIError
from scripts.ci import probe_native_nki as probe


@pytest.fixture
def kernel(monkeypatch):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    monkeypatch.setenv("NOUS_NKI_TOKEN", token)
    monkeypatch.setenv("NOUS_ALLOWED_CREDENTIALS", "")

    class Client:
        submitted = []
        profiles = {}
        accept_bad_auth = False

        def __init__(self, endpoint):
            self.closed = False

        async def _connect(self):
            pass

        async def close(self):
            self.closed = True

        async def health_check(self, deep=False):
            if os.environ["NOUS_NKI_TOKEN"] != token and not self.accept_bad_auth:
                raise NKIError("UNAUTHENTICATED", "rejected")
            return {
                "state": "READY",
                "runtime_version": "fixture",
                "node": {
                    "connection": "CONNECTED",
                    "capabilities": ["nki.v1", "nki.v2", "nki.v3"],
                },
            }

        async def _send(self, request):
            if request.version not in (1, 2, 3):
                raise NKIError("NKI_VERSION_UNSUPPORTED", "rejected")
            return await self.health_check()

        async def execute_operation(self, operation, idempotency_key):
            self.submitted.append(operation)
            assert operation["credential_env"] == "APEIR_NATIVE_SMOKE_NEVER_ALLOWED"
            assert operation["delivery"] == "AT_MOST_ONCE"
            self.profiles[operation["workload_id"]] = {
                "workload_id": operation["workload_id"],
                "operation_id": operation["operation_id"],
                "failure_code": "PROVIDER_ERROR",
                "retry_count": 0,
            }
            raise NKIError(
                "PROVIDER_ERROR",
                "credential reference is not authorized for provider use",
            )

        async def get_workload(self, workload_id):
            return self.profiles[workload_id]

    monkeypatch.setattr(probe, "NKIClient", Client)
    return Client, token


def test_original_denial_is_queried_after_restart_without_resubmission(kernel):
    client, token = kernel
    original = asyncio.run(probe.qualify("tcp://127.0.0.1:1234"))
    recovered = asyncio.run(probe.qualify("tcp://127.0.0.1:1234", original))
    assert len(client.submitted) == 1
    assert recovered["model_operation_submissions"] == 0
    assert recovered["recovery_query_only"] is True
    assert recovered["original_workload_id"] == original["original_workload_id"]
    assert token not in json.dumps(original)
    assert os.environ["NOUS_NKI_TOKEN"] == token


def test_authentication_false_success_is_rejected(kernel):
    client, token = kernel
    client.accept_bad_auth = True
    with pytest.raises(AssertionError, match="must be rejected"):
        asyncio.run(probe.qualify("tcp://127.0.0.1:1234"))
    assert not client.submitted
    assert os.environ["NOUS_NKI_TOKEN"] == token


def test_modified_original_profile_cannot_pass_recovery(kernel):
    client, _ = kernel
    original = asyncio.run(probe.qualify("tcp://127.0.0.1:1234"))
    client.profiles[original["original_workload_id"]]["changed"] = True
    with pytest.raises(AssertionError, match="evidence changed"):
        asyncio.run(probe.qualify("tcp://127.0.0.1:1234", original))
    assert len(client.submitted) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "tcp://example.invalid:1234",
        "tcp://user@127.0.0.1:1234",
        "http://127.0.0.1:1234",
        "tcp://127.0.0.1:1234/path",
    ],
)
def test_probe_does_not_contact_unowned_endpoints(kernel, endpoint):
    with pytest.raises(AssertionError, match="owned loopback"):
        asyncio.run(probe.qualify(endpoint))


def test_failure_report_does_not_disclose_exception_content(
    kernel, monkeypatch, tmp_path
):
    _, token = kernel

    async def fail(*args):
        raise NKIError("UNAUTHENTICATED", token)

    monkeypatch.setattr(probe, "qualify", fail)
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["probe", "--endpoint", "tcp://127.0.0.1:1", "--report", str(report)],
    )
    assert probe.main() == 1
    assert token not in report.read_text()
    assert json.loads(report.read_text())["status"] == "FAIL"

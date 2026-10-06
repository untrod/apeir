"""Protected KV-v2 contracts and optional real OpenBao software qualification."""

import asyncio
import contextlib
import json
import logging
import os
import pickle
import subprocess
import time
from pathlib import Path

import pytest
import requests

from nous_runtime.agent import AgentSessionState
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.governance.credentials import (
    CredentialBroker,
    OpenBaoKv2SecretBackend,
    SecretHandle,
)
from nous_runtime.node_runtime.distributed_work import DistributedWorkState
from tests.interoperability.test_opa_policy import Response
from tests.reality.test_simulated_execution import (
    FAKE_CREDENTIAL,
    STABLE,
    SimulationFault,
    _build_context,
    wait_for,
    SECRET_HANDLE,
    WORK_ID,
    approve_credential_firmware,
    assert_no_credential_on_disk,
    request_firmware,
    resume_firmware,
    simulation,
)

TOKEN = "apeir-openbao-test-read-only-token-714925"
ROOT = "apeir-openbao-test-bootstrap-root-852741"


def backend(endpoint="http://127.0.0.1:8200", **options):
    return OpenBaoKv2SecretBackend(
        endpoint,
        token=options.pop("token", TOKEN),
        references=options.pop(
            "references", {SECRET_HANDLE: ("secret", "apeir/firmware", "value")}
        ),
        **options,
    )


def transport(monkeypatch, response):
    calls = []

    def get(session, url, **kwargs):
        assert session.trust_env is True
        assert callable(session.auth)
        assert kwargs["allow_redirects"] is False
        calls.append((url, kwargs))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    return calls


def test_resolution_has_explicit_identity_and_protected_nonserializable_config(
    monkeypatch,
):
    calls = transport(
        monkeypatch, Response({"data": {"data": {"value": FAKE_CREDENTIAL}}})
    )
    store = backend()
    assert store.resolve(SecretHandle(vault_path=SECRET_HANDLE)) == FAKE_CREDENTIAL
    assert calls[0][1]["headers"]["X-Vault-Token"] == TOKEN
    assert store.discover()["authority"] is False
    assert store.discover()["dynamic_leases"] is False
    assert redact_sensitive_data(store) == "<REDACTED>"
    assert TOKEN not in repr(store)
    with pytest.raises(TypeError):
        pickle.dumps(store)
    with pytest.raises(PermissionError):
        store.resolve(SecretHandle(vault_path="secret_" + "f" * 32))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test",
        "https://user:pass@example.test",
        "https://example.test/path",
        "https://example.test?token=value",
        "https://example.test#fragment",
        "http://127.0.0.1:bad",
        "file:///tmp/store",
    ],
)
def test_unsafe_origin_denied(endpoint):
    with pytest.raises(ValueError):
        backend(endpoint)


@pytest.mark.parametrize(
    "reference",
    [
        ("secret", "../escape", "value"),
        ("secret", "apeir//firmware", "value"),
        ("secret/escape", "path", "value"),
        ("secret", "path?version=1", "value"),
        ("secret", "path", ""),
        ("secret", "path"),
    ],
)
def test_untrusted_binding_denied(reference):
    with pytest.raises(ValueError):
        backend(references={SECRET_HANDLE: reference})


@pytest.mark.parametrize("timeout", [0, -1, 11, float("nan"), float("inf"), "bad"])
def test_unbounded_timeout_denied(timeout):
    with pytest.raises(ValueError):
        backend(timeout_seconds=timeout)


@pytest.mark.parametrize(
    "response",
    [
        Response({}, status=403),
        Response({}, status=302),
        Response({}, content_type="text/plain"),
        Response(b"not-json"),
        Response([]),
        Response({}),
        Response({"data": {"data": {"value": ""}}}),
        Response({"data": {"data": {"value": 42}}}),
        Response(b"x" * 65537),
        requests.Timeout("transport detail"),
        requests.exceptions.SSLError("certificate detail"),
    ],
)
def test_resolution_errors_fail_closed_without_raw_detail(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(
        PermissionError, match="^Secret backend value unavailable$"
    ) as error:
        backend().resolve(SecretHandle(vault_path=SECRET_HANDLE))
    assert error.value.__cause__ is None


def test_unknown_material_in_transport_diagnostics_is_suppressed(
    monkeypatch, caplog, capsys
):
    unknown = "apeir-newly-fetched-not-yet-registered-value-537291"

    def get(*args, **kwargs):
        print(unknown)
        logging.getLogger("openbao.transport").warning(
            unknown, extra={"payload": unknown}
        )
        raise requests.RequestException(unknown)

    monkeypatch.setattr(requests.Session, "get", get)
    with caplog.at_level(logging.WARNING), pytest.raises(PermissionError):
        backend().resolve(SecretHandle(vault_path=SECRET_HANDLE))
    assert unknown not in caplog.text + capsys.readouterr().out
    assert all(getattr(record, "payload", "") != unknown for record in caplog.records)
    logging.getLogger("ordinary").warning("ordinary output survives")
    assert "ordinary output survives" in caplog.text


def test_health_never_sends_store_identity_or_authorizes(monkeypatch):
    calls = transport(monkeypatch, Response({"sealed": False}))
    assert backend().health()["verified_live"] is True
    assert "X-Vault-Token" not in calls[0][1]["headers"]


@pytest.fixture
def openbao_service():
    image = os.environ.get("APEIR_OPENBAO_TEST_IMAGE")
    if not image:
        pytest.skip("explicit real OpenBao acceptance image not configured")
    environment = dict(os.environ)
    command = ["docker"]
    if Path("/var/run/docker.sock").exists():
        command.append("--host=unix:///var/run/docker.sock")
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environment.pop(key, None)

    def docker(*args):
        return subprocess.run(
            [*command, *args],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()

    container = docker(
        "run",
        "--detach",
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs=/tmp",
        "--publish=127.0.0.1::8200",
        "--entrypoint=bao",
        image,
        "server",
        "-dev",
        "-dev-no-store-token",
        "-dev-root-token-id=" + ROOT,
        "-dev-listen-address=0.0.0.0:8200",
    )
    try:
        info = json.loads(docker("inspect", container))[0]
        port = info["NetworkSettings"]["Ports"]["8200/tcp"][0]["HostPort"]
        endpoint = f"http://127.0.0.1:{port}"
        store = backend(endpoint)
        deadline = time.monotonic() + 10
        while not store.health()["verified_live"]:
            if time.monotonic() > deadline:
                pytest.fail("actual OpenBao service did not become healthy")
            time.sleep(0.05)

        def admin(method, path, payload=None):
            response = requests.request(
                method,
                endpoint + "/v1/" + path,
                headers={"X-Vault-Token": ROOT},
                json=payload,
                timeout=2,
                allow_redirects=False,
            )
            assert response.status_code in {200, 204}
            return response.json() if response.content else {}

        admin(
            "POST", "secret/data/apeir/firmware", {"data": {"value": FAKE_CREDENTIAL}}
        )
        admin(
            "PUT",
            "sys/policies/acl/apeir-reader",
            {"policy": 'path "secret/data/apeir/firmware" { capabilities = ["read"] }'},
        )
        issued = admin(
            "POST",
            "auth/token/create",
            {
                "id": TOKEN,
                "policies": ["apeir-reader"],
                "no_default_policy": True,
                "ttl": "60s",
                "renewable": False,
            },
        )
        assert issued["auth"]["client_token"] == TOKEN
        yield (
            store,
            endpoint,
            lambda: admin("POST", "auth/token/revoke", {"token": TOKEN}),
            admin,
        )
    finally:
        with contextlib.suppress(subprocess.CalledProcessError):
            docker("rm", "--force", container)


@pytest.mark.integration
def test_real_read_only_token_scope_and_revocation(openbao_service):
    store, endpoint, revoke, _ = openbao_service
    assert store.resolve(SecretHandle(vault_path=SECRET_HANDLE)) == FAKE_CREDENTIAL
    for method, path in [
        ("POST", "secret/data/apeir/firmware"),
        ("GET", "secret/data/other"),
    ]:
        response = requests.request(
            method,
            endpoint + "/v1/" + path,
            headers={"X-Vault-Token": TOKEN},
            json={"data": {"value": "denied"}},
            timeout=2,
        )
        assert response.status_code == 403
    revoke()
    assert store.health()["verified_live"] is True
    with pytest.raises(PermissionError):
        store.resolve(SecretHandle(vault_path=SECRET_HANDLE))


@pytest.mark.integration
@pytest.mark.parametrize("approved", [True, False])
def test_real_openbao_original_firmware_work_and_denial(
    tmp_path, openbao_service, approved
):
    store, _, _, _ = openbao_service

    async def scenario():
        async with simulation(tmp_path / "runtime") as sim:
            sim.secret_backend = store
            sim.secret_handle = SecretHandle(vault_path=SECRET_HANDLE)
            sim.credential_broker = CredentialBroker(sim.governance, store)
            sim.firmware_handler.credential_broker = sim.credential_broker
            paused = await request_firmware(sim)
            original = sim.work().execution_arguments.copy()
            if approved:
                approve_credential_firmware(sim, paused)
            else:
                sim.handler.approvals.deny_operation(
                    paused.pending_approvals[0], _build_context(), gate=sim.governance
                )
            result = await resume_firmware(sim, paused.session_id)
            assert result.workflow_run_id == paused.workflow_run_id
            assert result.plan_history == paused.plan_history
            assert sim.work().execution_arguments == original
            assert sim.provider.execution_count(WORK_ID) == int(approved)
            if approved:
                assert result.state is AgentSessionState.COMPLETED
                assert sim.work().state is DistributedWorkState.COMMITTED
                assert sim.work().effect_verification["verdict"] == "MATCH"
            else:
                assert sim.work().state is not DistributedWorkState.COMMITTED
            assert_no_credential_on_disk(tmp_path)
            assert TOKEN not in json.dumps(sim.governance.store.operation_audit())

    asyncio.run(scenario())


@pytest.mark.integration
def test_real_revoked_store_after_effect_restart_does_not_resolve_or_replay(
    tmp_path, openbao_service, monkeypatch
):
    store, _, revoke, _ = openbao_service

    def configure(sim):
        sim.secret_backend = store
        sim.secret_handle = SecretHandle(vault_path=SECRET_HANDLE)
        sim.credential_broker = CredentialBroker(sim.governance, store)
        sim.firmware_handler.credential_broker = sim.credential_broker

    async def scenario():
        async with simulation(tmp_path / "runtime", single_connection=True) as first:
            configure(first)
            paused = await request_firmware(first, wait_timeout=3)
            approve_credential_firmware(first, paused)
            first.provider.inject_fault(
                STABLE, SimulationFault.EFFECT_THEN_RESPONSE_LOST
            )
            waiting = await resume_firmware(first, paused.session_id)
            await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == 1
            revoke()
        async with simulation(tmp_path / "runtime") as restored:
            configure(restored)

            def forbidden(handle):
                pytest.fail("Recovery attempted another mutation credential resolution")

            monkeypatch.setattr(store, "resolve", forbidden)
            completed = await resume_firmware(restored, paused.session_id)
            assert completed.state is AgentSessionState.COMPLETED
            assert completed.workflow_run_id == paused.workflow_run_id
            assert restored.work().state is DistributedWorkState.COMMITTED
            assert restored.work().effect_verification["verdict"] == "MATCH"
            assert restored.provider.execution_count(WORK_ID) == 1
            assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())


def test_ambient_netrc_identity_never_consulted(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Secret transport attempted ambient netrc identity")

    monkeypatch.setattr(requests.sessions, "get_netrc_auth", forbidden)
    observed = []

    def send(session, prepared, **kwargs):
        observed.append(prepared)
        assert session.trust_env is True
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(
            {"data": {"data": {"value": FAKE_CREDENTIAL}}}
        ).encode()
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    assert backend().resolve(SecretHandle(vault_path=SECRET_HANDLE)) == FAKE_CREDENTIAL
    assert "Authorization" not in observed[0].headers
    assert observed[0].headers["X-Vault-Token"] == TOKEN


def test_public_sdk_exports_canonical_backend():
    import sys

    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(root / "sdk/provider/python"), str(root))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'from nous_provider.interoperability import OpenBaoKv2SecretBackend; assert OpenBaoKv2SecretBackend.__name__ == "OpenBaoKv2SecretBackend"',
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout == ""


@pytest.mark.integration
def test_real_expired_store_token_cannot_deliver_again(openbao_service):
    _, endpoint, _, admin = openbao_service
    short_token = "apeir-openbao-test-expiring-token-127649"
    issued = admin(
        "POST",
        "auth/token/create",
        {
            "id": short_token,
            "policies": ["apeir-reader"],
            "no_default_policy": True,
            "ttl": "1s",
            "renewable": False,
        },
    )
    assert issued["auth"]["lease_duration"] == 1
    store = backend(endpoint, token=short_token)
    assert store.resolve(SecretHandle(vault_path=SECRET_HANDLE)) == FAKE_CREDENTIAL
    deadline = time.monotonic() + 5
    while True:
        try:
            store.resolve(SecretHandle(vault_path=SECRET_HANDLE))
        except PermissionError:
            break
        if time.monotonic() > deadline:
            pytest.fail("expired store token still delivered material")
        time.sleep(0.05)
    assert store.health()["verified_live"] is True

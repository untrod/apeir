"""OPA protocol/security contracts and optional real-service acceptance.

Set APEIR_OPA_TEST_IMAGE to an installed OPA image for the actual engine probe.
The fixture provisions only a local test service, never runtime authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from nous_runtime.agent import AgentSessionState
from nous_runtime.core.redaction import register_sensitive_value
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.operation_contracts import (
    GovernanceDecision,
    GovernanceRequest,
)
from nous_runtime.node_runtime.distributed_work import DistributedWorkState
from nous_runtime.provider.interoperability import OpaPolicyProvider
from tests.interoperability.test_external_agent import setup_agent
from tests.reality.test_simulated_execution import (
    SimulationFault,
    WORK_ID,
    STABLE,
    assert_no_credential_on_disk,
    approve_credential_firmware,
    request_firmware,
    resume_firmware,
    simulation,
    wait_for,
)

FAKE_SECRET = "apeir-opa-fixture-sensitive-material-726415"
OPA_REFERENCE_POLICY = """package apeir
import rego.v1

decision := {"authorization_id": input.authorization_id, "decision": verdict} if {
    input.schema == "apeir.opa-policy/v1"
}

verdict := "DENY" if {
    input.request.capability_inputs.risk == "CRITICAL"
} else := "REQUIRE_APPROVAL" if {
    input.request.capability_inputs.risk in {"MEDIUM", "HIGH"}
} else := "REQUIRE_APPROVAL" if {
    input.request.capability_inputs.risk in {"LOW", "READ_ONLY"}
    input.request.capability_inputs.side_effect_class in {"local_write", "external_write"}
} else := "ALLOW" if {
    input.request.capability_inputs.risk in {"LOW", "READ_ONLY"}
    input.request.capability_inputs.side_effect_class in {"none", "read_only"}
} else := "UNKNOWN"
"""


def request_facts():
    return GovernanceRequest(
        operation_id="work-policy",
        work_id="work-policy",
        capability_id="device.state.read",
        resource_id="device-policy",
        subject_id="agent-policy",
        node_id="node-policy",
        agent_session_id="session-policy",
        plan_id="plan-policy",
        workflow_run_id="run-policy",
        capability_inputs={"risk": "READ_ONLY", "side_effect_class": "read_only"},
    )


class Response:
    def __init__(self, body, *, status=200, content_type="application/json"):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


def stub_transport(monkeypatch, response):
    observed = []

    def request(session, method, url, **kwargs):
        observed.append((method, url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs.get("verify", True) is True
        assert "Authorization" not in kwargs["headers"]
        if isinstance(response, Exception):
            raise response
        return response(kwargs) if callable(response) else response

    monkeypatch.setattr(requests.Session, "request", request)
    return observed


@pytest.mark.parametrize("decision", list(GovernanceDecision))
def test_opa_decision_is_bound_to_exact_authorization_facts(monkeypatch, decision):
    request = request_facts()
    observed = stub_transport(
        monkeypatch,
        Response(
            {
                "result": {
                    "decision": decision.value,
                    "authorization_id": request.authorization_id,
                }
            }
        ),
    )
    provider = OpaPolicyProvider("http://127.0.0.1:8181")
    assert provider.evaluate(request) is decision
    assert observed[0][1].endswith("/v1/data/apeir/decision")
    assert observed[0][2]["json"]["input"]["request"] == request.to_dict()
    assert (
        observed[0][2]["json"]["input"]["authorization_id"] == request.authorization_id
    )
    assert provider.discover()["authority"] is False
    assert request.capability_inputs == {
        "risk": "READ_ONLY",
        "side_effect_class": "read_only",
    }


@pytest.mark.parametrize(
    "variant",
    [
        "wrong_operation",
        "missing_binding",
        "unbound_allow",
        "self_grant",
        "success_claim",
        "boolean",
        "undefined",
        "malformed",
        "oversize",
        "array",
        "content_type",
        "redirect",
        "http_failure",
        "timeout",
        "tls_failure",
    ],
)
def test_opa_invalid_or_unavailable_evidence_fails_closed(
    monkeypatch, caplog, capsys, variant
):
    register_sensitive_value(FAKE_SECRET)
    result = {"decision": "ALLOW", "authorization_id": request_facts().authorization_id}
    response = Response({"result": result})
    if variant == "wrong_operation":
        result["authorization_id"] = "gov_wrong_operation"
    elif variant == "missing_binding":
        result.pop("authorization_id")
    elif variant == "unbound_allow":
        response = Response({"result": "ALLOW"})
    elif variant == "self_grant":
        result["grant"] = {"authorized_by": "model"}
    elif variant == "success_claim":
        result["decision"] = "COMMITTED"
    elif variant == "boolean":
        result["decision"] = True
    elif variant == "undefined":
        response = Response({})
    elif variant == "malformed":
        response = Response(FAKE_SECRET.encode())
    elif variant == "oversize":
        response = Response(b'"' + b"x" * 70_000 + b'"')
    elif variant == "array":
        response = Response([result])
    elif variant == "content_type":
        response = Response({"result": result}, content_type="text/html")
    elif variant == "redirect":
        response = Response({"error": FAKE_SECRET}, status=302)
    elif variant == "http_failure":
        response = Response({"error": FAKE_SECRET}, status=503)
    elif variant == "timeout":
        response = requests.Timeout(FAKE_SECRET)
    elif variant == "tls_failure":
        response = requests.exceptions.SSLError(FAKE_SECRET)
    if variant in {
        "wrong_operation",
        "missing_binding",
        "self_grant",
        "success_claim",
        "boolean",
    }:
        response = Response({"result": result})
    stub_transport(monkeypatch, response)
    assert (
        OpaPolicyProvider("http://127.0.0.1:8181").evaluate(request_facts())
        is GovernanceDecision.UNKNOWN
    )
    captured = capsys.readouterr()
    assert FAKE_SECRET not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test",
        "https://owner:password@example.test",
        "file:///policy",
        "http://127.0.0.1/other",
        "https://example.test?token=opaque",
        "http://127.0.0.1#fragment",
        "http://127.0.0.1:opaque",
    ],
)
def test_opa_host_configuration_rejects_unsafe_origins(endpoint):
    with pytest.raises(ValueError):
        OpaPolicyProvider(endpoint)


@pytest.mark.parametrize(
    "path",
    ["../decision", "apeir//decision", "decision?allow=true", "decision#allow", ""],
)
def test_opa_work_cannot_select_an_unbound_policy_path(path):
    with pytest.raises(ValueError):
        OpaPolicyProvider("http://127.0.0.1", policy_path=path)


@pytest.mark.parametrize(
    "timeout", [0, -1, float("inf"), float("nan"), 11, FAKE_SECRET]
)
def test_opa_timeout_configuration_is_bounded_and_does_not_echo_material(timeout):
    with pytest.raises(ValueError) as rejected:
        OpaPolicyProvider("http://127.0.0.1", timeout_seconds=timeout)
    assert FAKE_SECRET not in str(rejected.value)


def test_opa_sensitive_input_never_leaves_the_boundary(monkeypatch):
    from dataclasses import replace

    register_sensitive_value(FAKE_SECRET)
    observed = stub_transport(monkeypatch, Response({"result": "ALLOW"}))
    request = replace(request_facts(), expected_effect={"value": FAKE_SECRET})
    assert (
        OpaPolicyProvider("http://127.0.0.1").evaluate(request)
        is GovernanceDecision.UNKNOWN
    )
    assert observed == []


@pytest.mark.parametrize("available", [True, False])
def test_opa_health_reports_actual_availability_without_error_body(
    monkeypatch, available
):
    stub_transport(
        monkeypatch,
        Response(
            {} if available else {"error": FAKE_SECRET},
            status=200 if available else 503,
        ),
    )
    health = OpaPolicyProvider("http://127.0.0.1").health()
    assert health["verified_live"] is available
    assert FAKE_SECRET not in json.dumps(health)


def test_opa_allow_is_not_authority_and_unknown_is_audited_without_leakage(
    tmp_path, monkeypatch
):
    observed = stub_transport(
        monkeypatch,
        lambda kwargs: Response(
            {
                "result": {
                    "decision": "ALLOW",
                    "authorization_id": kwargs["json"]["input"]["authorization_id"],
                }
            }
        ),
    )
    fixture = setup_agent(
        tmp_path,
        lambda *args: pytest.fail("unauthorized execution"),
        policy=OpaPolicyProvider("http://127.0.0.1"),
    )
    assert (
        fixture.gate.evaluate_operation(fixture.request.authorization_id)
        is GovernanceDecision.REQUIRE_APPROVAL
    )
    forged = AuthorizationContext(
        subject_type="user",
        subject_id="model",
        authn_method="human_session",
        authn_confidence=1.0,
    )
    with pytest.raises(PermissionError):
        fixture.gate.issue_operation_grant(fixture.request.authorization_id, forged)
    register_sensitive_value(FAKE_SECRET)
    stub_transport(monkeypatch, requests.Timeout(FAKE_SECRET))
    assert (
        fixture.gate.evaluate_operation(fixture.request.authorization_id)
        is GovernanceDecision.UNKNOWN
    )
    rows = fixture.gate.store.operation_audit()
    evidence = [
        json.loads(row["evidence_json"])
        for row in rows
        if row["event_type"] == "provider.policy.evaluated"
    ]
    assert evidence[-1]["verdict"] == "UNKNOWN"
    assert evidence[-1]["authorization_id"] == fixture.request.authorization_id
    assert evidence[-1]["policy_provider_type"].endswith(".OpaPolicyProvider")
    assert evidence[-1]["work_id"] == fixture.request.work_id
    assert evidence[-1]["node_id"] == fixture.request.node_id
    assert FAKE_SECRET not in json.dumps(rows)
    assert observed


@pytest.fixture
def opa_service(tmp_path):
    image = os.environ.get("APEIR_OPA_TEST_IMAGE")
    if not image:
        pytest.skip("explicit real OPA service acceptance image not configured")
    policy = tmp_path / "reference.rego"
    policy.write_text(OPA_REFERENCE_POLICY, encoding="utf-8")
    policy.chmod(0o644)
    engine = ["docker"]
    environment = dict(os.environ)
    if Path("/var/run/docker.sock").exists():
        engine.append("--host=unix:///var/run/docker.sock")
        for name in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environment.pop(name, None)

    def docker(*arguments):
        result = subprocess.run(
            [*engine, *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout.strip()

    container = docker(
        "run",
        "--detach",
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--publish=127.0.0.1::8181",
        image,
        "run",
        "--server",
        "--addr=0.0.0.0:8181",
    )
    try:
        inspect = json.loads(docker("inspect", container))[0]
        port = inspect["NetworkSettings"]["Ports"]["8181/tcp"][0]["HostPort"]
        endpoint = f"http://127.0.0.1:{port}"
        provider = OpaPolicyProvider(endpoint, timeout_seconds=0.5)
        deadline = time.monotonic() + 5
        while not provider.health()["verified_live"]:
            if time.monotonic() >= deadline:
                pytest.fail("actual OPA service did not become healthy")
            time.sleep(0.05)

        def set_policy(source):
            # Fixture-owned engine provisioning, not a Provider approval API.
            response = requests.put(
                endpoint + "/v1/policies/reference",
                data=source.encode(),
                headers={"Content-Type": "text/plain"},
                timeout=2,
                allow_redirects=False,
            )
            assert response.status_code == 200

        set_policy(policy.read_text(encoding="utf-8"))
        yield (
            provider,
            set_policy,
            lambda: docker("stop", "--time=1", container),
            lambda paused: docker("pause" if paused else "unpause", container),
        )
    finally:
        with contextlib.suppress(subprocess.CalledProcessError):
            docker("rm", "--force", container)


@pytest.mark.integration
def test_real_opa_engine_health_discovery_and_four_bound_decisions(opa_service):
    from dataclasses import replace

    provider, _, stop, _ = opa_service
    assert provider.health() == {"state": "healthy", "verified_live": True}
    for risk, effect, verdict in [
        ("READ_ONLY", "read_only", GovernanceDecision.ALLOW),
        ("HIGH", "external_write", GovernanceDecision.REQUIRE_APPROVAL),
        ("CRITICAL", "external_write", GovernanceDecision.DENY),
        ("unsupported", "unknown", GovernanceDecision.UNKNOWN),
    ]:
        request = replace(
            request_facts(),
            capability_inputs={"risk": risk, "side_effect_class": effect},
        )
        assert provider.evaluate(request) is verdict
    stop()
    assert provider.health()["state"] == "unavailable"
    assert provider.evaluate(request_facts()) is GovernanceDecision.UNKNOWN


@pytest.mark.integration
@pytest.mark.parametrize("deny_phase", ["none", "after_approval", "before_effect"])
def test_real_opa_governed_firmware_goal_keeps_authority_and_original_work(
    tmp_path,
    opa_service,
    monkeypatch,
    deny_phase,
):
    provider, set_policy, _, _ = opa_service

    async def scenario():
        async with simulation(tmp_path / "runtime", credentials=True) as sim:
            sim.governance.operation_policy_provider = provider
            paused = await request_firmware(sim)
            original = sim.work().to_dict()
            approve_credential_firmware(sim, paused)
            deny_after_approval = deny_phase != "none"

            def deny():
                set_policy("""package apeir
import rego.v1
decision := {"authorization_id": input.authorization_id, "decision": "DENY"}
""")

            if deny_phase == "after_approval":
                deny()
            elif deny_phase == "before_effect":
                original_resolve = sim.secret_backend.resolve

                def change_policy_after_resolution(handle):
                    value = original_resolve(handle)
                    deny()
                    return value

                monkeypatch.setattr(
                    sim.secret_backend, "resolve", change_policy_after_resolution
                )
            result = await resume_firmware(sim, paused.session_id)
            assert result.workflow_run_id == paused.workflow_run_id
            assert result.plan_history == paused.plan_history
            assert sim.work().execution_arguments == original["execution_arguments"]
            assert sim.provider.execution_count(WORK_ID) == (
                0 if deny_after_approval else 1
            )
            if deny_after_approval:
                assert result.state is not AgentSessionState.COMPLETED
                assert (
                    sim.provider.read_state(sim.device).data["state"][
                        "firmware_version"
                    ]
                    == "1.0.0"
                )
                assert sim.work().state is not DistributedWorkState.COMMITTED
            else:
                assert result.state is AgentSessionState.COMPLETED
                assert sim.work().state is DistributedWorkState.COMMITTED
                assert sim.work().effect_verification["verdict"] == "MATCH"
                assert (
                    sim.work().result_summary["remote_execution_receipt"][
                        "operation_id"
                    ]
                    == WORK_ID
                )
            evidence = [
                json.loads(row["evidence_json"])
                for row in sim.governance.store.operation_audit()
                if row["event_type"] == "provider.policy.evaluated"
            ]
            mutation = [row for row in evidence if row["operation_id"] == WORK_ID]
            assert mutation
            assert all(row["agent_session_id"] == paused.session_id for row in mutation)
            assert all(row["node_id"] == sim.node.identity.node_id for row in mutation)
            assert mutation[-1]["verdict"] == (
                "DENY" if deny_after_approval else "REQUIRE_APPROVAL"
            )
            if deny_phase == "before_effect":
                assert sim.work().state is DistributedWorkState.FAILED
                assert any(
                    json.loads(row["evidence_json"]).get("phase") == "before_effect"
                    for row in sim.governance.store.operation_audit()
                )
            assert_no_credential_on_disk(tmp_path)

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.parametrize("policy_pause", [False, True])
def test_real_opa_response_loss_restart_reconciles_without_repeating_effect(
    tmp_path, opa_service, policy_pause
):
    provider, _, _, pause_service = opa_service

    async def scenario():
        async with simulation(tmp_path / "runtime", single_connection=True) as first:
            first.governance.operation_policy_provider = provider
            first.provider.inject_fault(
                STABLE, SimulationFault.EFFECT_THEN_RESPONSE_LOST
            )
            paused = await first.execute(wait_timeout=3)
            await wait_for(first.client_task.done)
            assert paused.state is AgentSessionState.WAITING
            assert first.provider.execution_count(WORK_ID) == 1
            session_id = paused.session_id
        async with simulation(tmp_path / "runtime") as restored:
            restored.governance.operation_policy_provider = provider
            if policy_pause:
                pause_service(True)
                try:
                    blocked = await asyncio.to_thread(
                        restored.coordinator.resume_plan,
                        session_id,
                        handlers={"reality.operation": restored.handler},
                    )
                    assert blocked.state is AgentSessionState.WAITING
                    assert restored.work().state is DistributedWorkState.VERIFIED
                    assert restored.provider.execution_count(WORK_ID) == 1
                finally:
                    pause_service(False)
            result = await asyncio.to_thread(
                restored.coordinator.resume_plan,
                session_id,
                handlers={"reality.operation": restored.handler},
            )
            assert result.state is AgentSessionState.COMPLETED
            assert result.workflow_run_id == paused.workflow_run_id
            assert restored.work().state is DistributedWorkState.COMMITTED
            assert restored.work().effect_verification["verdict"] == "MATCH"
            assert restored.provider.execution_count(WORK_ID) == 1

    asyncio.run(scenario())


def test_opa_provider_is_available_through_public_sdk_without_internal_imports(
    tmp_path,
):
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(root / "sdk/provider/python"), str(root))
    )
    code = """from nous_provider.interoperability import OpaPolicyProvider, GovernanceRequest
provider = OpaPolicyProvider("http://127.0.0.1:8181")
assert provider.discover()["authority"] is False
assert "UNKNOWN" in provider.discover()["decisions"]
try:
    OpaPolicyProvider("http://untrusted.example.test")
except ValueError:
    print("public-sdk-contract-pass")
else:
    raise AssertionError("unsafe origin accepted through SDK")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "public-sdk-contract-pass"


@pytest.mark.parametrize("field", ["endpoint", "policy_path"])
def test_opa_configuration_material_cannot_leak_into_http_logging(
    monkeypatch, caplog, field
):
    register_sensitive_value(FAKE_SECRET)
    observed = stub_transport(monkeypatch, Response({}))
    configuration = {
        "endpoint": "https://example.test",
        "policy_path": "apeir/decision",
    }
    configuration[field] = (
        "https://" + FAKE_SECRET + ".example.test"
        if field == "endpoint"
        else FAKE_SECRET
    )
    with pytest.raises(ValueError) as rejected:
        OpaPolicyProvider(**configuration)
    assert FAKE_SECRET not in str(rejected.value) + caplog.text
    assert observed == []


def test_opa_never_reads_ambient_netrc_credentials(monkeypatch):
    request = request_facts()

    def netrc(*args, **kwargs):
        pytest.fail("policy transport attempted ambient credential resolution")

    def send(session, prepared, **kwargs):
        assert session.trust_env  # Preserve platform proxy/CA behavior.
        assert "Authorization" not in prepared.headers
        assert (
            json.loads(prepared.body)["input"]["authorization_id"]
            == request.authorization_id
        )
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(
            {
                "result": {
                    "decision": "ALLOW",
                    "authorization_id": request.authorization_id,
                }
            }
        ).encode()
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.sessions, "get_netrc_auth", netrc)
    monkeypatch.setattr(requests.Session, "send", send)
    assert (
        OpaPolicyProvider("https://opa.example.test").evaluate(request)
        is GovernanceDecision.ALLOW
    )

"""Bounded diagnostic only; no production Ray provider acceptance claim."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from nous_runtime.agents.external.models import AgentDescriptor
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.node_runtime.service import (
    NodeRuntimeConfig,
    NodeRuntimeService,
    WorkloadResponseLost,
)
from nous_runtime.planner.observation import Observation
from scripts.ci.ray_bounded_diagnostic import (
    RayBoundedDiagnostic,
    RayDiagnosticProfile,
    summarize_samples,
)
from tests.interoperability.test_external_agent import approve, execute, setup_agent

IMAGE = "sha256:" + "1" * 64


@pytest.mark.parametrize("value", [0, 63, 257, -1, True, 224.0, "224"])
def test_diagnostic_profile_cannot_request_unbounded_resources(value):
    with pytest.raises(ValueError):
        RayDiagnosticProfile(IMAGE, value, True)


@pytest.mark.parametrize(
    "image", ["ray:latest", "", "sha256:abc", "https://example.test/image"]
)
def test_diagnostic_image_is_an_immutable_local_reference(image):
    with pytest.raises(ValueError):
        RayDiagnosticProfile(image, 224, True)


def test_exception_is_explicit_and_does_not_change_default():
    assert RayDiagnosticProfile(IMAGE).pids == 64
    with pytest.raises(PermissionError):
        RayDiagnosticProfile(IMAGE, 224)
    assert RayDiagnosticProfile(IMAGE, 224, True).to_dict()["diagnostic_only"] is True


def test_profile_is_immutable_and_binds_all_containment():
    profile = RayDiagnosticProfile(IMAGE, 224, True)
    altered = profile.to_dict()
    altered["pids"] = 256
    assert profile.to_dict()["pids"] == 224
    assert profile.to_dict()["memory_limit_mb"] == 2048
    assert profile.to_dict()["network"] == "none"
    assert profile.to_dict()["timeout_seconds"] == 45
    with pytest.raises(AttributeError):
        profile.pids = 256


def test_mismatched_profile_is_rejected_before_container_create(tmp_path, monkeypatch):
    probe = RayBoundedDiagnostic(tmp_path, RayDiagnosticProfile(IMAGE, 224, True))
    monkeypatch.setattr(
        probe.provider, "prepare", lambda *a: pytest.fail("wrong profile admitted")
    )
    with pytest.raises(PermissionError, match="original governed"):
        probe.run(expected_profile=replace(probe.profile, pids=256).to_dict())


def test_uncertain_prior_effect_is_never_replayed(tmp_path):
    probe = RayBoundedDiagnostic(tmp_path, RayDiagnosticProfile(IMAGE, 224, True))
    (probe.workspace / "count.txt").write_text("1")
    with pytest.raises(PermissionError, match="replay"):
        probe.run()
    (probe.workspace / "count.txt").unlink()
    (probe.workspace / "mode.json").write_text('"execute"')
    restored = RayBoundedDiagnostic(tmp_path, probe.profile)
    with pytest.raises(PermissionError, match="replay"):
        restored.run()


def test_partial_create_failure_still_cleans_the_owned_container(tmp_path, monkeypatch):
    from types import SimpleNamespace

    probe = RayBoundedDiagnostic(tmp_path, RayDiagnosticProfile(IMAGE, 224, True))
    probe.provider._engine = "docker"  # Contract fixture; never invokes an engine.
    destroyed = []

    def create(*args):
        raise RuntimeError("deterministic partial create failure")

    monkeypatch.setattr(probe.provider, "prepare", create)
    monkeypatch.setattr(
        probe.provider, "destroy", lambda environment, handle: destroyed.append(handle)
    )
    monkeypatch.setattr(
        probe,
        "_docker",
        lambda *a: SimpleNamespace(returncode=1, stdout="", stderr="No such container"),
    )
    with pytest.raises(RuntimeError, match="partial create"):
        probe.run()
    assert destroyed == [probe.handle]
    assert probe.report["cleanup"]["container_absent"]
    assert probe.report["cleanup"]["default_pids_after"] == 64


def test_metric_summary_uses_cgroup_cpu_and_memory():
    rows = [
        {
            "phase": "steady",
            "t": t,
            "cpu_usage_usec": cpu,
            "processes": 10,
            "threads": 207,
            "pids_current": 207,
            "pids_peak": 208,
            "memory_current": 400,
            "memory_peak": 500,
            "names": {"raylet": 1},
        }
        for t, cpu in [(1, 100), (3, 1000100)]
    ]
    result = summarize_samples(rows)["steady"]
    assert result["cpu_mean_cores"] == 0.5
    assert result["cpu_peak_sample_cores"] == 0.5
    assert result["peaks"]["memory_peak"] == 500
    assert result["peaks"]["pids_peak"] == 208
    assert result["peak_topology"] == {"raylet": 1}


def governed_probe(root, profile, *, mode="execute", lost=False):
    diagnostic = RayBoundedDiagnostic(root, profile)
    calls = []
    descriptor = AgentDescriptor(
        agent_id="ray-diagnostic",
        executable_reference="diagnostic-only",
        default_timeout_ms=45000,
        metadata={"execution_profile": profile.to_dict()},
    )

    def runner(argv, environment, cwd, timeout):
        # Registered host profile, not model-provided environment or executable.
        assert timeout <= 45000
        assert argv[0] == "diagnostic-only"
        assert Path(cwd).resolve() == diagnostic.workspace
        assert json.loads(Path(argv[-1]).read_text())["agent_id"] == "ray-diagnostic"
        calls.append("invoke")
        result = diagnostic.run(
            mode,
            expected_profile=fixture.handler._descriptor.metadata["execution_profile"],
        )
        if lost:
            assert result.ok
            evidence = json.loads(
                (diagnostic.workspace / "task-evidence.json").read_text()
            )
            raise WorkloadResponseLost(
                "fake diagnostic ACK loss after effect",
                output={"ray_task": evidence},
                completed=True,
            )
        return result

    fixture = setup_agent(root, runner, descriptor=descriptor)
    assert fixture.request.resource_id.endswith(
        fixture.handler.discover()["descriptor_digest"]
    )
    return fixture, diagnostic, calls


@pytest.mark.parametrize("changed", ["pids", "image"])
def test_approval_cannot_admit_a_changed_host_profile(tmp_path, changed):
    fixture, diagnostic, calls = governed_probe(
        tmp_path, RayDiagnosticProfile(IMAGE, 224, True)
    )
    approve(fixture)
    diagnostic.profile = replace(
        diagnostic.profile,
        **({"pids": 256} if changed == "pids" else {"image": "sha256:" + "2" * 64}),
    )
    assert execute(fixture)["state"] == "FAILED"
    assert not diagnostic.handle
    assert calls == ["invoke"]


@pytest.mark.parametrize(
    "subject", ["model", "agent", "planner", "node", "provider", "scheduler"]
)
def test_profile_never_grants_self_authority(tmp_path, subject):
    fixture, diagnostic, calls = governed_probe(
        tmp_path, RayDiagnosticProfile(IMAGE, 224, True)
    )
    broker = ApprovalBroker(fixture.gate.store)
    approval = broker.request_operation(
        fixture.request.authorization_id, gate=fixture.gate
    )
    with pytest.raises(PermissionError):
        broker.approve_operation_once(
            approval.request_id,
            AuthorizationContext(
                subject_type=subject, subject_id="not-human", authn_confidence=1.0
            ),
            gate=fixture.gate,
        )
    assert execute(fixture)["state"] == "FAILED"
    assert calls == []
    assert not diagnostic.handle


@pytest.mark.parametrize("decision", ["deny", "revoke"])
def test_governance_rejects_profile_operation_before_any_engine_use(tmp_path, decision):
    fixture, diagnostic, calls = governed_probe(
        tmp_path, RayDiagnosticProfile(IMAGE, 224, True)
    )
    broker = ApprovalBroker(fixture.gate.store)
    approval = broker.request_operation(
        fixture.request.authorization_id, gate=fixture.gate
    )
    if decision == "deny":
        broker.deny_operation(approval.request_id, _build_context(), gate=fixture.gate)
    else:
        approve(fixture)
        fixture.gate.interrupt_operation(
            fixture.request.authorization_id, _build_context()
        )
    assert execute(fixture)["state"] == "FAILED"
    assert calls == []
    assert not diagnostic.handle


@pytest.fixture
def real_image():
    image = os.environ.get("APEIR_RAY_DIAGNOSTIC_IMAGE")
    if not image:
        pytest.skip(
            "explicit local bounded diagnostic image not configured; no Ray Gate PASS"
        )
    return image


def assert_cleanup(diagnostic):
    cleanup = diagnostic.report["cleanup"]
    assert cleanup["container_absent"]
    assert cleanup["remaining_host_processes"] == []
    assert cleanup["default_pids_after"] == 64
    limits = diagnostic.report["limits"]
    assert limits["PidsLimit"] == diagnostic.profile.pids
    assert limits["Memory"] == 2048 * 1024 * 1024
    assert limits["NanoCpus"] == 1_000_000_000
    assert limits["ReadonlyRootfs"] and not limits["Privileged"]
    assert limits["NetworkMode"] == "none"
    assert limits["PidMode"] == ""
    assert limits["CapDrop"] == ["ALL"]
    assert limits["SecurityOpt"] == ["no-new-privileges"]
    assert diagnostic.report["uid"] == "65532:65532"
    assert diagnostic.report["final_cgroup"]["pids.peak"] <= diagnostic.profile.pids
    assert diagnostic.report["final_cgroup"]["memory.peak"] <= 2048 * 1024 * 1024
    if diagnostic.report["mode"] == "cancel":
        assert diagnostic.report["cancel_destroy_seconds"] >= 0
    for directory in (diagnostic.workspace / "ray-state").rglob("*"):
        if directory.is_dir() and not directory.is_symlink():
            assert os.access(directory, os.W_OK), (
                "guest-owned fake evidence must be removable by host"
            )
    assert (
        max(s["peaks"]["pids_peak"] for s in diagnostic.report["measurements"].values())
        <= diagnostic.profile.pids
    )


@pytest.mark.integration
@pytest.mark.parametrize("lost", [False, True])
def test_actual_task_evidence_and_lost_response_restart_never_replay(
    tmp_path, real_image, lost
):
    fixture, diagnostic, calls = governed_probe(
        tmp_path,
        RayDiagnosticProfile(
            real_image, int(os.environ.get("APEIR_RAY_DIAGNOSTIC_PIDS", "224")), True
        ),
        lost=lost,
    )
    approve(fixture)
    if lost:
        with pytest.raises(WorkloadResponseLost):
            execute(fixture)
    else:
        original = execute(fixture)
        assert original["state"] == "COMPLETED"
        assert original["output"]["effect_verified"] is False
        assert original["output"]["result_artifact"].startswith("artifact://sha256/")
    # Restart reloads the canonical Node journal; a still-valid prior grant cannot
    # cause another invocation. Observe the file independently of provider output.
    fixture.node = NodeRuntimeService(
        NodeRuntimeConfig(tmp_path / "node"),
        capability_handlers={fixture.handler.capability_id: fixture.handler},
    )
    reconciled = execute(fixture)
    assert reconciled["state"] == "COMPLETED"
    if lost:
        assert reconciled["error_code"] == "NOUS_NODE_RESPONSE_LOST"
    evidence = json.loads((diagnostic.workspace / "task-evidence.json").read_text())
    assert all(evidence[k] for k in ("task_id", "worker_id", "node_id"))
    observed = Observation(
        tool="diagnostic.counter.observe",
        data={"counter": int((diagnostic.workspace / "count.txt").read_text())},
        metadata={
            "resource_id": fixture.request.resource_id,
            "operation_id": fixture.request.operation_id,
            "independent": True,
        },
    )
    assert observed.data["counter"] == 1
    assert calls == ["invoke"]
    assert_cleanup(diagnostic)
    with pytest.raises(PermissionError, match="replay"):
        diagnostic.run()


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["failure", "cancel"])
def test_actual_error_and_cancellation_preserve_uncertain_effect_and_cleanup(
    tmp_path, real_image, mode
):
    fixture, diagnostic, calls = governed_probe(
        tmp_path,
        RayDiagnosticProfile(
            real_image, int(os.environ.get("APEIR_RAY_DIAGNOSTIC_PIDS", "224")), True
        ),
        mode=mode,
    )
    approve(fixture)
    result = execute(fixture)
    assert result["state"] == "FAILED"
    assert (diagnostic.workspace / "count.txt").read_text() == "1"
    # Cancellation/failure is not proof that no effect occurred; no implicit Ray
    # retry and canonical duplicate delivery returns the same terminal evidence.
    assert execute(fixture) == result
    assert calls == ["invoke"]
    assert_cleanup(diagnostic)

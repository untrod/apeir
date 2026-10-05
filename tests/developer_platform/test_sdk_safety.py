"""Public SDK packaging and execution-free conformance regressions."""

from pathlib import Path
import importlib

import pytest

from nous_runtime.cli.ctk import (
    CTKRunner,
    ConformanceLevel,
    ConformanceSuite,
    TestCase as Case,
    TestResult as Result,
    TestStatus as Status,
)
from nous_runtime.provider.sdk import (
    ProviderAdapter,
    ProviderManifest,
    ConformanceTestSuite,
)


class NonExecutingAdapter(ProviderAdapter):
    calls = 0

    @property
    def manifest(self):
        return ProviderManifest(
            provider_id="fixture",
            provider_name="fixture",
            capabilities=["model.stream"],
        )

    def invoke(self, capability_id, **params):
        self.calls += 1
        raise AssertionError("Conformance must not execute an adapter directly")

    def health(self):
        return {"status": "ok"}


def test_metadata_validation_and_unconfigured_conformance_never_execute():
    adapter = NonExecutingAdapter()
    assert adapter.validate().ok
    results = ConformanceTestSuite(adapter).run_all()
    assert results["test_manifest_valid"]
    assert not results["test_invoke_returns_dict"]
    assert not results["test_error_response_format"]
    assert not results["test_stream_yields_dicts"]
    assert adapter.calls == 0


def test_required_skip_cannot_be_hidden_by_optional_pass():
    runner = CTKRunner(ConformanceLevel.RUNNABLE)
    runner.suites["regression"] = ConformanceSuite(
        "regression",
        "execution",
        "1",
        tests=[
            Case(
                "required",
                "unconfigured target",
                ConformanceLevel.RUNNABLE,
                "execution",
            ),
            Case(
                "optional",
                "optional probe",
                ConformanceLevel.RUNNABLE,
                "execution",
                required=False,
                fn=lambda: Result("optional", Status.PASS),
            ),
        ],
    )
    result = runner.run_suite("regression")
    assert result.passed == 1 and result.skipped == 1
    assert not result.certified


def test_public_sdk_reexports_authoritative_types(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "sdk/provider/python")
    )
    sdk = importlib.import_module("nous_provider.runtime")
    from nous_runtime.node_runtime.distributed_work import DistributedWork
    from nous_runtime.reality.contracts import Device

    assert sdk.DistributedWork is DistributedWork
    assert sdk.ManagedDevice is Device
    assert importlib.import_module("nous_provider").Device is not Device
    with pytest.raises(ValueError, match="schema"):
        sdk.DistributedWork.from_dict({"schema": "unknown/v9"})
    assert sdk.NODE_PROTOCOL_VERSION == "1.0"


def test_runtime_suites_missing_targets_do_not_certify():
    from nous_runtime.provider.runtime_conformance import (
        RuntimeConformanceTarget,
        register_runtime_suites,
    )

    runner = CTKRunner()
    assert len(runner.suites) == 5
    register_runtime_suites(runner, RuntimeConformanceTarget())
    results = runner.run_required(
        [
            f"runtime-{name}"
            for name in (
                "work",
                "node",
                "device",
                "provider",
                "capability",
                "execution",
                "evidence",
            )
        ]
    )
    assert len(results) == 7
    assert all(
        result.skipped == 1 and not result.certified for result in results.values()
    )


@pytest.mark.parametrize("version", ["", "0.9", "2.0", "1.0.0"])
def test_public_node_protocol_rejects_unsupported_versions(monkeypatch, version):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "sdk/provider/python")
    )
    from nous_provider.runtime import NodeProtocolEnvelope, NodeProtocolError

    envelope = NodeProtocolEnvelope(
        "ACK",
        "node",
        "controller",
        1,
        payload={"acknowledged": "message"},
        protocol_version=version,
    )
    with pytest.raises(NodeProtocolError, match="version"):
        envelope.validate()


def test_runtime_contract_suites_inspect_real_contracts_without_execution(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from nous_runtime.provider.runtime_conformance import (
        RuntimeConformanceTarget,
        register_runtime_suites,
    )
    from nous_runtime.node_runtime.distributed_work import DistributedWork
    from nous_runtime.node_runtime.protocol import NodeProtocolEnvelope
    from nous_runtime.reality.contracts import Device, DeviceLifecycle
    from nous_runtime.capability.contract import CapabilityContract
    from nous_runtime.artifact.content_store import ContentAddressedArtifactStore

    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    artifact = store.store_bytes(
        b"conformance evidence", name="fixture", artifact_type="file"
    )
    key = Ed25519PrivateKey.generate()
    envelope = NodeProtocolEnvelope(
        "ACK", "node", "controller", 1, payload={"acknowledged": "message"}
    ).sign(key)
    target = RuntimeConformanceTarget(
        work=DistributedWork(intent="Inspect resource"),
        node_envelope=envelope,
        node_public_key=key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex(),
        device=Device(
            "device",
            "fixture",
            "stable",
            "simulated",
            lifecycle=DeviceLifecycle.REVOKED,
        ),
        provider=NonExecutingAdapter(),
        capability=CapabilityContract(
            capability_id="read", risk_level="LOW", side_effect_class="read_only"
        ),
        artifact_store=store,
        artifact_digest=artifact["artifact"]["digest"],
    )
    runner = CTKRunner()
    register_runtime_suites(runner, target)
    names = ("work", "node", "device", "provider", "capability", "evidence")
    assert all(runner.run_suite(f"runtime-{name}").certified for name in names)
    assert target.provider.calls == 0
    envelope.signature = "00" * 64
    assert not runner.run_suite("runtime-node").certified
    store.resolve(artifact["artifact"]["digest"]).write_bytes(b"tampered")
    assert not runner.run_suite("runtime-evidence").certified


def test_manifest_roundtrip_preserves_credential_and_compatibility_declarations():
    manifest = ProviderManifest(
        provider_id="fixture",
        requires_credential=False,
        requires_network=False,
        credential_type="none",
        rate_limit_per_minute=12,
        homepage="https://example.org",
    )
    restored = ProviderManifest.from_dict(manifest.to_dict())
    assert restored.to_dict() == manifest.to_dict()
    assert not restored.requires_credential and not restored.requires_network
    with pytest.raises(ValueError):
        ProviderManifest.from_dict({"compatibility": "unknown"})


def test_conformance_result_cannot_impersonate_another_probe():
    runner = CTKRunner()
    runner.suites["binding"] = ConformanceSuite(
        "binding",
        "provider",
        "1",
        tests=[
            Case(
                "required",
                "bound result",
                ConformanceLevel.DISCOVERABLE,
                "security",
                fn=lambda: Result("different-test", Status.PASS),
            ),
        ],
    )
    result = runner.run_suite("binding")
    assert result.errors == 1 and not result.certified


def test_optimized_python_cannot_disable_fail_closed_contract_checks():
    import subprocess
    import sys

    code = """
from nous_runtime.cli.ctk import CTKRunner
from nous_runtime.provider.runtime_conformance import RuntimeConformanceTarget, register_runtime_suites
from nous_runtime.capability.contract import CapabilityContract
runner = CTKRunner()
register_runtime_suites(runner, RuntimeConformanceTarget(capability=CapabilityContract(capability_id='unsafe', risk_level='UNKNOWN', side_effect_class='read_only')))
result = runner.run_suite('runtime-capability')
if result.certified or result.failed != 1:
    raise RuntimeError('UNKNOWN must fail closed with optimized Python')
"""
    subprocess.run([sys.executable, "-O", "-c", code], check=True, capture_output=True)


def test_duplicate_conformance_probe_names_cannot_hide_a_failure():
    runner = CTKRunner()
    runner.suites["duplicate"] = ConformanceSuite(
        "duplicate",
        "provider",
        "1",
        tests=[
            Case(
                "same",
                "failed probe",
                ConformanceLevel.DISCOVERABLE,
                "security",
                fn=lambda: Result("same", Status.FAIL),
            ),
            Case(
                "same",
                "passing probe",
                ConformanceLevel.DISCOVERABLE,
                "security",
                fn=lambda: Result("same", Status.PASS),
            ),
        ],
    )
    result = runner.run_suite("duplicate")
    assert result.errors == 1 and not result.certified

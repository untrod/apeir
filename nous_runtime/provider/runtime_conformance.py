"""Opt-in Distribution conformance suites using the existing CTK.

Contract probes inspect supplied canonical records and never execute Operations.
The execution target is persisted evidence from an already governed run. A report
certifies only the named contracts at its reported validation level, not hardware,
performance, enrollment, or production readiness.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.capability.contract import CapabilityContract
from nous_runtime.cli.ctk import (
    CTKRunner,
    ConformanceLevel,
    ConformanceSuite,
    TestCase,
    TestResult,
    TestStatus,
)
from nous_runtime.node_runtime.distributed_work import DistributedWork
from nous_runtime.node_runtime.protocol import NodeProtocolEnvelope
from nous_runtime.planner.observation import Observation
from nous_runtime.reality.verification import EffectVerifier
from nous_runtime.provider.sdk import ProviderAdapter
from nous_runtime.reality.contracts import Device, EffectVerification, Operation


@dataclass(frozen=True)
class RuntimeConformanceTarget:
    """Host-supplied test records, never an authority or a provider executor."""

    work: DistributedWork | None = None
    node_envelope: NodeProtocolEnvelope | None = None
    node_public_key: str = ""
    device: Device | None = None
    provider: ProviderAdapter | None = None
    capability: CapabilityContract | None = None
    operation: Operation | None = None
    receipt: dict[str, Any] | None = None
    verification: EffectVerification | None = None
    observations: tuple[Observation, ...] = ()
    artifact_store: ContentAddressedArtifactStore | None = None
    artifact_digest: str = ""


def register_runtime_suites(
    runner: CTKRunner, target: RuntimeConformanceTarget
) -> None:
    """Add seven target-backed suites without changing the legacy CTK defaults."""

    def work() -> None:
        if target.work is None:
            raise AssertionError("Runtime contract check failed")
        restored = DistributedWork.from_dict(target.work.to_dict())
        if restored.work_id != target.work.work_id:
            raise AssertionError("Runtime contract check failed")
        policy = restored.execution_policy
        if not policy.require_receipt:
            raise AssertionError("Work must require execution evidence")
        if restored.expected_effect:
            if not policy.retry_disabled:
                raise AssertionError("uncertain effects cannot be blindly retried")
            if not policy.require_effect_verification:
                raise AssertionError("mutation requires verification")

    def node() -> None:
        if target.node_envelope is None:
            raise AssertionError("Runtime contract check failed")
        target.node_envelope.validate()
        if not target.node_envelope.verify(target.node_public_key):
            raise AssertionError("invalid Node signature")

    def device() -> None:
        if target.device is None:
            raise AssertionError("Runtime contract check failed")
        restored = Device.from_dict(target.device.to_dict())
        if not (restored.device_id and restored.stable_identity):
            raise AssertionError("Runtime contract check failed")
        if restored.device_id != target.device.device_id:
            raise AssertionError("Runtime contract check failed")
        if restored.lifecycle != target.device.lifecycle:
            raise AssertionError("Runtime contract check failed")

    def provider() -> None:
        if target.provider is None:
            raise AssertionError("Runtime contract check failed")
        target.provider.validate().unwrap()
        manifest = target.provider.manifest
        if not manifest.version:
            raise AssertionError("Runtime contract check failed")
        if manifest.from_dict(manifest.to_dict()).to_dict() != manifest.to_dict():
            raise AssertionError("Runtime contract check failed")

    def capability() -> None:
        if target.capability is None:
            raise AssertionError("Runtime contract check failed")
        value = target.capability
        if not value.capability_id:
            raise AssertionError("Runtime contract check failed")
        if value.risk_level not in {"READ_ONLY", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise AssertionError("Runtime contract check failed")
        if value.side_effect_class not in {
            "read_only",
            "local_write",
            "external_write",
            "destructive",
        }:
            raise AssertionError("Runtime contract check failed")
        if value.timeout_seconds <= 0:
            raise AssertionError("Runtime contract check failed")
        if not (value.idempotency.value and value.verification_method.value):
            raise AssertionError("Runtime contract check failed")

    def execution() -> None:
        if not (target.operation is not None and target.receipt is not None):
            raise AssertionError("Runtime contract check failed")
        if not (target.work is not None and target.verification is not None):
            raise AssertionError("Runtime contract check failed")
        operation, receipt, verification = (
            target.operation,
            target.receipt,
            target.verification,
        )
        if operation.work_id != target.work.work_id:
            raise AssertionError("Runtime contract check failed")
        if receipt.get("operation_id") != operation.operation_id:
            raise AssertionError("Runtime contract check failed")
        if verification.operation_id != operation.operation_id:
            raise AssertionError("Runtime contract check failed")
        if verification.receipt_operation_id != operation.operation_id:
            raise AssertionError("Runtime contract check failed")
        if verification.work_id != operation.work_id:
            raise AssertionError("Runtime contract check failed")
        if verification.device_id != operation.target_resource_id:
            raise AssertionError("Runtime contract check failed")
        if not verification.observation_ids:
            raise AssertionError("receipt alone cannot establish an effect")
        if not verification.committable:
            raise AssertionError("UNKNOWN or MISMATCH cannot certify execution")
        checked = EffectVerifier().verify(operation, receipt, target.observations)
        if not checked.committable:
            raise AssertionError("independent evidence does not establish MATCH")
        if checked.observation_ids != verification.observation_ids:
            raise AssertionError("Runtime contract check failed")
        if checked.receipt_digest != verification.receipt_digest:
            raise AssertionError("Runtime contract check failed")

    def evidence() -> None:
        if target.artifact_store is None:
            raise AssertionError("Runtime contract check failed")
        if target.artifact_store.get(target.artifact_digest) is None:
            raise AssertionError("Runtime contract check failed")
        if not target.artifact_store.verify(target.artifact_digest):
            raise AssertionError("artifact integrity failure")

    probes = {
        "work": (target.work is not None, work),
        "node": (
            target.node_envelope is not None and bool(target.node_public_key),
            node,
        ),
        "device": (target.device is not None, device),
        "provider": (target.provider is not None, provider),
        "capability": (target.capability is not None, capability),
        "execution": (
            all(
                (
                    item is not None
                    for item in (
                        target.work,
                        target.operation,
                        target.receipt,
                        target.verification,
                    )
                )
            ),
            execution,
        ),
        "evidence": (
            target.artifact_store is not None and bool(target.artifact_digest),
            evidence,
        ),
    }
    for name, (configured, probe) in probes.items():

        def run(name=name, configured=configured, probe=probe):
            if not configured:
                return TestResult(
                    name,
                    TestStatus.SKIP,
                    detail="Runtime test target is not configured",
                )
            try:
                probe()
            except (AssertionError, ValueError) as exc:
                return TestResult(name, TestStatus.FAIL, detail=str(exc))
            return TestResult(
                name,
                TestStatus.PASS,
                evidence={"validation_level": "contract", "execution_performed": False},
            )

        runner.suites[f"runtime-{name}"] = ConformanceSuite(
            f"apeir-{name}/v1",
            name,
            "1.0",
            tests=[
                TestCase(
                    name,
                    f"Canonical {name} contract",
                    ConformanceLevel.DISCOVERABLE,
                    "execution" if name == "execution" else "security",
                    fn=run,
                )
            ],
        )

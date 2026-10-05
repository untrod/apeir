from __future__ import annotations

from dataclasses import replace

import pytest

from nous_runtime.capability.contract import (
    CapabilityContract,
    Idempotency,
    VerificationMethod,
)
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.planner.observation import Observation
from nous_runtime.reality import (
    Capability,
    DeviceDiscovery,
    DeviceLifecycle,
    DeviceRegistry,
    EffectVerdict,
    EffectVerifier,
    Node,
    Operation,
    RelationKind,
    ResourceGraph,
    ResourceKind,
    SimulatedDeviceProvider,
)


def _node() -> NodeIdentity:
    return NodeIdentity(
        node_id="node_test",
        node_name="test-node",
        node_role="personal_node",
        platform_os="linux",
        platform_os_version="test",
        platform_arch="aarch64",
        platform_hostname="test-host",
        public_key="ab" * 32,
    )


def _provider() -> SimulatedDeviceProvider:
    return SimulatedDeviceProvider(
        {
            "sim-sensor-001": {
                "device_type": "temperature-sensor",
                "capabilities": ["device.state.read"],
                "state": {"temperature_c": 24.5, "healthy": True},
            }
        }
    )


def test_reality_reuses_authoritative_node_capability_and_observation() -> None:
    assert Node is NodeIdentity
    assert Capability is CapabilityContract
    assert Observation.__module__ == "nous_runtime.planner.observation"


def test_capability_2_fields_are_additive_and_compatible() -> None:
    contract = CapabilityContract(
        capability_id="device.state.read",
        risk_level="low",
        side_effect_class="read_only",
        idempotency=Idempotency.IDEMPOTENT,
        observation_method="provider.read_state",
        verification_method=VerificationMethod.ASSERTION,
    )
    value = contract.to_dict()
    assert contract.risk == "low"
    assert value["risk"] == value["risk_level"] == "low"
    assert value["side_effect_class"] == "read_only"
    assert value["observation_method"] == "provider.read_state"
    assert value["idempotency"] == "idempotent"


def test_device_registry_enforces_lifecycle_and_persists(tmp_path) -> None:
    provider = _provider()
    registry = DeviceRegistry(tmp_path)
    device = provider.register_discovered(registry)[0]
    assert device.lifecycle is DeviceLifecycle.IDENTIFIED

    trusted = registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
    available = registry.transition(trusted.device_id, DeviceLifecycle.AVAILABLE)
    assert available.lifecycle is DeviceLifecycle.AVAILABLE

    restored = DeviceRegistry(tmp_path).get(device.device_id)
    assert restored is not None
    assert restored.lifecycle is DeviceLifecycle.AVAILABLE

    registry.transition(device.device_id, DeviceLifecycle.REVOKED)
    with pytest.raises(ValueError, match="invalid device transition"):
        registry.transition(device.device_id, DeviceLifecycle.AVAILABLE)


def test_rediscovery_does_not_reduce_trust_or_resurrect_revoked_device(
    tmp_path,
) -> None:
    provider = _provider()
    registry = DeviceRegistry(tmp_path)
    device = provider.register_discovered(registry)[0]
    registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
    registry.transition(device.device_id, DeviceLifecycle.AVAILABLE)
    assert (
        provider.register_discovered(registry)[0].lifecycle is DeviceLifecycle.AVAILABLE
    )
    registry.transition(device.device_id, DeviceLifecycle.REVOKED)
    assert (
        provider.register_discovered(registry)[0].lifecycle is DeviceLifecycle.REVOKED
    )


def test_device_identity_does_not_depend_on_transport_locator() -> None:
    provider = _provider()
    original = provider.discover()[0]
    moved = DeviceDiscovery(
        provider_id=original.provider_id,
        locator="simulated://different-port",
        hints=original.hints,
    )
    assert provider.identify(original).device_id == provider.identify(moved).device_id


def test_resource_graph_persists_typed_relations(tmp_path) -> None:
    provider = _provider()
    device = provider.identify(provider.discover()[0])
    capability = CapabilityContract(capability_id="device.state.read")
    observation = provider.read_state(device)

    graph = ResourceGraph(tmp_path)
    graph.add_node(_node())
    graph.add_device(replace(device, node_id="node_test"))
    graph.add_transport(provider.transport.descriptor)
    graph.add_capability(capability)
    graph.add_observation(observation)
    graph.relate("node_test", RelationKind.HOSTS, device.device_id)
    graph.relate(device.device_id, RelationKind.CONNECTED_TO, "simulated-default")
    graph.relate(device.device_id, RelationKind.EXPOSES, "device.state.read")
    graph.relate(device.device_id, RelationKind.OBSERVED_BY, observation.observation_id)

    restored = ResourceGraph(tmp_path)
    assert len(restored.list()) == 5
    assert len(restored.relations(resource_id=device.device_id)) == 4
    assert restored.get("node_test").kind is ResourceKind.NODE

    with pytest.raises(ValueError, match="invalid HOSTS"):
        restored.relate(device.device_id, RelationKind.HOSTS, "node_test")


def test_simulated_provider_discover_identify_register_and_read(tmp_path) -> None:
    provider = _provider()
    registry = DeviceRegistry(tmp_path)
    device = provider.register_discovered(registry)[0]
    registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
    device = registry.transition(device.device_id, DeviceLifecycle.AVAILABLE)
    observation = provider.read_state(device)

    assert observation.status == "success"
    assert observation.data["state"] == {"temperature_c": 24.5, "healthy": True}
    assert observation.metadata["device_id"] == device.device_id


def test_effect_verification_matches_receipt_and_observed_reality() -> None:
    provider = _provider()
    device = provider.identify(provider.discover()[0])
    operation = Operation(
        operation_id="op_read_sensor",
        work_id="work_existing",
        capability_id="device.state.read",
        target_resource_id=device.device_id,
        expected_effect={"healthy": True},
    )
    receipt = {
        "schema": "nous.operation-receipt/v1",
        "operation_id": operation.operation_id,
        "result": "COMPLETED",
        "effect_digest": "ab" * 32,
    }
    verification = EffectVerifier().verify(
        operation, receipt, [provider.read_state(device)]
    )
    assert verification.verdict is EffectVerdict.MATCH
    assert verification.committable is True


@pytest.mark.parametrize(
    ("receipt_id", "expected", "observations", "verdict"),
    [
        ("different", {"healthy": True}, "real", EffectVerdict.MISMATCH),
        ("same", {}, "real", EffectVerdict.UNKNOWN),
        ("same", {"healthy": True}, "none", EffectVerdict.UNKNOWN),
        ("same", {"temperature_c": 100.0}, "real", EffectVerdict.MISMATCH),
    ],
)
def test_effect_verification_is_fail_closed(
    receipt_id, expected, observations, verdict
) -> None:
    provider = _provider()
    device = provider.identify(provider.discover()[0])
    operation = Operation(
        operation_id="op_effect",
        work_id="work_existing",
        capability_id="device.state.read",
        target_resource_id=device.device_id,
        expected_effect=expected,
    )
    receipt = {
        "schema": "nous.operation-receipt/v1",
        "operation_id": operation.operation_id if receipt_id == "same" else receipt_id,
        "effect_digest": "cd" * 32,
    }
    values = [provider.read_state(device)] if observations == "real" else []
    result = EffectVerifier().verify(operation, receipt, values)
    assert result.verdict is verdict
    assert result.committable is False


def test_incomplete_receipt_keeps_effect_unknown() -> None:
    provider = _provider()
    device = provider.identify(provider.discover()[0])
    operation = Operation(
        operation_id="op_incomplete_receipt",
        work_id="work_existing",
        capability_id="device.state.read",
        target_resource_id=device.device_id,
        expected_effect={"healthy": True},
    )
    result = EffectVerifier().verify(
        operation,
        {"operation_id": operation.operation_id},
        [provider.read_state(device)],
    )
    assert result.verdict is EffectVerdict.UNKNOWN
    assert result.committable is False

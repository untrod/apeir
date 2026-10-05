"""Fake signed wire fixtures exercise contracts, never physical acceptance."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from nous_runtime.reality.contracts import DeviceLifecycle
from nous_runtime.reality.registry import DeviceRegistry
from nous_runtime.reality.serial import (
    ESP32_STATE_SCHEMA,
    MAX_SERIAL_FRAME_BYTES,
    ESP32DeviceProvider,
    SerialContractError,
    SerialTransport,
)

pytestmark = pytest.mark.unit


class FakeWire:
    def __init__(self):
        self.key = Ed25519PrivateKey.generate()
        self.requests = []
        self.closed = 0
        self.modify = lambda response: None
        self.raw = None
        self.partial_write = False
        self.disconnect = False

    def open(self, **kwargs):
        assert kwargs["timeout"] <= 10
        return self

    def write(self, encoded):
        self.requests.append(json.loads(encoded))
        return len(encoded) - int(self.partial_write)

    def read_until(self, terminator, limit):
        assert terminator == b"\n" and limit == MAX_SERIAL_FRAME_BYTES + 1
        if self.disconnect:
            raise OSError("Fake disconnected serial port")
        if self.raw is not None:
            return self.raw
        request = self.requests[-1]
        response = {
            "schema": ESP32_STATE_SCHEMA,
            "kind": request["kind"],
            "nonce": request["nonce"],
            "stable_identity": "esp32-fake-chip-001",
            "state_revision": 3,
            "last_operation_id": "operation-fake-3",
            "state": {"firmware_version": "1.0.0"},
        }
        self.modify(response)
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
        response["signature"] = self.key.sign(encoded).hex()
        return json.dumps(response).encode() + b"\n"

    def close(self):
        self.closed += 1

    def provider(self, port="/dev/fake-serial", transport_id="serial-fake-1"):
        public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return ESP32DeviceProvider(
            SerialTransport(
                port,
                public.hex(),
                transport_id=transport_id,
                node_id="node-fake-1",
                opener=self.open,
            )
        )


@pytest.fixture
def fixture():
    wire = FakeWire()
    provider = wire.provider()
    device = provider.identify(provider.discover()[0])
    return wire, provider, replace(device, lifecycle=DeviceLifecycle.AVAILABLE)


def test_identity_locator_and_revocation_survive_restart(tmp_path):
    wire = FakeWire()
    first = wire.provider()
    device = first.identify(first.discover()[0])
    assert device.lifecycle is DeviceLifecycle.IDENTIFIED
    assert device.metadata["hardware_acceptance"] == "PENDING"
    assert device.capability_ids == ("device.state.read",)
    registry = DeviceRegistry(tmp_path)
    registry.register(device)
    registry.transition(device.device_id, DeviceLifecycle.TRUSTED)
    registry.transition(device.device_id, DeviceLifecycle.AVAILABLE)
    moved = wire.provider("/dev/fake-new-port", "serial-fake-2")
    rediscovered = moved.identify(moved.discover()[0])
    assert rediscovered.device_id == device.device_id
    assert registry.register(rediscovered).lifecycle is DeviceLifecycle.AVAILABLE
    registry.transition(device.device_id, DeviceLifecycle.REVOKED)
    assert (
        DeviceRegistry(tmp_path).register(rediscovered).lifecycle
        is DeviceLifecycle.REVOKED
    )
    assert (
        moved.read_state(DeviceRegistry(tmp_path).get(device.device_id)).status
        == "failed"
    )


def test_fresh_observation_even_with_reused_correlation_id(fixture):
    wire, provider, device = fixture
    first = provider.read_state(device, acquisition_id="same-correlation")
    second = provider.read_state(device, acquisition_id="same-correlation")
    assert first.status == second.status == "success"
    assert first.observation_id != second.observation_id
    assert wire.requests[-1]["nonce"] != wire.requests[-2]["nonce"]
    assert first.metadata["state_revision"] == 3
    assert first.metadata["last_operation_id"] == "operation-fake-3"
    assert wire.closed == 3


@pytest.mark.parametrize(
    "change",
    [
        {"nonce": "stale-challenge"},
        {"stable_identity": "wrong-chip"},
        {"schema": "apeir.esp32-state/v0"},
        {"kind": "mutate"},
        {"state_revision": -1},
        {"state_revision": True},
        {"last_operation_id": "bad operation"},
        {"state": []},
        {"state": {"password": "deterministic-fake-sensitive-value"}},
        {"extra": "unsupported"},
    ],
)
def test_invalid_evidence_is_not_an_observation_success(fixture, change):
    wire, provider, device = fixture
    wire.modify = lambda response: response.update(change)
    observation = provider.read_state(device)
    assert observation.status == "failed"
    assert "deterministic-fake-sensitive-value" not in json.dumps(observation.to_dict())
    assert len(wire.requests) == 2  # Identification plus one read, no retry.
    assert wire.closed == 2


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"{}\n",
        b"\xff\n",
        b'{"nonce":1,"nonce":2}\n',
        b"x" * (MAX_SERIAL_FRAME_BYTES + 1) + b"\n",
    ],
)
def test_truncated_duplicate_and_oversized_frames_fail_closed(fixture, raw):
    wire, provider, device = fixture
    wire.raw = raw
    assert provider.read_state(device).status == "failed"
    assert wire.closed == 2


def test_tampered_signature_and_disconnect_never_retry(fixture):
    wire, provider, device = fixture
    signed = wire.read_until(b"\n", MAX_SERIAL_FRAME_BYTES + 1)
    frame = json.loads(signed)
    frame["state"]["firmware_version"] = "9.9.9"
    wire.raw = json.dumps(frame).encode() + b"\n"
    assert provider.read_state(device).status == "failed"
    wire.raw = None
    wire.disconnect = True
    assert provider.read_state(device).status == "failed"
    wire.disconnect = False
    assert provider.read_state(device).status == "success"
    assert len(wire.requests) == wire.closed == 4


@pytest.mark.parametrize(
    "change",
    [
        {"device_id": "device-wrong"},
        {"provider_id": "other-provider"},
        {"node_id": "other-node"},
        {"transport_ids": ("other-transport",)},
        {"lifecycle": DeviceLifecycle.REVOKED},
    ],
)
def test_wrong_resource_binding_does_not_open_port(fixture, change):
    wire, provider, device = fixture
    assert provider.read_state(replace(device, **change)).status == "failed"
    assert len(wire.requests) == wire.closed == 1


def test_mutation_and_partial_request_are_not_supported(fixture):
    wire, provider, device = fixture
    with pytest.raises(PermissionError):
        provider.transport.exchange("firmware.update")
    assert len(wire.requests) == 1
    wire.partial_write = True
    assert provider.read_state(device).status == "failed"
    assert wire.closed == 2


def test_public_sdk_exports_and_unpinned_transport_rejected(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "sdk/provider/python")
    )
    from nous_provider.runtime import ESP32DeviceProvider as PublicProvider
    from nous_provider.runtime import SerialTransport as PublicTransport

    assert PublicProvider is ESP32DeviceProvider
    assert PublicTransport is SerialTransport
    with pytest.raises(ValueError):
        SerialTransport("/dev/fake", "not-a-public-key", transport_id="fake")
    with pytest.raises(ValueError):
        SerialTransport("socket://remote", "00" * 32, transport_id="fake")
    with pytest.raises(ValueError):
        FakeWire().provider().transport.exchange("observe", nonce="bad nonce")


def test_wrong_signing_key_fails_even_when_nonce_and_resource_match(fixture):
    wire, provider, device = fixture
    wire.key = Ed25519PrivateKey.generate()
    with pytest.raises(SerialContractError, match="signature is invalid"):
        provider.transport.exchange("observe", stable_identity=device.stable_identity)
    assert len(wire.requests) == wire.closed == 2

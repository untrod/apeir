"""Prepared ESP32 signed-state contract; physical acceptance remains PENDING.

Uses pyserial when explicitly configured on a hardware host. No mutation command
is implemented or advertised. The existing Node/Governance path must admit state
acquisition; transport challenges prove message freshness, never authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from nous_runtime.core.redaction import redact_sensitive_data, redact_sensitive_text
from nous_runtime.planner.observation import Observation
from nous_runtime.reality.contracts import Device, DeviceLifecycle, Transport
from nous_runtime.reality.provider import (
    DeviceDiscovery,
    DeviceProvider,
    DeviceTransport,
)

ESP32_STATE_SCHEMA = "apeir.esp32-state/v1"
MAX_SERIAL_FRAME_BYTES = 65_536
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class SerialContractError(ValueError):
    """Missing, stale, tampered or unsupported wire evidence; never success."""


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SerialContractError("Duplicate serial JSON field")
        result[key] = value
    return result


class SerialTransport(DeviceTransport):
    """One bounded request/response, no retries and no write-operation surface.

    Port and public key are trusted-host configuration, not Work/model inputs.
    Signing keys stay on the device; this host receives public verification data.
    A signature or chip identifier does not promote a Device to TRUSTED.
    """

    def __init__(
        self,
        port: str,
        public_key: str,
        *,
        transport_id: str,
        node_id: str = "",
        baudrate: int = 115200,
        timeout_seconds: float = 2.0,
        opener: Callable | None = None,
    ):
        if not port or len(port) > 512 or "\0" in port or "://" in port:
            raise ValueError("A fixed local serial port is required")
        if not _IDENTIFIER.fullmatch(transport_id):
            raise ValueError("A valid transport identifier is required")
        if not 0 < timeout_seconds <= 10 or baudrate not in {
            9600,
            19200,
            38400,
            57600,
            115200,
            230400,
        }:
            raise ValueError("Serial timing or baudrate exceeds its contract")
        try:
            key = bytes.fromhex(public_key)
            self._peer = Ed25519PublicKey.from_public_bytes(key)
        except (ValueError, TypeError) as exc:
            raise ValueError("A pinned Ed25519 public key is required") from exc
        self._descriptor = Transport(
            transport_id=transport_id,
            kind="serial",
            locator=f"serial://{port}",
            node_id=node_id,
            metadata={
                "public_key_fingerprint": hashlib.sha256(key).hexdigest(),
                "hardware_acceptance": "PENDING",
            },
        )
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout_seconds
        self._opener = opener
        self._lock = threading.Lock()

    @property
    def descriptor(self) -> Transport:
        return self._descriptor

    def _open(self):
        opener = self._opener
        if opener is None:
            try:
                import serial
            except ImportError as exc:
                raise SerialContractError(
                    "Install the optional pyserial driver on the hardware host"
                ) from exc
            opener = serial.Serial
        return opener(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._timeout,
            write_timeout=self._timeout,
        )

    def exchange(
        self, kind: str, *, stable_identity: str = "", nonce: str = ""
    ) -> dict:
        if kind not in {"identify", "observe"}:
            raise PermissionError("Serial mutation is not implemented or qualified")
        nonce = nonce or uuid.uuid4().hex
        if not _IDENTIFIER.fullmatch(nonce) or (
            stable_identity and not _IDENTIFIER.fullmatch(stable_identity)
        ):
            raise ValueError("Serial identity/challenge is malformed")
        request = {
            "schema": ESP32_STATE_SCHEMA,
            "kind": kind,
            "nonce": nonce,
            "stable_identity": stable_identity,
        }
        encoded = _canonical(request) + b"\n"
        with self._lock:
            connection = self._open()
            try:
                if connection.write(encoded) != len(encoded):
                    raise SerialContractError(
                        "Serial request was not completely written"
                    )
                raw = connection.read_until(b"\n", MAX_SERIAL_FRAME_BYTES + 1)
            finally:
                connection.close()
        if (
            not isinstance(raw, bytes)
            or not raw.endswith(b"\n")
            or len(raw) > MAX_SERIAL_FRAME_BYTES
        ):
            raise SerialContractError(
                "Serial response is missing, incomplete or oversized"
            )
        try:
            response = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise SerialContractError("Serial JSON response is invalid") from exc
        required = {
            "schema",
            "kind",
            "nonce",
            "stable_identity",
            "state_revision",
            "last_operation_id",
            "state",
            "signature",
        }
        if not isinstance(response, dict) or set(response) != required:
            raise SerialContractError("Serial response fields differ from the contract")
        if (
            response["schema"] != ESP32_STATE_SCHEMA
            or response["kind"] != kind
            or response["nonce"] != nonce
            or not isinstance(response["stable_identity"], str)
            or not _IDENTIFIER.fullmatch(response["stable_identity"])
            or (stable_identity and response["stable_identity"] != stable_identity)
            or type(response["state_revision"]) is not int
            or response["state_revision"] < 0
            or not isinstance(response["last_operation_id"], str)
            or (
                response["last_operation_id"]
                and not _IDENTIFIER.fullmatch(response["last_operation_id"])
            )
            or not isinstance(response["state"], dict)
            or redact_sensitive_data(response) != response
        ):
            raise SerialContractError("Serial evidence is stale, unbound or unsafe")
        signature = response.pop("signature")
        try:
            self._peer.verify(bytes.fromhex(signature), _canonical(response))
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise SerialContractError("Serial peer signature is invalid") from exc
        return response

    def read(self, device: Device) -> Mapping:
        return self.exchange("observe", stable_identity=device.stable_identity)


class ESP32DeviceProvider(DeviceProvider):
    """Prepared read-only DeviceProvider, not a physical acceptance certificate."""

    provider_id = "esp32-serial"

    def __init__(self, transport: SerialTransport):
        self.transport = transport

    def discover(self) -> tuple[DeviceDiscovery, ...]:
        return (DeviceDiscovery(self.provider_id, self.transport.descriptor.locator),)

    def identify(self, discovery: DeviceDiscovery) -> Device:
        if (
            discovery.provider_id != self.provider_id
            or discovery.locator != self.transport.descriptor.locator
        ):
            raise ValueError("Serial discovery differs from its host binding")
        response = self.transport.exchange("identify")
        stable_identity = response["stable_identity"]
        digest = hashlib.sha256(
            f"{self.provider_id}\0{stable_identity}".encode()
        ).hexdigest()[:24]
        return Device(
            device_id=f"device_{digest}",
            provider_id=self.provider_id,
            stable_identity=stable_identity,
            device_type="esp32",
            lifecycle=DeviceLifecycle.IDENTIFIED,
            node_id=self.transport.descriptor.node_id,
            capability_ids=("device.state.read",),
            transport_ids=(self.transport.descriptor.transport_id,),
            metadata={
                "hardware_acceptance": "PENDING",
                "identity_evidence": "pinned-peer-signature",
            },
        )

    def read_state(self, device: Device, *, acquisition_id: str = "") -> Observation:
        metadata = {
            "device_id": device.device_id,
            "provider_id": self.provider_id,
            "hardware_acceptance": "PENDING",
        }
        if (
            device.provider_id != self.provider_id
            or device.lifecycle is not DeviceLifecycle.AVAILABLE
            or device.device_id
            != "device_"
            + hashlib.sha256(
                f"{self.provider_id}\0{device.stable_identity}".encode()
            ).hexdigest()[:24]
            or device.node_id != self.transport.descriptor.node_id
            or self.transport.descriptor.transport_id not in device.transport_ids
        ):
            return Observation.failure(
                "reality.device.read",
                ["Serial Device is not admitted as AVAILABLE"],
                metadata=metadata,
            )
        acquisition_id = acquisition_id or uuid.uuid4().hex
        try:
            response = self.transport.exchange(
                "observe", stable_identity=device.stable_identity
            )
        except (SerialContractError, OSError, ValueError) as exc:
            return Observation.failure(
                "reality.device.read",
                [redact_sensitive_text(str(exc))],
                metadata=metadata,
            )
        return Observation.success(
            "reality.device.read",
            {"device_id": device.device_id, "state": response["state"]},
            capability="device.state.read",
            metadata={
                **metadata,
                "acquisition_id": acquisition_id,
                "state_revision": response["state_revision"],
                "last_operation_id": response["last_operation_id"],
                "transport_id": self.transport.descriptor.transport_id,
            },
        )

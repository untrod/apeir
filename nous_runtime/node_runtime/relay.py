"""R2 authenticated WebSocket transport for Nous Node Protocol v1."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import random
import secrets
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.security.private_files import restrict_owner_only_file

from .protocol import (
    MAX_MESSAGE_BYTES,
    NODE_PROTOCOL_VERSION,
    NodeProtocolEnvelope,
    NodeProtocolError,
    ReplayWindow,
    workload_request_digest,
)
from .distributed_work import (
    DistributedWorkError,
    DistributedWorkState,
    DistributedWorkStore,
    WorkRequirements,
)
from .service import NodeRuntimeService

CONTROL_PLANE_ID = "control_plane"
OBSERVED_MESSAGE_TYPES = frozenset(
    {"REGISTER", "HEARTBEAT", "RESOURCE_REPORT", "DEVICE_REPORT", "TELEMETRY"}
)


def public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


class NodeRelayServer:
    """Small control-plane relay with authenticated, replay-safe node sessions."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        private_key: Ed25519PrivateKey | None = None,
        state_dir: Path | None = None,
        ssl_context: ssl.SSLContext | None = None,
        heartbeat_seconds: float = 15.0,
        artifact_store: ContentAddressedArtifactStore | None = None,
    ):
        self.host = host
        self.port = port
        if not _is_loopback_host(host) and ssl_context is None:
            raise ValueError("a non-loopback relay listener requires TLS")
        self.state_dir = state_dir.expanduser().resolve() if state_dir else None
        if private_key is not None:
            self.private_key = private_key
        elif self.state_dir is not None:
            self.private_key = _load_or_create_relay_key(self.state_dir)
        else:
            self.private_key = Ed25519PrivateKey.generate()
        self.public_key = public_key_hex(self.private_key)
        self.ssl_context = ssl_context
        self.heartbeat_seconds = heartbeat_seconds
        self.artifact_store = artifact_store
        self.node_keys: dict[str, str] = self._load_trusted_nodes()
        self.connections: dict[str, Any] = {}
        self.sessions: dict[str, str] = {}
        self.pending: dict[str, dict[str, dict[str, Any]]] = {}
        self.pending_artifacts: dict[str, dict[str, dict[str, Any]]] = {}
        self.pending_controls: dict[str, list[dict[str, Any]]] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.result_envelopes: dict[str, dict[str, Any]] = {}
        self._load_workload_state()
        self.artifact_results: dict[str, dict[str, Any]] = {}
        self.lease_results: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, dict[str, Any]] = self._load_observations()
        self._replay = ReplayWindow()
        self._sequence = 0
        self._server: Any = None
        self._provider_spool_task: asyncio.Task[None] | None = None
        self.provider_requests = (
            self.state_dir / "provider-requests" if self.state_dir else None
        )
        self.provider_results = (
            self.state_dir / "provider-results" if self.state_dir else None
        )
        self.work_store = (
            DistributedWorkStore(self.state_dir) if self.state_dir else None
        )

    def register_node(self, node_id: str, public_key: str) -> None:
        try:
            raw_key = bytes.fromhex(public_key)
        except ValueError as exc:
            raise ValueError("node Ed25519 public key must be hex") from exc
        if len(raw_key) != 32:
            raise ValueError("node Ed25519 public key must be 32-byte hex")
        self.node_keys[node_id] = public_key
        self._save_trusted_nodes()

    def _load_trusted_nodes(self) -> dict[str, str]:
        if self.state_dir is None:
            return {}
        value = _read_json(self.state_dir / "trusted-nodes.json")
        nodes = value.get("nodes", {})
        if not isinstance(nodes, dict):
            raise TypeError("relay trusted-node registry is invalid")
        return {
            str(node_id): str(public_key)
            for node_id, public_key in nodes.items()
            if isinstance(node_id, str) and isinstance(public_key, str)
        }

    def _save_trusted_nodes(self) -> None:
        if self.state_dir is not None:
            _atomic_json(
                self.state_dir / "trusted-nodes.json",
                {"schema": "nous.relay-trust/v1", "nodes": self.node_keys},
            )

    def _load_workload_state(self) -> None:
        if self.state_dir is None:
            return
        path = self.state_dir / "workload-state.json"
        if not path.exists():
            return
        value = _read_json(path)
        if value.get("schema") != "nous.relay-workloads/v1":
            raise NodeProtocolError("relay workload state is invalid")
        pending = value.get("pending")
        results = value.get("results")
        envelopes = value.get("result_envelopes")
        controls = value.get("pending_controls", {})
        if not all(
            isinstance(item, dict) for item in (pending, results, envelopes, controls)
        ):
            raise NodeProtocolError("relay workload state is invalid")
        for workload_id, raw in envelopes.items():
            if not isinstance(raw, dict) or not isinstance(
                results.get(workload_id), dict
            ):
                raise NodeProtocolError("relay workload result is invalid")
            envelope = NodeProtocolEnvelope.from_json(json.dumps(raw), check_time=False)
            if (
                envelope.message_type != "WORKLOAD_STATUS"
                or envelope.idempotency_key != workload_id
                or envelope.payload != results[workload_id]
                or not envelope.verify(self.node_keys.get(envelope.source, ""))
            ):
                raise NodeProtocolError("relay workload result signature is invalid")
        if set(results) != set(envelopes):
            raise NodeProtocolError(
                "relay workload result is missing signed provenance"
            )
        for node_id, assigned in pending.items():
            if node_id not in self.node_keys or not isinstance(assigned, dict):
                raise NodeProtocolError("relay pending workload assignment is invalid")
            for workload_id, request in assigned.items():
                if (
                    not isinstance(request, dict)
                    or request.get("workload_id") != workload_id
                    or not isinstance(request.get("arguments"), dict)
                ):
                    raise NodeProtocolError(
                        "relay pending workload assignment is invalid"
                    )
        for node_id, requests in controls.items():
            if node_id not in self.node_keys or not isinstance(requests, list):
                raise NodeProtocolError("relay pending control is invalid")
            if not all(
                isinstance(request, dict)
                and isinstance(request.get("message_type"), str)
                and isinstance(request.get("payload"), dict)
                and isinstance(request.get("idempotency_key"), str)
                for request in requests
            ):
                raise NodeProtocolError("relay pending control is invalid")
        self.pending = pending
        self.results = results
        self.result_envelopes = envelopes
        self.pending_controls = controls

    def _save_workload_state(
        self,
        *,
        pending: dict[str, dict[str, dict[str, Any]]] | None = None,
        results: dict[str, dict[str, Any]] | None = None,
        result_envelopes: dict[str, dict[str, Any]] | None = None,
        pending_controls: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        if self.state_dir is not None:
            _atomic_json(
                self.state_dir / "workload-state.json",
                {
                    "schema": "nous.relay-workloads/v1",
                    "pending": self.pending if pending is None else pending,
                    "results": self.results if results is None else results,
                    "result_envelopes": (
                        self.result_envelopes
                        if result_envelopes is None
                        else result_envelopes
                    ),
                    "pending_controls": (
                        self.pending_controls
                        if pending_controls is None
                        else pending_controls
                    ),
                },
            )

    def _load_observations(self) -> dict[str, dict[str, Any]]:
        if self.state_dir is None:
            return {}
        value = _read_json(self.state_dir / "node-observations.json")
        if not value:
            return {}
        if value.get("schema") != "apeir.controller-observations/v1":
            raise NodeProtocolError("relay node observations are invalid")
        nodes = value.get("nodes")
        if not isinstance(nodes, dict):
            raise NodeProtocolError("relay node observations are invalid")
        observations: dict[str, dict[str, Any]] = {}
        for node_id, observation in nodes.items():
            if node_id not in self.node_keys or not isinstance(observation, dict):
                raise NodeProtocolError("relay node observation identity is invalid")
            signed = observation.get("signed_envelopes")
            message_types = {
                key for key in observation if key in OBSERVED_MESSAGE_TYPES
            }
            if not isinstance(signed, dict) or set(signed) != message_types:
                raise NodeProtocolError("relay node observation provenance is invalid")
            for message_type, raw_envelope in signed.items():
                if not isinstance(raw_envelope, dict):
                    raise NodeProtocolError(
                        "relay node observation provenance is invalid"
                    )
                envelope = NodeProtocolEnvelope.from_json(
                    json.dumps(raw_envelope), check_time=False
                )
                if (
                    envelope.source != node_id
                    or envelope.target != CONTROL_PLANE_ID
                    or envelope.message_type != message_type
                    or envelope.payload != observation[message_type]
                    or not envelope.verify(self.node_keys[node_id])
                ):
                    raise NodeProtocolError(
                        "relay node observation signature is invalid"
                    )
            observations[node_id] = observation
        return observations

    def _save_observations(self) -> None:
        if self.state_dir is not None:
            _atomic_json(
                self.state_dir / "node-observations.json",
                {
                    "schema": "apeir.controller-observations/v1",
                    "nodes": self.reports,
                },
            )

    def controller_status(self) -> dict[str, Any]:
        """Return durable controller facts without claiming offline nodes are live."""
        nodes = []
        for node_id in sorted(self.node_keys):
            observation = self.reports.get(node_id, {})
            heartbeat = observation.get("HEARTBEAT", {})
            registration = observation.get("REGISTER", {})
            identity = registration.get("identity", {})
            platform = identity.get("platform", {})
            last_observed_at = str(observation.get("observed_at", ""))
            observation_age = _observation_age_seconds(last_observed_at)
            if node_id in self.connections:
                liveness = "CONNECTED"
            elif observation_age is None:
                liveness = "NEVER_SEEN"
            elif observation_age <= self.heartbeat_seconds * 3:
                liveness = "RECENTLY_OBSERVED"
            else:
                liveness = "STALE"
            nodes.append(
                {
                    "node_id": node_id,
                    "node_name": str(identity.get("node_name", "")),
                    "connected": node_id in self.connections,
                    "session_id": self.sessions.get(node_id, ""),
                    "liveness": liveness,
                    "last_observed_at": last_observed_at,
                    "observation_age_seconds": observation_age,
                    "heartbeat_sequence": int(heartbeat.get("heartbeat_sequence", 0)),
                    "reported_status": str(
                        heartbeat.get(
                            "status", "REGISTERED" if registration else "UNKNOWN"
                        )
                    ),
                    "platform": {
                        "os": str(platform.get("os", "")),
                        "arch": str(platform.get("arch", "")),
                        "abi": str(platform.get("abi", "")),
                        "word_size_bits": identity.get("word_size_bits", 0),
                    },
                    "capabilities": list(identity.get("capabilities", [])),
                    "has_resource_report": "RESOURCE_REPORT" in observation,
                    "has_device_report": "DEVICE_REPORT" in observation,
                }
            )
        return {
            "schema": "apeir.controller-status/v1",
            "role": "controller",
            "state_dir": str(self.state_dir) if self.state_dir else "",
            "public_key": self.public_key,
            "trusted_node_count": len(self.node_keys),
            "connected_node_count": len(self.connections),
            "pending_workload_count": sum(
                len(items) for items in self.pending.values()
            ),
            "completed_workload_count": len(self.results),
            "pending_control_count": sum(
                len(items) for items in self.pending_controls.values()
            ),
            "artifact_count": (
                len(self.artifact_store.list()) if self.artifact_store else 0
            ),
            "distributed_work_count": (
                len(self.work_store.list()) if self.work_store else 0
            ),
            "distributed_work_states": (
                self.work_store.counts() if self.work_store else {}
            ),
            "nodes": nodes,
        }

    def select_node(self, requirements: dict[str, Any]) -> dict[str, Any]:
        """Select one recently observed Node by deterministic capability match."""
        if not isinstance(requirements, dict):
            raise TypeError("node placement requirements must be an object")
        raw_architecture = requirements.get("architecture", "")
        raw_capability = requirements.get("capability", "")
        if not isinstance(raw_architecture, str) or not isinstance(raw_capability, str):
            raise TypeError("node placement requirements must be strings")
        architecture = _normalize_node_architecture(raw_architecture)
        capability = raw_capability.strip()
        normalized_requirements = {
            "architecture": architecture,
            "capability": capability,
        }

        candidates: list[dict[str, Any]] = []
        for node in self.controller_status()["nodes"]:
            reasons: list[str] = []
            observed_architecture = _normalize_node_architecture(
                str(node["platform"]["arch"])
            )
            if node["liveness"] not in {"CONNECTED", "RECENTLY_OBSERVED"}:
                reasons.append(f"node liveness is {node['liveness']}")
            if architecture and observed_architecture != architecture:
                reasons.append(
                    "architecture mismatch: "
                    f"requires {architecture}, node is {observed_architecture or 'unknown'}"
                )
            if capability and capability not in node["capabilities"]:
                reasons.append(f"capability {capability} is not reported")
            candidates.append(
                {
                    "node_id": node["node_id"],
                    "node_name": node["node_name"],
                    "architecture": observed_architecture,
                    "eligible": not reasons,
                    "reasons": reasons,
                }
            )

        eligible = sorted(
            (item for item in candidates if item["eligible"]),
            key=lambda item: item["node_id"],
        )
        return {
            "schema": "apeir.node-placement/v1",
            "strategy": "deterministic-capability-match",
            "requirements": normalized_requirements,
            "selected_node": eligible[0]["node_id"] if eligible else "",
            "candidates": candidates,
            "authority": "placement-only",
            "grants_capabilities": False,
        }

    def select_work_node(self, requirements: WorkRequirements) -> dict[str, Any]:
        """Match a distributed Work to signed Node facts deterministically."""
        candidates: list[dict[str, Any]] = []
        for node in self.controller_status()["nodes"]:
            node_id = str(node["node_id"])
            observation = self.reports.get(node_id, {})
            resources = observation.get("RESOURCE_REPORT", {})
            if not isinstance(resources, dict):
                resources = {}
            device_report = observation.get("DEVICE_REPORT", {})
            devices = (
                device_report.get("devices", [])
                if isinstance(device_report, dict)
                else []
            )
            if not isinstance(devices, list):
                devices = []

            architecture = _normalize_node_architecture(str(node["platform"]["arch"]))
            operating_system = str(node["platform"]["os"]).strip().lower()
            capabilities = {str(item).strip().lower() for item in node["capabilities"]}
            memory_available = _non_negative_int(
                resources.get("memory_available_bytes")
            )
            memory_total = _non_negative_int(resources.get("memory_total_bytes"))
            gpu_available = any(_is_gpu_device(item) for item in devices)
            reasons: list[str] = []
            if node["liveness"] not in {"CONNECTED", "RECENTLY_OBSERVED"}:
                reasons.append(f"node liveness is {node['liveness']}")
            if (
                requirements.architectures
                and architecture not in requirements.architectures
            ):
                reasons.append(
                    "architecture mismatch: requires one of "
                    f"{list(requirements.architectures)}, node is "
                    f"{architecture or 'unknown'}"
                )
            if (
                requirements.operating_systems
                and operating_system not in requirements.operating_systems
            ):
                reasons.append(
                    "operating system mismatch: requires one of "
                    f"{list(requirements.operating_systems)}, node is "
                    f"{operating_system or 'unknown'}"
                )
            missing = sorted(set(requirements.capabilities) - capabilities)
            if missing:
                reasons.append(f"capabilities are not reported: {missing}")
            if requirements.minimum_memory_bytes:
                measured_memory = memory_available or memory_total
                if measured_memory < requirements.minimum_memory_bytes:
                    reasons.append(
                        "insufficient memory: requires "
                        f"{requirements.minimum_memory_bytes}, node reports "
                        f"{measured_memory}"
                    )
            if requirements.gpu_required and not gpu_available:
                reasons.append("GPU is required but not reported")
            candidates.append(
                {
                    "node_id": node_id,
                    "node_name": node["node_name"],
                    "architecture": architecture,
                    "operating_system": operating_system,
                    "capabilities": sorted(capabilities),
                    "memory_available_bytes": memory_available,
                    "memory_total_bytes": memory_total,
                    "gpu_available": gpu_available,
                    "eligible": not reasons,
                    "reasons": reasons,
                }
            )
        eligible = sorted(
            (item for item in candidates if item["eligible"]),
            key=lambda item: item["node_id"],
        )
        return {
            "schema": "apeir.work-placement/v1",
            "strategy": "deterministic-capability-resource-match",
            "requirements": requirements.to_dict(),
            "selected_node": eligible[0]["node_id"] if eligible else "",
            "candidates": candidates,
            "authority": "placement-only",
            "grants_capabilities": False,
        }

    def schedule_work(self, work_id: str) -> dict[str, Any]:
        """Evaluate and persist placement without dispatching the Work."""
        if self.work_store is None:
            raise DistributedWorkError("Controller state directory is required")
        work = self.work_store.get(work_id)
        if work is None:
            raise DistributedWorkError(f"Work does not exist: {work_id}")
        if work.state is DistributedWorkState.CREATED:
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.SCHEDULED,
                reason="Work admitted for deterministic placement",
            )
        elif work.state is not DistributedWorkState.SCHEDULED:
            raise DistributedWorkError(
                f"Work cannot be scheduled from {work.state.value}"
            )
        decision = self.select_work_node(work.requirements)
        work = self.work_store.record_placement(work_id, decision)
        selected_node = str(decision["selected_node"])
        if selected_node:
            work = self.work_store.assign(work_id, selected_node)
        return {"work": work.to_dict(), "placement": decision}

    def stage_work_dispatch(self, work_id: str) -> dict[str, Any]:
        """Stage one assignment for the running Controller provider spool."""
        if (
            self.work_store is None
            or self.provider_requests is None
            or self.artifact_store is None
        ):
            raise DistributedWorkError(
                "Controller state and Artifact store are required"
            )
        work = self.work_store.get(work_id)
        if work is None:
            raise DistributedWorkError(f"Work does not exist: {work_id}")
        if work.state is not DistributedWorkState.ASSIGNED or not work.assignment:
            raise DistributedWorkError("dispatch requires an ASSIGNED Work")
        if work.execution_policy.delivery != "at_most_once":
            raise DistributedWorkError(
                "Distributed Work v0.2 dispatch requires at-most-once delivery"
            )
        capability = work.execution_capability
        if not capability:
            raise DistributedWorkError("Work execution capability is required")
        if capability not in work.requirements.capabilities:
            raise DistributedWorkError(
                "Work execution capability must be included in requirements"
            )
        input_digests = tuple(
            _artifact_uri_digest(reference) for reference in work.input_artifacts
        )
        for digest in input_digests:
            self.artifact_store.resolve(digest, verify=True)

        target = {
            "node_id": work.assigned_node,
            "capability": capability,
        }
        binding = {
            "intent_id": work.work_id,
            "effect_contract_digest": _payload_digest(
                {
                    "capability": capability,
                    "execution_policy": work.execution_policy.to_dict(),
                }
            ),
            "target_ref": (f"node://{work.assigned_node}/capability/{capability}"),
            "target_binding_digest": _payload_digest(target),
            "workload_id": work.work_id,
            "request_digest": _payload_digest(work.execution_arguments),
            "provider_revision": "apeir.distributed-work/v1",
        }
        request = {
            "schema": "nous.remote-provider-request/v1",
            "operation_id": work.work_id,
            "workload_id": work.work_id,
            "step_id": work.assignment.assignment_id,
            "node_id": work.assigned_node,
            "capability": capability,
            "arguments": dict(work.execution_arguments),
            "timeout_seconds": 30.0,
            "delivery_semantics": "at_most_once",
            "binding": binding,
            "input_artifacts": list(work.input_artifacts),
        }
        request_digest = _payload_digest(request)
        self.provider_requests.mkdir(parents=True, exist_ok=True)
        request_path = self.provider_requests / f"{work.work_id}.json"
        if work.dispatch_record:
            if work.dispatch_record.get("provider_request_digest") != request_digest:
                raise DistributedWorkError("recorded Work dispatch binding changed")
            if request_path.exists():
                if _read_json(request_path) != request:
                    raise DistributedWorkError("staged Work dispatch binding changed")
            else:
                _atomic_json(request_path, request)
            return {"work": work.to_dict(), "dispatch": work.dispatch_record}
        if request_path.exists():
            if _read_json(request_path) != request:
                raise DistributedWorkError("staged Work dispatch binding changed")
        else:
            _atomic_json(request_path, request)
        dispatch = {
            "schema": "apeir.work-dispatch/v1",
            "work_id": work.work_id,
            "assignment_id": work.assignment.assignment_id,
            "node_id": work.assigned_node,
            "staged_at": _utc_now(),
            "provider_request_digest": request_digest,
            "input_artifacts": list(work.input_artifacts),
            "delivery": "at_most_once",
        }
        updated = self.work_store.record_dispatch(work.work_id, dispatch)
        return {"work": updated.to_dict(), "dispatch": dispatch}

    def reconcile_work(self, work_id: str) -> dict[str, Any]:
        """Reconcile one signed terminal Node result into durable Work state."""
        if self.state_dir is None or self.artifact_store is None:
            raise DistributedWorkError(
                "Controller state and Artifact store are required"
            )
        self.work_store = DistributedWorkStore(self.state_dir)
        work = self.work_store.get(work_id)
        if work is None:
            raise DistributedWorkError(f"Work does not exist: {work_id}")
        if work.state is DistributedWorkState.COMMITTED:
            return {"work": work.to_dict(), "reconciled": False, "idempotent": True}
        payload = self.results.get(work_id)
        envelope = self.result_envelopes.get(work_id)
        if not isinstance(payload, dict) or not isinstance(envelope, dict):
            raise DistributedWorkError("signed Work result is not available")
        if not work.assignment:
            raise DistributedWorkError("Work result has no durable assignment")
        source_node = str(envelope.get("source") or "")
        if source_node != work.assignment.node_id:
            raise DistributedWorkError("Work result node does not match assignment")

        state = str(payload.get("state") or "")
        if state == "RECOVERY_REQUIRED":
            if work.state is DistributedWorkState.UNKNOWN:
                _verify_recorded_result(work, payload, envelope, status="UNKNOWN")
                return {
                    "work": work.to_dict(),
                    "reconciled": False,
                    "idempotent": True,
                }
            summary = _work_result_summary(work, payload, envelope, status="UNKNOWN")
            work = self.work_store.record_result(work_id, summary)
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.UNKNOWN,
                reason="Node reported an uncertain at-most-once effect",
            )
            return {"work": work.to_dict(), "reconciled": True, "idempotent": False}
        if state != "COMPLETED":
            if work.state is DistributedWorkState.FAILED:
                _verify_recorded_result(work, payload, envelope, status="FAILED")
                return {
                    "work": work.to_dict(),
                    "reconciled": False,
                    "idempotent": True,
                }
            summary = _work_result_summary(work, payload, envelope, status="FAILED")
            work = self.work_store.record_result(work_id, summary)
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.FAILED,
                reason="Signed Node execution failed",
            )
            return {"work": work.to_dict(), "reconciled": True, "idempotent": False}

        receipt = remote_execution_receipt(envelope, expected_operation_id=work.work_id)
        if receipt["node_id"] != work.assignment.node_id:
            raise DistributedWorkError(
                "verified receipt node does not match assignment"
            )
        if work.state is DistributedWorkState.VERIFIED:
            _verify_committed_artifacts(work, self.artifact_store)
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.COMMITTED,
                reason="Recovered verified Work result committed",
            )
            return {"work": work.to_dict(), "reconciled": True, "idempotent": True}
        if work.state is DistributedWorkState.SUCCEEDED and work.result_summary:
            _verify_recorded_result(work, payload, envelope, status="VERIFIED")
            _verify_committed_artifacts(work, self.artifact_store)
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.VERIFIED,
                reason="Recovered receipt and Artifact verification",
            )
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.COMMITTED,
                reason="Recovered verified Work result committed",
            )
            return {"work": work.to_dict(), "reconciled": True, "idempotent": True}
        if work.state is DistributedWorkState.ASSIGNED:
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.RUNNING,
                reason="Signed terminal result proves Node execution occurred",
            )
        if work.state is DistributedWorkState.RUNNING:
            work = self.work_store.transition(
                work_id,
                DistributedWorkState.SUCCEEDED,
                reason="Node returned a signed successful execution result",
            )
        elif work.state is not DistributedWorkState.SUCCEEDED:
            raise DistributedWorkError(
                f"completed result cannot reconcile from {work.state.value}"
            )

        dependencies = tuple(
            _artifact_uri_digest(reference) for reference in work.input_artifacts
        )
        output_value = {
            "schema": "apeir.distributed-work-output/v1",
            "work_id": work.work_id,
            "node_id": work.assigned_node,
            "output": payload.get("output"),
        }
        output_stored = self.artifact_store.store_bytes(
            json.dumps(
                output_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            artifact_type="verification_result",
            name=f"{work.work_id}-output.json",
            media_type="application/vnd.apeir.distributed-work-output+json",
            produced_by=f"distributed-work:{work.work_id}",
            derived_from=dependencies,
            metadata={
                "work_id": work.work_id,
                "node_id": work.assigned_node,
                "owner": work.creator,
                "retention_policy": "work-lifecycle",
            },
        )
        evidence_value = {
            "schema": "apeir.distributed-work-evidence/v1",
            "work_id": work.work_id,
            "remote_execution_receipt": receipt,
        }
        evidence_stored = self.artifact_store.store_bytes(
            json.dumps(
                evidence_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            artifact_type="evidence",
            name=f"{work.work_id}-evidence.json",
            media_type="application/vnd.apeir.distributed-work-evidence+json",
            produced_by=f"distributed-work:{work.work_id}",
            depends_on=(str(output_stored["artifact"]["digest"]),),
            derived_from=dependencies,
            metadata={
                "work_id": work.work_id,
                "node_id": work.assigned_node,
                "owner": work.creator,
                "retention_policy": "audit",
                "signed_envelope_digest": receipt["signed_envelope_digest"],
            },
        )
        output_digest = str(output_stored["artifact"]["digest"])
        evidence_digest = str(evidence_stored["artifact"]["digest"])
        if not (
            self.artifact_store.verify(output_digest)
            and self.artifact_store.verify(evidence_digest)
        ):
            raise DistributedWorkError("Work Artifact verification failed")
        output_ref = _artifact_digest_uri(output_digest)
        evidence_ref = _artifact_digest_uri(evidence_digest)
        summary = _work_result_summary(
            work,
            payload,
            envelope,
            status="VERIFIED",
            remote_receipt=receipt,
            output_artifact=output_ref,
            evidence_artifact=evidence_ref,
        )
        work = self.work_store.record_result(
            work_id,
            summary,
            output_artifacts=(output_ref,),
            evidence_refs=(evidence_ref,),
        )
        work = self.work_store.transition(
            work_id,
            DistributedWorkState.VERIFIED,
            reason="Receipt signature and Artifact digests verified",
        )
        work = self.work_store.transition(
            work_id,
            DistributedWorkState.COMMITTED,
            reason="Verified Work result committed",
        )
        return {"work": work.to_dict(), "reconciled": True, "idempotent": False}

    async def start(self) -> str:
        self._server = await serve(
            self._handle_connection,
            self.host,
            self.port,
            ssl=self.ssl_context,
            max_size=MAX_MESSAGE_BYTES,
            compression=None,
            ping_interval=self.heartbeat_seconds,
            ping_timeout=self.heartbeat_seconds * 2,
        )
        socket = self._server.sockets[0]
        port = socket.getsockname()[1]
        scheme = "wss" if self.ssl_context else "ws"
        if self.provider_requests is not None and self.provider_results is not None:
            self.provider_requests.mkdir(parents=True, exist_ok=True)
            self.provider_results.mkdir(parents=True, exist_ok=True)
            self._provider_spool_task = asyncio.create_task(self._run_provider_spool())
        return f"{scheme}://{self.host}:{port}"

    async def stop(self) -> None:
        if self._provider_spool_task is not None:
            self._provider_spool_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._provider_spool_task
            self._provider_spool_task = None
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def queue_workload(
        self,
        node_id: str,
        workload_id: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_seconds: float = 30.0,
        delivery_semantics: str = "idempotent",
        binding: dict[str, str] | None = None,
    ) -> None:
        if node_id not in self.node_keys:
            raise NodeProtocolError("node is not registered")
        prior = self.result_envelopes.get(workload_id)
        if prior is not None and prior.get("source") != node_id:
            raise NodeProtocolError("workload is already bound to another node")
        if any(
            workload_id in assigned and assigned_node != node_id
            for assigned_node, assigned in self.pending.items()
        ):
            raise NodeProtocolError("workload is already assigned to another node")
        if delivery_semantics not in {"idempotent", "at_most_once"}:
            raise NodeProtocolError("unsupported workload delivery semantics")
        if binding is not None and (
            not isinstance(binding, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in binding.items()
            )
        ):
            raise NodeProtocolError("workload binding must contain string fields")
        if delivery_semantics == "at_most_once" and not all(
            isinstance((binding or {}).get(field), str) and (binding or {}).get(field)
            for field in (
                "intent_id",
                "effect_contract_digest",
                "target_ref",
                "target_binding_digest",
                "workload_id",
                "request_digest",
                "provider_revision",
            )
        ):
            raise NodeProtocolError("at-most-once workload binding is incomplete")
        request = {
            "workload_id": workload_id,
            "capability": capability,
            "arguments": dict(arguments or {}),
            "timeout_seconds": timeout_seconds,
            "delivery_semantics": delivery_semantics,
            "binding": binding or {},
        }
        if delivery_semantics == "at_most_once":
            existing = self.pending.get(node_id, {}).get(workload_id)
            if existing is not None:
                if existing != request:
                    raise NodeProtocolError("at-most-once workload assignment changed")
                return
            completed = self.results.get(workload_id)
            if completed is not None:
                if completed.get("request_digest") != _workload_request_digest(request):
                    raise NodeProtocolError(
                        "at-most-once workload result binding changed"
                    )
                return
        staged_pending = {key: dict(value) for key, value in self.pending.items()}
        staged_pending.setdefault(node_id, {})[workload_id] = request
        self._save_workload_state(pending=staged_pending)
        self.pending = staged_pending
        connection = self.connections.get(node_id)
        if connection is not None:
            await self._send_workload(connection, node_id, request)

    async def queue_artifact(self, node_id: str, digest: str) -> None:
        """Queue a verified CAS artifact (and graph dependencies) for a node."""
        if node_id not in self.node_keys:
            raise NodeProtocolError("node is not registered")
        if self.artifact_store is None:
            raise NodeProtocolError("relay artifact store is not configured")
        record = self.artifact_store.get(digest)
        if record is None:
            raise NodeProtocolError("artifact is not present in relay store")
        for linked in (*record.depends_on, *record.derived_from):
            await self.queue_artifact(node_id, linked)
        self.pending_artifacts.setdefault(node_id, {})[digest] = record.to_dict()
        connection = self.connections.get(node_id)
        if connection is not None:
            await self._send_artifact(connection, node_id, digest, record.to_dict())

    async def queue_lease_acquire(
        self, node_id: str, lease_id: str, resource_id: str, ttl_seconds: float
    ) -> None:
        await self._queue_control(
            node_id,
            "LEASE_ACQUIRE",
            {
                "lease_id": lease_id,
                "resource_id": resource_id,
                "ttl_seconds": ttl_seconds,
            },
            lease_id,
        )

    async def queue_lease_release(
        self, node_id: str, lease_id: str, resource_id: str
    ) -> None:
        await self._queue_control(
            node_id,
            "LEASE_RELEASE",
            {"lease_id": lease_id, "resource_id": resource_id},
            lease_id,
        )

    async def queue_workload_stop(self, node_id: str, workload_id: str) -> None:
        await self._queue_control(
            node_id,
            "WORKLOAD_STOP",
            {"workload_id": workload_id},
            workload_id,
            cancel_workload_id=workload_id,
        )

    async def _queue_control(
        self,
        node_id: str,
        message_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        *,
        cancel_workload_id: str | None = None,
    ) -> None:
        if node_id not in self.node_keys:
            raise NodeProtocolError("node is not registered")
        request = {
            "message_type": message_type,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        staged_controls = {
            key: list(value) for key, value in self.pending_controls.items()
        }
        controls = staged_controls.setdefault(node_id, [])
        if not any(
            item.get("message_type") == message_type
            and item.get("idempotency_key") == idempotency_key
            for item in controls
        ):
            controls.append(request)
        staged_pending = {key: dict(value) for key, value in self.pending.items()}
        if cancel_workload_id is not None:
            staged_pending.get(node_id, {}).pop(cancel_workload_id, None)
        self._save_workload_state(
            pending=staged_pending, pending_controls=staged_controls
        )
        self.pending = staged_pending
        self.pending_controls = staged_controls
        connection = self.connections.get(node_id)
        if connection is None:
            return
        await self._send(
            connection,
            node_id,
            message_type,
            payload,
            idempotency_key=idempotency_key,
        )

    async def _handle_connection(self, websocket: Any) -> None:
        node_id = ""
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            envelope = NodeProtocolEnvelope.from_json(raw)
            if (
                envelope.message_type != "REGISTER"
                or envelope.target != CONTROL_PLANE_ID
            ):
                raise NodeProtocolError("REGISTER must be the first message")
            node_id = envelope.source
            if self.state_dir is not None:
                # The controller CLI may enroll a Node while this listener is
                # running. Reload the durable registry at the authentication
                # boundary so the new key becomes usable without a restart.
                self.node_keys = self._load_trusted_nodes()
            public_key = self.node_keys.get(node_id, "")
            if not public_key or not envelope.verify(public_key):
                raise NodeProtocolError("node authentication failed")
            self._replay.accept(envelope)
            payload = envelope.payload
            if payload.get("node_id") != node_id:
                raise NodeProtocolError("registered identity does not match source")
            raw_identity = payload.get("identity")
            if not isinstance(raw_identity, dict):
                raise NodeProtocolError("registered node identity is invalid")
            try:
                identity = NodeIdentity.from_dict(raw_identity)
            except (KeyError, TypeError, ValueError) as exc:
                raise NodeProtocolError("registered node identity is invalid") from exc
            if identity.node_id != node_id or identity.public_key != public_key:
                raise NodeProtocolError(
                    "registered node identity is not bound to its trusted key"
                )
            if NODE_PROTOCOL_VERSION not in payload.get("supported_versions", []):
                raise NodeProtocolError("no compatible protocol version")

            self._record_observation(node_id, envelope)

            previous = self.sessions.get(node_id, "")
            resume = payload.get("resume_session_id", "")
            resumed = bool(previous and secrets.compare_digest(previous, resume))
            session_id = previous if resumed else f"session_{secrets.token_hex(16)}"
            self.sessions[node_id] = session_id
            self.connections[node_id] = websocket
            await self._send(
                websocket,
                node_id,
                "ACK",
                {
                    "acknowledged": "REGISTER",
                    "session_id": session_id,
                    "protocol_version": NODE_PROTOCOL_VERSION,
                    "resumed": resumed,
                    "heartbeat_seconds": self.heartbeat_seconds,
                },
                reply_to=envelope.message_id,
            )
            for digest, artifact in list(
                self.pending_artifacts.get(node_id, {}).items()
            ):
                await self._send_artifact(websocket, node_id, digest, artifact)
            for request in list(self.pending.get(node_id, {}).values()):
                await self._send_workload(websocket, node_id, request)
            for request in list(self.pending_controls.get(node_id, [])):
                await self._send(
                    websocket,
                    node_id,
                    request["message_type"],
                    request["payload"],
                    idempotency_key=request["idempotency_key"],
                )

            async for raw in websocket:
                envelope = NodeProtocolEnvelope.from_json(raw)
                if envelope.source != node_id or envelope.target != CONTROL_PLANE_ID:
                    raise NodeProtocolError(
                        "message route changed after authentication"
                    )
                if not envelope.verify(public_key):
                    raise NodeProtocolError("message signature verification failed")
                self._replay.accept(envelope)
                await self._handle_message(websocket, node_id, envelope)
        except (asyncio.TimeoutError, ConnectionClosed):
            pass
        except NodeProtocolError as exc:
            try:
                await self._send(
                    websocket,
                    node_id or "untrusted_node",
                    "ERROR",
                    {"code": "PROTOCOL_ERROR", "message": str(exc)},
                )
            except ConnectionClosed:
                pass
            await websocket.close(code=1008, reason="protocol policy violation")
        finally:
            if node_id and self.connections.get(node_id) is websocket:
                self.connections.pop(node_id, None)

    async def _handle_message(
        self, websocket: Any, node_id: str, envelope: NodeProtocolEnvelope
    ) -> None:
        if envelope.message_type in OBSERVED_MESSAGE_TYPES - {"REGISTER"}:
            self._record_observation(node_id, envelope)
        elif envelope.message_type == "WORKLOAD_STATUS":
            workload_id = str(envelope.payload.get("workload_id", ""))
            assignment = self.pending.get(node_id, {}).get(workload_id)
            assigned = assignment is not None
            stopped = any(
                item.get("message_type") == "WORKLOAD_STOP"
                and item.get("idempotency_key") == workload_id
                for item in self.pending_controls.get(node_id, [])
            )
            prior = self.result_envelopes.get(workload_id)
            if prior is not None and prior.get("source") != node_id:
                raise NodeProtocolError("workload result is bound to another node")
            if not (assigned or stopped or (prior and prior.get("source") == node_id)):
                raise NodeProtocolError(
                    "workload status has no matching node assignment"
                )
            if envelope.idempotency_key != workload_id:
                raise NodeProtocolError("workload status idempotency key is mismatched")
            if assignment and assignment.get("delivery_semantics") == "at_most_once":
                _verify_at_most_once_result(node_id, assignment, envelope.payload)
            staged_pending = {key: dict(value) for key, value in self.pending.items()}
            staged_pending.get(node_id, {}).pop(workload_id, None)
            staged_results = {**self.results, workload_id: envelope.payload}
            staged_envelopes = {
                **self.result_envelopes,
                workload_id: envelope.to_dict(),
            }
            self._save_workload_state(
                pending=staged_pending,
                results=staged_results,
                result_envelopes=staged_envelopes,
            )
            self.pending = staged_pending
            self.results = staged_results
            self.result_envelopes = staged_envelopes
            self._publish_provider_result(workload_id)
            self._complete_control(node_id, "WORKLOAD_STOP", workload_id)
        elif envelope.message_type == "ARTIFACT_READY":
            digest = str(envelope.payload.get("digest", ""))
            if digest:
                self.artifact_results[digest] = envelope.payload
                if envelope.payload.get("state") == "READY":
                    self.pending_artifacts.get(node_id, {}).pop(digest, None)
        elif envelope.message_type == "ACK":
            acknowledged = str(envelope.payload.get("acknowledged", ""))
            if acknowledged == "WORKLOAD_START":
                workload_id = str(envelope.payload.get("workload_id", ""))
                self._mark_work_running(workload_id, node_id)
            lease = envelope.payload.get("lease")
            if isinstance(lease, dict) and lease.get("lease_id"):
                lease_id = str(lease["lease_id"])
                self.lease_results[lease_id] = lease
                if acknowledged in {"LEASE_ACQUIRE", "LEASE_RELEASE"}:
                    self._complete_control(node_id, acknowledged, lease_id)
        elif envelope.message_type not in {"HEARTBEAT", "ACK", "ERROR"}:
            await self._send(
                websocket,
                node_id,
                "ERROR",
                {
                    "code": "UNSUPPORTED_DIRECTION",
                    "message_type": envelope.message_type,
                },
                reply_to=envelope.message_id,
            )
            return
        await self._send(
            websocket,
            node_id,
            "ACK",
            {"acknowledged": envelope.message_type},
            reply_to=envelope.message_id,
        )

    def _record_observation(self, node_id: str, envelope: NodeProtocolEnvelope) -> None:
        observation = self.reports.setdefault(node_id, {})
        observation[envelope.message_type] = envelope.payload
        observation.setdefault("signed_envelopes", {})[envelope.message_type] = (
            envelope.to_dict()
        )
        observation["observed_at"] = _utc_now()
        self._save_observations()

    def _mark_work_running(self, work_id: str, node_id: str) -> None:
        """Bind a signed Node acknowledgement to the durable Work lifecycle."""
        if not self.state_dir or not work_id:
            return
        self.work_store = DistributedWorkStore(self.state_dir)
        work = self.work_store.get(work_id)
        if work is None:
            return
        if work.assigned_node != node_id:
            raise NodeProtocolError("Work acknowledgement node changed")
        if work.state is DistributedWorkState.ASSIGNED:
            self.work_store.transition(
                work_id,
                DistributedWorkState.RUNNING,
                reason="Node acknowledged the signed Work assignment",
            )
        elif work.state not in {
            DistributedWorkState.RUNNING,
            DistributedWorkState.SUCCEEDED,
            DistributedWorkState.VERIFIED,
            DistributedWorkState.COMMITTED,
        }:
            raise NodeProtocolError(
                f"Work acknowledgement is invalid from {work.state.value}"
            )

    def _complete_control(
        self, node_id: str, message_type: str, idempotency_key: str
    ) -> None:
        """Remove a control only after its terminal node response is received."""
        controls = self.pending_controls.get(node_id)
        if not controls:
            return
        remaining = [
            request
            for request in controls
            if not (
                request.get("message_type") == message_type
                and request.get("idempotency_key") == idempotency_key
            )
        ]
        staged_controls = {
            key: list(value) for key, value in self.pending_controls.items()
        }
        if remaining:
            staged_controls[node_id] = remaining
        else:
            staged_controls.pop(node_id, None)
        self._save_workload_state(pending_controls=staged_controls)
        self.pending_controls = staged_controls

    async def _send_workload(
        self, websocket: Any, node_id: str, request: dict[str, Any]
    ) -> None:
        await self._send(
            websocket,
            node_id,
            "WORKLOAD_START",
            request,
            idempotency_key=request["workload_id"],
        )

    async def _run_provider_spool(self) -> None:
        assert self.provider_requests is not None
        while True:
            for request_path in sorted(self.provider_requests.glob("*.json")):
                await self._ingest_provider_request(request_path)
            await asyncio.sleep(0.05)

    async def _ingest_provider_request(self, request_path: Path) -> None:
        assert self.provider_results is not None
        try:
            value = json.loads(request_path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema") != "nous.remote-provider-request/v1"
            ):
                raise NodeProtocolError("remote provider request schema is invalid")
            operation_id = str(value.get("operation_id", ""))
            node_id = str(value.get("node_id", ""))
            if request_path.stem != operation_id:
                raise NodeProtocolError("remote provider request filename is not bound")
            input_artifacts = value.get("input_artifacts", [])
            if not isinstance(input_artifacts, list) or not all(
                isinstance(item, str) for item in input_artifacts
            ):
                raise NodeProtocolError("remote provider input artifacts are invalid")
            if input_artifacts and self.artifact_store is not None:
                self.artifact_store = ContentAddressedArtifactStore(
                    self.artifact_store.root
                )
            for reference in input_artifacts:
                await self.queue_artifact(node_id, _artifact_uri_digest(reference))
            await self.queue_workload(
                node_id,
                operation_id,
                str(value.get("capability", "")),
                value.get("arguments"),
                timeout_seconds=float(value.get("timeout_seconds", 30.0)),
                delivery_semantics=str(value.get("delivery_semantics", "")),
                binding=value.get("binding"),
            )
            self._publish_provider_result(operation_id)
        except (KeyError, OSError, TypeError, ValueError, NodeProtocolError) as exc:
            operation_id = request_path.stem
            _atomic_json(
                self.provider_results / f"{operation_id}.json",
                {
                    "ok": False,
                    "error_code": "REMOTE_PROVIDER_REQUEST_REJECTED",
                    "error_message": f"{type(exc).__name__}: {exc}",
                },
            )
            request_path.unlink(missing_ok=True)

    def _publish_provider_result(self, workload_id: str) -> None:
        if (
            self.provider_requests is None
            or self.provider_results is None
            or workload_id not in self.result_envelopes
        ):
            return
        request_path = self.provider_requests / f"{workload_id}.json"
        if not request_path.is_file():
            return
        result_path = self.provider_results / f"{workload_id}.json"
        if result_path.is_file():
            request_path.unlink(missing_ok=True)
            return
        payload = self.results[workload_id]
        if payload.get("state") == "RECOVERY_REQUIRED":
            value = {
                "ok": False,
                "error_code": "NOUS_NODE_UNCERTAIN_EFFECT",
                "error_message": "remote effect outcome requires manual recovery",
            }
        elif payload.get("state") != "COMPLETED":
            value = {
                "ok": False,
                "error_code": str(
                    payload.get("error_code") or "REMOTE_EXECUTION_FAILED"
                ),
                "error_message": str(payload.get("error") or "remote execution failed"),
            }
        else:
            value = {
                "ok": True,
                "output": payload.get("output"),
                "remote_execution_receipt": remote_execution_receipt(
                    self.result_envelopes[workload_id],
                    expected_operation_id=workload_id,
                ),
            }
        _atomic_json(result_path, value)
        request_path.unlink(missing_ok=True)

    async def _send_artifact(
        self,
        websocket: Any,
        node_id: str,
        digest: str,
        artifact: dict[str, Any],
    ) -> None:
        if self.artifact_store is None:
            raise NodeProtocolError("relay artifact store is not configured")
        source = self.artifact_store.resolve(digest, verify=True)
        total_size = source.stat().st_size
        transfer_id = "artifact_" + digest.removeprefix("sha256:")
        offset = 0
        with source.open("rb") as handle:
            while True:
                chunk = handle.read(256 * 1024)
                eof = offset + len(chunk) == total_size
                await self._send(
                    websocket,
                    node_id,
                    "ARTIFACT_FETCH",
                    {
                        "digest": digest,
                        "transfer_id": transfer_id,
                        "offset": offset,
                        "total_size": total_size,
                        "chunk_b64": base64.b64encode(chunk).decode("ascii"),
                        "eof": eof,
                        "artifact": artifact,
                    },
                    idempotency_key=f"{transfer_id}:{offset}",
                )
                offset += len(chunk)
                if eof:
                    break

    async def _send(
        self,
        websocket: Any,
        target: str,
        message_type: str,
        payload: dict[str, Any],
        *,
        reply_to: str = "",
        idempotency_key: str = "",
    ) -> None:
        self._sequence += 1
        envelope = NodeProtocolEnvelope(
            message_type=message_type,
            source=CONTROL_PLANE_ID,
            target=target,
            sequence=self._sequence,
            payload=payload,
            reply_to=reply_to,
            idempotency_key=idempotency_key,
        ).sign(self.private_key)
        await websocket.send(envelope.to_json())


class NodeRelayClient:
    """Connect a durable NodeRuntimeService to a Node Protocol relay."""

    def __init__(
        self,
        service: NodeRuntimeService,
        relay_url: str,
        server_public_key: str,
        *,
        ssl_context: ssl.SSLContext | None = None,
        heartbeat_seconds: float = 15.0,
    ):
        _validate_relay_url(relay_url)
        self.service = service
        self.relay_url = relay_url
        self.server_public_key = server_public_key
        self.ssl_context = ssl_context
        self.heartbeat_seconds = heartbeat_seconds
        self.session_path = service.state_dir / "relay-session.json"
        self.sequence_path = service.state_dir / "relay-sequence.json"
        self._sequence = self._load_sequence()
        self._replay = ReplayWindow()

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        delay = 1.0
        while not stop_event.is_set():
            try:
                await self.run_session(stop_event)
                delay = 1.0
            except (OSError, TimeoutError, ConnectionClosed, NodeProtocolError):
                if stop_event.is_set():
                    break
                await asyncio.sleep(delay + random.random() * min(delay * 0.25, 1.0))
                delay = min(delay * 2, 60.0)

    async def run_session(self, stop_event: asyncio.Event) -> None:
        async with connect(
            self.relay_url,
            ssl=self.ssl_context,
            proxy=None,
            max_size=MAX_MESSAGE_BYTES,
            compression=None,
            open_timeout=10,
            ping_interval=self.heartbeat_seconds,
            ping_timeout=self.heartbeat_seconds * 2,
        ) as websocket:
            await self._send(
                websocket,
                "REGISTER",
                {
                    "node_id": self.service.identity.node_id,
                    "identity": self.service.identity.to_dict(),
                    "supported_versions": [NODE_PROTOCOL_VERSION],
                    "resume_session_id": self._load_session_id(),
                },
            )
            welcome = await self._receive(websocket)
            if (
                welcome.message_type != "ACK"
                or welcome.payload.get("acknowledged") != "REGISTER"
            ):
                raise NodeProtocolError("relay did not accept node registration")
            self._save_session_id(str(welcome.payload["session_id"]))
            status = self.service.run_once()
            await self._send(websocket, "RESOURCE_REPORT", status["resources"])
            await self._send(websocket, "DEVICE_REPORT", {"devices": status["devices"]})
            resource_digest = _payload_digest(status["resources"])
            device_digest = _payload_digest(status["devices"])
            loop = asyncio.get_running_loop()
            next_heartbeat = loop.time() + self.heartbeat_seconds

            while not stop_event.is_set():
                timeout = max(next_heartbeat - loop.time(), 0.001)
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
                else:
                    envelope = NodeProtocolEnvelope.from_json(raw)
                    if envelope.source != CONTROL_PLANE_ID:
                        raise NodeProtocolError("unexpected message source")
                    if envelope.target != self.service.identity.node_id:
                        raise NodeProtocolError("message addressed to another node")
                    if not envelope.verify(self.server_public_key):
                        raise NodeProtocolError(
                            "control-plane signature verification failed"
                        )
                    self._replay.accept(envelope)
                    await self._handle_message(websocket, envelope)
                if loop.time() < next_heartbeat:
                    continue
                status = self.service.run_once()
                await self._send(
                    websocket,
                    "HEARTBEAT",
                    {
                        "node_id": self.service.identity.node_id,
                        "status": "ONLINE",
                        "heartbeat_sequence": status["heartbeat_sequence"],
                    },
                )
                next_resource_digest = _payload_digest(status["resources"])
                if next_resource_digest != resource_digest:
                    await self._send(websocket, "RESOURCE_REPORT", status["resources"])
                    resource_digest = next_resource_digest
                next_device_digest = _payload_digest(status["devices"])
                if next_device_digest != device_digest:
                    await self._send(
                        websocket,
                        "DEVICE_REPORT",
                        {"devices": status["devices"]},
                    )
                    device_digest = next_device_digest
                next_heartbeat = loop.time() + self.heartbeat_seconds

    async def _handle_message(
        self, websocket: Any, envelope: NodeProtocolEnvelope
    ) -> None:
        if envelope.message_type == "WORKLOAD_START":
            workload_id = str(envelope.payload.get("workload_id", ""))
            if not workload_id or envelope.idempotency_key != workload_id:
                raise NodeProtocolError(
                    "workload idempotency key is missing or mismatched"
                )
            await self._send(
                websocket,
                "ACK",
                {"acknowledged": "WORKLOAD_START", "workload_id": workload_id},
                reply_to=envelope.message_id,
            )
            result = self.service.execute_workload(
                workload_id,
                str(envelope.payload.get("capability", "")),
                envelope.payload.get("arguments", {}),
                delivery_semantics=str(
                    envelope.payload.get("delivery_semantics", "idempotent")
                ),
                binding=envelope.payload.get("binding"),
            )
            await self._send(
                websocket,
                "WORKLOAD_STATUS",
                result,
                reply_to=envelope.message_id,
                idempotency_key=workload_id,
            )
        elif envelope.message_type == "WORKLOAD_STOP":
            workload_id = str(envelope.payload.get("workload_id", ""))
            result = self.service.stop_workload(workload_id)
            await self._send(
                websocket,
                "WORKLOAD_STATUS",
                result,
                reply_to=envelope.message_id,
                idempotency_key=workload_id,
            )
        elif envelope.message_type == "LEASE_ACQUIRE":
            lease = self.service.acquire_lease(
                str(envelope.payload.get("lease_id", "")),
                str(envelope.payload.get("resource_id", "")),
                envelope.payload.get("ttl_seconds", 0),
            )
            await self._send(
                websocket,
                "ACK",
                {"acknowledged": "LEASE_ACQUIRE", "lease": lease},
                reply_to=envelope.message_id,
                idempotency_key=envelope.idempotency_key,
            )
        elif envelope.message_type == "LEASE_RELEASE":
            lease = self.service.release_lease(
                str(envelope.payload.get("lease_id", "")),
                str(envelope.payload.get("resource_id", "")),
            )
            await self._send(
                websocket,
                "ACK",
                {"acknowledged": "LEASE_RELEASE", "lease": lease},
                reply_to=envelope.message_id,
                idempotency_key=envelope.idempotency_key,
            )
        elif envelope.message_type == "ARTIFACT_FETCH":
            try:
                chunk = base64.b64decode(
                    str(envelope.payload.get("chunk_b64", "")), validate=True
                )
                ready = self.service.ingest_artifact_chunk(
                    digest=str(envelope.payload.get("digest", "")),
                    transfer_id=str(envelope.payload.get("transfer_id", "")),
                    offset=envelope.payload.get("offset", -1),
                    content=chunk,
                    total_size=envelope.payload.get("total_size", -1),
                    artifact=dict(envelope.payload.get("artifact") or {}),
                    eof=envelope.payload.get("eof") is True,
                )
            except (ValueError, TypeError) as exc:
                await self._send(
                    websocket,
                    "ERROR",
                    {"code": "ARTIFACT_TRANSFER_REJECTED", "message": str(exc)},
                    reply_to=envelope.message_id,
                )
                return
            await self._send(
                websocket,
                "ARTIFACT_READY",
                ready,
                reply_to=envelope.message_id,
            )
        elif envelope.message_type not in {"ACK", "ERROR"}:
            await self._send(
                websocket,
                "ERROR",
                {"code": "UNSUPPORTED_MESSAGE", "message_type": envelope.message_type},
                reply_to=envelope.message_id,
            )

    async def _send(
        self,
        websocket: Any,
        message_type: str,
        payload: dict[str, Any],
        *,
        reply_to: str = "",
        idempotency_key: str = "",
    ) -> None:
        envelope = NodeProtocolEnvelope(
            message_type=message_type,
            source=self.service.identity.node_id,
            target=CONTROL_PLANE_ID,
            sequence=self._next_sequence(),
            payload=payload,
            reply_to=reply_to,
            idempotency_key=idempotency_key,
        ).sign(self.service.load_private_key())
        await websocket.send(envelope.to_json())

    async def _receive(self, websocket: Any) -> NodeProtocolEnvelope:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        envelope = NodeProtocolEnvelope.from_json(raw)
        if not envelope.verify(self.server_public_key):
            raise NodeProtocolError("control-plane signature verification failed")
        self._replay.accept(envelope)
        return envelope

    def _next_sequence(self) -> int:
        self._sequence += 1
        _atomic_json(self.sequence_path, {"sequence": self._sequence})
        return self._sequence

    def _load_sequence(self) -> int:
        value = _read_json(self.sequence_path)
        sequence = value.get("sequence", 0)
        return (
            sequence
            if isinstance(sequence, int) and not isinstance(sequence, bool)
            else 0
        )

    def _load_session_id(self) -> str:
        return str(_read_json(self.session_path).get("session_id", ""))

    def _save_session_id(self, session_id: str) -> None:
        _atomic_json(self.session_path, {"session_id": session_id})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _payload_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _observation_age_seconds(value: str) -> float | None:
    if not value:
        return None
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - observed).total_seconds(), 0.0)


def _normalize_node_architecture(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"aarch64", "arm64"}:
        return "arm64"
    if normalized in {"amd64", "x86-64", "x64"}:
        return "amd64"
    return normalized


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _is_gpu_device(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    spec = value.get("spec")
    if not isinstance(spec, dict):
        return False
    return str(spec.get("device_type", "")).upper() in {
        "CUDA",
        "ROCM",
        "METAL",
        "QNN",
        "VULKAN",
    }


def _artifact_uri_digest(reference: str) -> str:
    prefix = "artifact://sha256/"
    if not reference.startswith(prefix):
        raise DistributedWorkError(
            "dispatch input artifacts must use artifact://sha256/<digest>"
        )
    value = reference.removeprefix(prefix)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise DistributedWorkError("dispatch input Artifact digest is invalid")
    return f"sha256:{value}"


def _artifact_digest_uri(digest: str) -> str:
    if not digest.startswith("sha256:"):
        raise DistributedWorkError("committed Artifact digest is invalid")
    return f"artifact://sha256/{digest.removeprefix('sha256:')}"


def _work_result_summary(
    work: Any,
    payload: dict[str, Any],
    envelope: dict[str, Any],
    *,
    status: str,
    remote_receipt: dict[str, Any] | None = None,
    output_artifact: str = "",
    evidence_artifact: str = "",
) -> dict[str, Any]:
    return {
        "schema": "apeir.work-result-summary/v1",
        "work_id": work.work_id,
        "assignment_id": work.assignment.assignment_id if work.assignment else "",
        "node_id": str(envelope.get("source") or ""),
        "status": status,
        "node_result_state": str(payload.get("state") or ""),
        "signed_envelope_digest": _payload_digest(envelope),
        "output_artifact": output_artifact,
        "evidence_artifact": evidence_artifact,
        "remote_execution_receipt": dict(remote_receipt or {}),
        "reconciled_at": _utc_now(),
    }


def _verify_recorded_result(
    work: Any,
    payload: dict[str, Any],
    envelope: dict[str, Any],
    *,
    status: str,
) -> None:
    summary = work.result_summary
    if (
        summary.get("schema") != "apeir.work-result-summary/v1"
        or summary.get("work_id") != work.work_id
        or summary.get("assignment_id")
        != (work.assignment.assignment_id if work.assignment else "")
        or summary.get("node_id") != str(envelope.get("source") or "")
        or summary.get("status") != status
        or summary.get("node_result_state") != str(payload.get("state") or "")
        or summary.get("signed_envelope_digest") != _payload_digest(envelope)
    ):
        raise DistributedWorkError("recorded Work result binding changed")


def _verify_committed_artifacts(
    work: Any, artifact_store: ContentAddressedArtifactStore
) -> None:
    references = (*work.output_artifacts, *work.evidence_refs)
    if not references:
        raise DistributedWorkError("verified Work has no committed Artifacts")
    for reference in references:
        if not artifact_store.verify(_artifact_uri_digest(reference)):
            raise DistributedWorkError("committed Work Artifact verification failed")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_file(source: Path, target: Path) -> None:
    """Bound Windows sharing violations without weakening atomic replacement."""
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.01 * (attempt + 1))


def _workload_request_digest(request: dict[str, Any]) -> str:
    return workload_request_digest(
        request["capability"],
        request["arguments"],
        request["delivery_semantics"],
        request["binding"],
    )


def _verify_at_most_once_result(
    node_id: str, request: dict[str, Any], result: dict[str, Any]
) -> None:
    binding = request["binding"]
    if (
        result.get("workload_id") != request["workload_id"]
        or result.get("capability") != request["capability"]
        or result.get("binding") != binding
        or result.get("request_digest") != _workload_request_digest(request)
    ):
        raise NodeProtocolError("at-most-once result does not match assignment")
    if result.get("state") == "RECOVERY_REQUIRED":
        return
    receipt = result.get("receipt")
    if not isinstance(receipt, dict) or any(
        receipt.get(field) != value
        for field, value in {
            "operation_id": request["workload_id"],
            "actor": node_id,
            "node_id": node_id,
            "intent_id": binding["intent_id"],
            "effect_contract_digest": binding["effect_contract_digest"],
            "target_ref": binding["target_ref"],
            "target_binding_digest": binding["target_binding_digest"],
            "request_digest": result["request_digest"],
            "input_digest": hashlib.sha256(
                json.dumps(
                    request["arguments"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }.items()
    ):
        raise NodeProtocolError("at-most-once receipt does not match assignment")


def remote_execution_receipt(
    envelope_value: dict[str, Any], *, expected_operation_id: str = ""
) -> dict[str, Any]:
    """Project a signed Node result into the Kernel remote-receipt contract."""
    envelope = NodeProtocolEnvelope.from_json(
        json.dumps(envelope_value), check_time=False
    )
    payload = envelope.payload
    operation_id = str(payload.get("workload_id", ""))
    binding = payload.get("binding")
    receipt = payload.get("receipt")
    if (
        envelope.message_type != "WORKLOAD_STATUS"
        or envelope.idempotency_key != operation_id
        or (expected_operation_id and operation_id != expected_operation_id)
        or not isinstance(binding, dict)
        or not isinstance(receipt, dict)
        or payload.get("state") != "COMPLETED"
    ):
        raise NodeProtocolError("signed node result is not an accepted execution fact")
    required_binding = (
        "intent_id",
        "effect_contract_digest",
        "target_ref",
        "target_binding_digest",
        "workload_id",
        "request_digest",
        "provider_revision",
    )
    if not all(
        isinstance(binding.get(field), str) and binding[field]
        for field in required_binding
    ):
        raise NodeProtocolError("signed node result has incomplete Kernel binding")
    required_receipt = ("node_id", "executor", "effect_digest")
    if not all(
        isinstance(receipt.get(field), str) and receipt[field]
        for field in required_receipt
    ):
        raise NodeProtocolError("signed node result has incomplete execution receipt")
    if (
        receipt["node_id"] != envelope.source
        or receipt.get("operation_id") != operation_id
    ):
        raise NodeProtocolError("signed node result identity is inconsistent")
    envelope_digest = hashlib.sha256(
        json.dumps(
            envelope.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "workload_id": binding["workload_id"],
        "node_id": envelope.source,
        "executor_id": receipt["executor"],
        "intent_id": binding["intent_id"],
        "effect_contract_digest": binding["effect_contract_digest"],
        "target_ref": binding["target_ref"],
        "target_binding_digest": binding["target_binding_digest"],
        "request_digest": binding["request_digest"],
        "output_digest": receipt["effect_digest"],
        "provider_revision": binding["provider_revision"],
        "delivery_semantics": "AT_MOST_ONCE",
        "started_at": str(receipt.get("timestamps", {}).get("started_at", "")),
        "completed_at": str(receipt.get("timestamps", {}).get("finished_at", "")),
        "node_protocol_version": envelope.protocol_version,
        "signed_envelope_digest": envelope_digest,
        "signed_envelope": envelope.to_dict(),
    }


def _validate_relay_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise ValueError("relay URL must use ws:// or wss://")
    loopback = _is_loopback_host(parsed.hostname)
    if parsed.scheme != "wss" and not loopback:
        raise ValueError("remote relay connections require wss://")


def _is_loopback_host(host: str) -> bool:
    return host.lower() in {"localhost", "127.0.0.1", "::1"}


def _load_or_create_relay_key(state_dir: Path) -> Ed25519PrivateKey:
    state_dir.mkdir(parents=True, exist_ok=True)
    key_path = state_dir / "identity.ed25519.pem"
    if key_path.is_file():
        restrict_owner_only_file(key_path, subject="Controller identity private key")
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("relay identity key must be Ed25519")
        return key
    key = Ed25519PrivateKey.generate()
    temporary = key_path.with_suffix(key_path.suffix + ".tmp")
    temporary.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        restrict_owner_only_file(temporary, subject="Controller identity private key")
        temporary.replace(key_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return key

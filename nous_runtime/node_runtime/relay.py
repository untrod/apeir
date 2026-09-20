"""R2 authenticated WebSocket transport for Nous Node Protocol v1."""

from __future__ import annotations

import asyncio
import base64
import json
import random
import secrets
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore

from .protocol import (
    MAX_MESSAGE_BYTES,
    NODE_PROTOCOL_VERSION,
    NodeProtocolEnvelope,
    NodeProtocolError,
    ReplayWindow,
)
from .service import NodeRuntimeService

CONTROL_PLANE_ID = "control_plane"


def public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


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
        self.artifact_results: dict[str, dict[str, Any]] = {}
        self.lease_results: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self._replay = ReplayWindow()
        self._sequence = 0
        self._server: Any = None

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
            raise ValueError("relay trusted-node registry is invalid")
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
        return f"{scheme}://{self.host}:{port}"

    async def stop(self) -> None:
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
    ) -> None:
        if node_id not in self.node_keys:
            raise NodeProtocolError("node is not registered")
        request = {
            "workload_id": workload_id,
            "capability": capability,
            "arguments": dict(arguments or {}),
            "timeout_seconds": timeout_seconds,
        }
        self.pending.setdefault(node_id, {})[workload_id] = request
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
            {"lease_id": lease_id, "resource_id": resource_id, "ttl_seconds": ttl_seconds},
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
        self.pending.get(node_id, {}).pop(workload_id, None)
        await self._queue_control(
            node_id,
            "WORKLOAD_STOP",
            {"workload_id": workload_id},
            workload_id,
        )

    async def _queue_control(
        self,
        node_id: str,
        message_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> None:
        if node_id not in self.node_keys:
            raise NodeProtocolError("node is not registered")
        request = {
            "message_type": message_type,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        connection = self.connections.get(node_id)
        if connection is None:
            self.pending_controls.setdefault(node_id, []).append(request)
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
            if envelope.message_type != "REGISTER" or envelope.target != CONTROL_PLANE_ID:
                raise NodeProtocolError("REGISTER must be the first message")
            node_id = envelope.source
            public_key = self.node_keys.get(node_id, "")
            if not public_key or not envelope.verify(public_key):
                raise NodeProtocolError("node authentication failed")
            self._replay.accept(envelope)
            payload = envelope.payload
            if payload.get("node_id") != node_id:
                raise NodeProtocolError("registered identity does not match source")
            if NODE_PROTOCOL_VERSION not in payload.get("supported_versions", []):
                raise NodeProtocolError("no compatible protocol version")

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
            for request in list(self.pending.get(node_id, {}).values()):
                await self._send_workload(websocket, node_id, request)
            for digest, artifact in list(self.pending_artifacts.get(node_id, {}).items()):
                await self._send_artifact(websocket, node_id, digest, artifact)
            for request in self.pending_controls.pop(node_id, []):
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
                    raise NodeProtocolError("message route changed after authentication")
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
        if envelope.message_type in {"RESOURCE_REPORT", "DEVICE_REPORT", "TELEMETRY"}:
            self.reports.setdefault(node_id, {})[envelope.message_type] = envelope.payload
        elif envelope.message_type == "WORKLOAD_STATUS":
            workload_id = str(envelope.payload.get("workload_id", ""))
            if workload_id:
                self.results[workload_id] = envelope.payload
                self.pending.get(node_id, {}).pop(workload_id, None)
        elif envelope.message_type == "ARTIFACT_READY":
            digest = str(envelope.payload.get("digest", ""))
            if digest:
                self.artifact_results[digest] = envelope.payload
                if envelope.payload.get("state") == "READY":
                    self.pending_artifacts.get(node_id, {}).pop(digest, None)
        elif envelope.message_type == "ACK":
            lease = envelope.payload.get("lease")
            if isinstance(lease, dict) and lease.get("lease_id"):
                self.lease_results[str(lease["lease_id"])] = lease
        elif envelope.message_type not in {"HEARTBEAT", "ACK", "ERROR"}:
            await self._send(
                websocket,
                node_id,
                "ERROR",
                {"code": "UNSUPPORTED_DIRECTION", "message_type": envelope.message_type},
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
            if welcome.message_type != "ACK" or welcome.payload.get("acknowledged") != "REGISTER":
                raise NodeProtocolError("relay did not accept node registration")
            self._save_session_id(str(welcome.payload["session_id"]))
            status = self.service.run_once()
            await self._send(websocket, "RESOURCE_REPORT", status["resources"])
            await self._send(websocket, "DEVICE_REPORT", {"devices": status["devices"]})

            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(
                        websocket.recv(), timeout=self.heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    await self._send(
                        websocket,
                        "HEARTBEAT",
                        {
                            "node_id": self.service.identity.node_id,
                            "status": "ONLINE",
                            "heartbeat_sequence": self.service.run_once()[
                                "heartbeat_sequence"
                            ],
                        },
                    )
                    continue
                envelope = NodeProtocolEnvelope.from_json(raw)
                if envelope.source != CONTROL_PLANE_ID:
                    raise NodeProtocolError("unexpected message source")
                if envelope.target != self.service.identity.node_id:
                    raise NodeProtocolError("message addressed to another node")
                if not envelope.verify(self.server_public_key):
                    raise NodeProtocolError("control-plane signature verification failed")
                self._replay.accept(envelope)
                await self._handle_message(websocket, envelope)

    async def _handle_message(self, websocket: Any, envelope: NodeProtocolEnvelope) -> None:
        if envelope.message_type == "WORKLOAD_START":
            workload_id = str(envelope.payload.get("workload_id", ""))
            if not workload_id or envelope.idempotency_key != workload_id:
                raise NodeProtocolError("workload idempotency key is missing or mismatched")
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
        return sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else 0

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


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


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
    temporary.replace(key_path)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return key

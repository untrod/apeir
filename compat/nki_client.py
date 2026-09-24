"""
NKI v1 Python Client — Compatibility bridge between existing Nous Runtime
and the new Rust-based Nous AI Kernel.

This module provides a Python-native NKI client that communicates with nousd
over Unix Domain Sockets (Linux) or Named Pipes (Windows).

During migration, this client is used:
1. By the existing HTTP API as a backend (transparent to API consumers)
2. By the CLI as a drop-in replacement for direct function calls
3. By the desktop app through the existing API layer

Usage:
    async with NKIClient.connect() as client:
        workload = await client.submit_workload(spec)
        result = await client.get_workload(workload["uid"])
"""

import json
import os
import struct
import sys
import base64
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from urllib.parse import urlsplit

# NKI constants.

# NKI v3 — Reality Effect contracts, with v1/v2 envelope compatibility.
MIN_NKI_VERSION = 1
NKI_VERSION = 3
MAX_FRAME_BYTES = 16 * 1024 * 1024

if sys.platform == "win32":
    DEFAULT_ENDPOINT = r"\\.\pipe\nous\nousd"
else:
    DEFAULT_ENDPOINT = "/run/nous/nousd.sock"


# NKI errors.


class NKIError(Exception):
    """NKI protocol error."""

    def __init__(
        self,
        code: str,
        message: str,
        failed_phase: str = "",
        cause: str = "",
        retryable: bool = False,
        recommended_delay_ms: int = 0,
    ):
        self.code = code
        self.message = message
        self.failed_phase = failed_phase
        self.cause = cause
        self.retryable = retryable
        self.recommended_delay_ms = recommended_delay_ms
        super().__init__(f"[{code}] {message}")

    @classmethod
    def from_response(cls, error_body: dict) -> "NKIError":
        return cls(
            code=error_body["code"],
            message=error_body["message"],
            failed_phase=error_body.get("failed_phase", ""),
            cause=error_body.get("cause", ""),
            retryable=error_body.get("retryable", False),
            recommended_delay_ms=error_body.get("recommended_delay_ms", 0),
        )


# NKI client.


@dataclass
class NKIRequest:
    """An NKI request envelope."""

    method: str
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    idempotency_key: str = ""
    principal_id: str = "nous-runtime"
    namespace: str = "default"
    deadline_us: int = 0
    traceparent: str = ""
    tracestate: str = ""

    def to_dict(self) -> Dict[str, Any]:
        import uuid

        if not self.request_id:
            self.request_id = str(uuid.uuid4())
        return {
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key or str(uuid.uuid4()),
            "nki_version": NKI_VERSION,
            "principal_id": self.principal_id,
            "session_token": os.environ.get("NOUS_NKI_TOKEN", ""),
            "namespace": self.namespace,
            "deadline_us": self.deadline_us,
            "traceparent": self.traceparent,
            "tracestate": self.tracestate,
            "feature_flags": [],
            "method": self.method,
            "payload": base64.b64encode(
                json.dumps(self.payload).encode("utf-8")
            ).decode("ascii"),
        }


class NKIClient:
    """
    Python NKI client for communicating with nousd.

    Supports:
    - Unix Domain Socket (Linux)
    - Windows Named Pipe (Windows)
    - TCP (for remote connections)

    All methods are async and return typed dictionaries matching
    the protobuf schema in spec/nki/v1/nki.proto.
    """

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, principal_id: str = "nous-runtime"):
        self._endpoint = endpoint
        if not principal_id.strip():
            raise ValueError("NKI principal_id is required")
        self._principal_id = principal_id
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    @classmethod
    async def connect(
        cls, endpoint: str = DEFAULT_ENDPOINT, principal_id: str = "nous-runtime"
    ) -> "NKIClient":
        """Connect to nousd and return a ready client."""
        client = cls(endpoint, principal_id=principal_id)
        await client._connect()
        return client

    async def _connect(self):
        """Establish transport connection."""
        if self._endpoint.startswith("tcp://"):
            endpoint = urlsplit(self._endpoint)
            if not endpoint.hostname or not endpoint.port:
                raise NKIError("INVALID_ENDPOINT", "NKI TCP endpoint is invalid")
            host, port = endpoint.hostname, endpoint.port
            self._reader, self._writer = await asyncio.open_connection(host, port)
        elif sys.platform == "win32":
            host = os.environ.get("NOUS_HOST", "127.0.0.1")
            port = int(os.environ.get("NOUS_PORT", "8771"))
            self._reader, self._writer = await asyncio.open_connection(host, port)
        else:
            self._reader, self._writer = await asyncio.open_unix_connection(
                self._endpoint
            )

    async def close(self):
        """Close the connection."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()

    async def __aenter__(self):
        await self._connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _request(
        self, method: str, payload: Dict[str, Any] = None, idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Send an NKI request and return the response payload."""
        req = NKIRequest(
            method=method,
            payload=payload or {},
            idempotency_key=idempotency_key,
            principal_id=self._principal_id,
        )
        return await self._send(req)

    async def _send(self, request: NKIRequest) -> Dict[str, Any]:
        """Send a framed NKI request and read the response."""
        if not self._writer:
            raise NKIError("CONNECTION_FAILED", "Not connected to nousd")

        # Encode as JSON with length prefix
        body = json.dumps(request.to_dict(), separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_FRAME_BYTES:
            raise NKIError("FRAME_TOO_LARGE", "NKI request exceeds 16 MiB")
        framed = struct.pack(">I", len(body)) + body

        self._writer.write(framed)
        await self._writer.drain()

        # Read response: 4-byte length prefix + JSON
        if not self._reader:
            raise NKIError("CONNECTION_FAILED", "Reader not available")

        len_bytes = await self._reader.readexactly(4)
        resp_len = struct.unpack(">I", len_bytes)[0]
        if resp_len > MAX_FRAME_BYTES:
            raise NKIError("FRAME_TOO_LARGE", "NKI response exceeds 16 MiB")
        resp_bytes = await self._reader.readexactly(resp_len)
        response = json.loads(resp_bytes)

        if response.get("request_id") != request.request_id:
            raise NKIError("PROTOCOL_ERROR", "NKI response request_id mismatch")
        response_version = response.get("nki_version")
        if not isinstance(response_version, int) or not (
            MIN_NKI_VERSION <= response_version <= NKI_VERSION
        ):
            raise NKIError("PROTOCOL_ERROR", "NKI response version is unsupported")

        # Check for error (tagged enum: status field indicates success/error)
        if response.get("status") == "error":
            raise NKIError.from_response(response["error"])

        return response.get("payload", response)

    # Workload management.

    async def submit_workload(
        self, spec: Dict[str, Any], idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Submit a workload for execution. Returns {workload_id, phase, resource_version}.

        C1 fix: idempotency_key is passed BOTH in the envelope AND injected into
        the WorkloadSpec payload (the server reads spec.idempotency_key for dedup).
        """
        payload_spec = dict(spec)
        if idempotency_key and not payload_spec.get("idempotency_key"):
            payload_spec["idempotency_key"] = idempotency_key
        return await self._request(
            "SubmitWorkload", {"workload": payload_spec}, idempotency_key
        )

    async def execute_operation(
        self, operation: Dict[str, Any], idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Execute one complete Runtime operation through the production kernel path."""
        return await self._request("SubmitWorkload", operation, idempotency_key)

    async def get_workload(self, workload_id: str) -> Dict[str, Any]:
        """Get the current state of a workload."""
        return await self._request("GetWorkload", {"workload_id": workload_id})

    async def list_workloads(
        self,
        namespace: str = "default",
        filters: List[Dict] = None,
        page_size: int = 50,
        page_token: str = "",
    ) -> Dict[str, Any]:
        """List workloads in a namespace."""
        return await self._request(
            "ListWorkloads",
            {
                "namespace": namespace,
                "filters": filters or [],
                "page_size": page_size,
                "page_token": page_token,
            },
        )

    async def cancel_workload(
        self, workload_id: str, reason: str = "", force: bool = False
    ) -> Dict[str, Any]:
        """Cancel a running workload."""
        return await self._request(
            "CancelWorkload",
            {
                "workload_id": workload_id,
                "reason": reason,
                "force": force,
            },
        )

    async def pause_workload(self, workload_id: str) -> Dict[str, Any]:
        """Pause a running workload."""
        return await self._request("PauseWorkload", {"workload_id": workload_id})

    async def resume_workload(self, workload_id: str) -> Dict[str, Any]:
        """Resume a paused workload."""
        return await self._request("ResumeWorkload", {"workload_id": workload_id})

    # Admission and resources.

    async def admit_workload(self, workload_id: str) -> Dict[str, Any]:
        """Check if a workload can be admitted."""
        return await self._request("AdmitWorkload", {"workload_id": workload_id})

    async def admit_extension(
        self, admission: Dict[str, Any], idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Submit a normalized extension to the authoritative Kernel."""
        return await self._request("AdmitExtension", admission, idempotency_key)

    async def authorize_extension(
        self, authorization: Dict[str, Any], idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Bind a Runtime approval to an existing Kernel admission receipt."""
        return await self._request(
            "AuthorizeExtension", authorization, idempotency_key
        )

    async def authorize_extension_execution(
        self, execution: Dict[str, Any], idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Request a parameter-bound, per-invocation permit from Kernel."""
        return await self._request(
            "AuthorizeExtensionExecution", execution, idempotency_key
        )

    async def revoke_extension(
        self, revocation: Dict[str, Any], idempotency_key: str = ""
    ) -> Dict[str, Any]:
        """Revoke a digest-bound extension authorization in Kernel."""
        return await self._request("RevokeExtension", revocation, idempotency_key)

    async def reserve_resources(
        self,
        workload_id: str,
        resources: Dict[str, Any],
        preferred_node: str = "",
        preferred_device: str = "",
    ) -> Dict[str, Any]:
        """Reserve resources for a workload."""
        return await self._request(
            "ReserveResources",
            {
                "workload_id": workload_id,
                "resources": resources,
                "preferred_node_id": preferred_node,
                "preferred_device_id": preferred_device,
            },
        )

    async def release_resources(self, lease_id: str) -> Dict[str, Any]:
        """Release reserved resources."""
        return await self._request("ReleaseResources", {"lease_id": lease_id})

    async def renew_lease(
        self, lease_id: str, expected_generation: int = 0, extend_duration_us: int = 0
    ) -> Dict[str, Any]:
        """H3: Renew a workload's resource lease before expiry."""
        return await self._request(
            "RenewLease",
            {
                "lease_id": lease_id,
                "expected_generation": expected_generation,
                "extend_duration_us": extend_duration_us,
            },
        )

    # Model management.

    async def register_model(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """Register a model package."""
        return await self._request("RegisterModel", {"model": model})

    async def validate_model(self, model_id: str) -> Dict[str, Any]:
        """Validate a registered model."""
        return await self._request("ValidateModel", {"model_id": model_id})

    async def load_model(
        self,
        model_id: str,
        engine_id: str = "",
        device_id: str = "",
        options: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Load a model onto an engine."""
        return await self._request(
            "LoadModel",
            {
                "model_id": model_id,
                "engine_id": engine_id,
                "device_id": device_id,
                "options": options or {},
            },
        )

    async def unload_model(self, instance_id: str) -> Dict[str, Any]:
        """Unload a model instance."""
        return await self._request("UnloadModel", {"instance_id": instance_id})

    # Engine management.

    async def register_engine(
        self, engine: Dict[str, Any], process_id: str = ""
    ) -> Dict[str, Any]:
        """Register an inference engine."""
        return await self._request(
            "RegisterEngine",
            {
                "engine": engine,
                "process_id": process_id,
            },
        )

    async def probe_engine(self, engine_id: str) -> Dict[str, Any]:
        """Probe engine health."""
        return await self._request("ProbeEngine", {"engine_id": engine_id})

    async def list_engines(self, namespace: str = "default") -> Dict[str, Any]:
        """List registered engines."""
        return await self._request("ListEngines", {"namespace": namespace})

    # Device management.

    async def register_device(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Register a hardware device."""
        return await self._request("RegisterDevice", {"device": device})

    async def probe_device(self, device_id: str) -> Dict[str, Any]:
        """Probe device health."""
        return await self._request("ProbeDevice", {"device_id": device_id})

    async def list_devices(self, namespace: str = "default") -> Dict[str, Any]:
        """List registered devices."""
        return await self._request("ListDevices", {"namespace": namespace})

    # State and recovery.

    async def create_checkpoint(
        self, workload_id: str, description: str = ""
    ) -> Dict[str, Any]:
        """Create a checkpoint for a workload."""
        return await self._request(
            "CreateCheckpoint",
            {
                "workload_id": workload_id,
                "description": description,
            },
        )

    async def restore_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        """Restore a workload from a checkpoint."""
        return await self._request(
            "RestoreCheckpoint",
            {
                "checkpoint_id": checkpoint_id,
            },
        )

    # Observability.

    async def watch_events(
        self,
        namespace: str = "default",
        event_types: List[str] = None,
        follow: bool = False,
    ) -> Dict[str, Any]:
        """Watch for events."""
        return await self._request(
            "WatchEvents",
            {
                "namespace": namespace,
                "event_types": event_types or [],
                "from_resource_version": "",
                "follow": follow,
            },
        )

    async def get_trace(self, trace_id: str) -> Dict[str, Any]:
        """Get trace by ID."""
        return await self._request("GetTrace", {"trace_id": trace_id})

    async def get_metrics(
        self,
        namespace: str = "default",
        metric_name: str = "",
        start_us: int = 0,
        end_us: int = 0,
    ) -> Dict[str, Any]:
        """Get metrics."""
        return await self._request(
            "GetMetrics",
            {
                "namespace": namespace,
                "metric_name": metric_name,
                "start_us": start_us,
                "end_us": end_us,
            },
        )

    # Health.

    async def health_check(self, deep: bool = False) -> Dict[str, Any]:
        """Check kernel health."""
        return await self._request("HealthCheck", {"deep": deep})


# Compatibility layer.


class CompatibilityFacade:
    """
    Provides backward-compatible wrappers that translate old Nous Runtime
    API calls into NKI requests.

    This allows existing code (CLI, HTTP API, desktop) to work unchanged
    while routing through the new kernel.
    """

    def __init__(self, nki_client: NKIClient):
        self._nki = nki_client

    async def runtime_run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compatibility wrapper for the old RuntimeRequest → RuntimeResponse flow.

        Maps old RuntimeRequest fields to a WorkloadSpec and submits via NKI.
        """
        # Map old fields to WorkloadSpec
        spec = {
            "goal": request.get("input_text", ""),
            "workload_type": self._map_workload_type(request),
            "model_requirements": {
                "allowed_model_families": request.get("allowed_models", []),
                "max_tokens_per_request": request.get("max_tokens", 4096),
                "min_context_length": request.get("min_context_length", 0),
            },
            "execution_graph": self._build_simple_graph(request),
            "output_contract": {
                "format": "Text",
                "max_output_tokens": request.get("max_tokens", 4096),
                "include_reasoning": request.get("include_reasoning", False),
            },
            "checkpoint_policy": {
                "enabled": request.get("checkpoint_enabled", False),
                "strategy": "BeforeRiskyPhase",
            },
            "retry_policy": {
                "max_retries": request.get("max_retries", 3),
                "initial_backoff_ms": 100,
                "max_backoff_ms": 10000,
                "backoff_multiplier": 2.0,
                "retry_on_timeout": True,
            },
        }

        result = await self._nki.submit_workload(spec)

        # Wait for completion
        workload = await self._nki.get_workload(result["workload_id"])

        # Map back to old RuntimeResponse format
        return self._map_to_legacy_response(workload)

    def _map_workload_type(self, request: Dict[str, Any]) -> str:
        """Map old request mode to WorkloadType."""
        mode = request.get("mode", "chat")
        mapping = {
            "chat": "CHAT",
            "completion": "COMPLETION",
            "structured": "STRUCTURED_OUTPUT",
            "embedding": "EMBEDDING",
            "agent": "AGENT_PROGRAM",
            "workflow": "WORKFLOW",
            "tool": "TOOL_EXECUTION",
            "retrieval": "RETRIEVAL",
        }
        return mapping.get(mode, "CHAT")

    def _build_simple_graph(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Build a simple linear execution graph for basic requests."""
        nodes = [
            {"node_id": "recv", "phase_type": "RECEIVE"},
            {"node_id": "ctx", "phase_type": "RESOLVE_CONTEXT"},
        ]

        if request.get("mode") == "retrieval":
            nodes.append({"node_id": "retrieve", "phase_type": "RETRIEVE"})

        nodes.extend(
            [
                {"node_id": "tokenize", "phase_type": "TOKENIZE"},
                {"node_id": "prefill", "phase_type": "PREFILL"},
                {"node_id": "decode", "phase_type": "DECODE"},
                {"node_id": "finalize", "phase_type": "FINALIZE"},
            ]
        )

        edges = []
        for i in range(len(nodes) - 1):
            edges.append(
                {
                    "from_node_id": nodes[i]["node_id"],
                    "to_node_id": nodes[i + 1]["node_id"],
                }
            )

        return {
            "nodes": nodes,
            "edges": edges,
            "entry_node_id": nodes[0]["node_id"],
        }

    def _map_to_legacy_response(self, workload: Dict[str, Any]) -> Dict[str, Any]:
        """Map a Workload status back to the old RuntimeResponse format.

        C2 fix: Handles BOTH response shapes:
        - Proto nested shape: {meta: {uid, ...}, spec: {...}, status: {phase, ...}}
        - Server flat shape:   {workload_id, phase, generation, spec, lease, ...}
        """
        # Try proto nested shape first
        if "meta" in workload and "status" in workload:
            status = workload.get("status", {})
            return {
                "run_id": workload.get("meta", {}).get("uid", ""),
                "phase": status.get("phase", "UNKNOWN"),
                "output_text": "",
                "metrics": status.get("metrics", {}),
                "error": status.get("error"),
                "events": [],
                "artifacts": [],
            }
        # Fall back to server flat shape
        return {
            "run_id": workload.get("workload_id", ""),
            "phase": workload.get("phase", "UNKNOWN"),
            "output_text": "",
            "metrics": workload.get("metrics", {}),
            "error": workload.get("error"),
            "events": [],
            "artifacts": [],
        }


# Convenience functions.


async def connect_to_kernel(endpoint: str = None) -> NKIClient:
    """Connect to the local Nous Kernel daemon."""
    ep = endpoint or os.environ.get("NOUS_KERNEL_ENDPOINT", DEFAULT_ENDPOINT)
    return await NKIClient.connect(ep)

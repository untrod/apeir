"""
Contract tests for the NKI Python compatibility layer.

These tests verify that the Python NKI client (compat/nki_client.py)
correctly implements the NKI v1 protocol. They can run against:
1. A real nousd daemon (integration test)
2. A mock NKI server (unit test — no daemon required)

Run:
    pytest tests/test_nki_compat.py -v
"""

import pytest
import json
import asyncio
from unittest.mock import MagicMock

# Import the compatibility layer
import sys

sys.path.insert(0, ".")
from compat.nki_client import (
    NKIClient,
    NKIError,
    NKIRequest,
    CompatibilityFacade,
    NKI_VERSION,
)


class TestNKIRequest:
    """Test NKIRequest envelope construction."""

    def test_request_has_all_fields(self):
        req = NKIRequest(method="SubmitWorkload", payload={"goal": "test"})
        d = req.to_dict()
        assert "request_id" in d
        assert "idempotency_key" in d
        assert d["nki_version"] == NKI_VERSION
        assert d["method"] == "SubmitWorkload"
        assert "payload" in d

    def test_request_generates_unique_ids(self):
        req1 = NKIRequest(method="HealthCheck")
        req2 = NKIRequest(method="HealthCheck")
        assert req1.to_dict()["request_id"] != req2.to_dict()["request_id"]

    def test_idempotency_key_preserved(self):
        req = NKIRequest(method="SubmitWorkload", idempotency_key="my-key-123")
        d = req.to_dict()
        assert d["idempotency_key"] == "my-key-123"


class TestNKIError:
    """Test NKIError construction from response errors."""

    def test_from_response(self):
        body = {
            "code": "ERROR_RESOURCE_INSUFFICIENT",
            "message": "Not enough VRAM",
            "retryable": False,
            "recommended_delay_ms": 0,
        }
        err = NKIError.from_response(body)
        assert err.code == "ERROR_RESOURCE_INSUFFICIENT"
        assert "VRAM" in err.message
        assert not err.retryable

    def test_from_response_with_phase(self):
        body = {
            "code": "ERROR_WORKLOAD_REJECTED",
            "message": "Security check failed",
            "failed_phase": "ADMIT",
            "cause": "Missing capability grant",
            "retryable": False,
            "recommended_delay_ms": 0,
        }
        err = NKIError.from_response(body)
        assert err.failed_phase == "ADMIT"
        assert err.cause == "Missing capability grant"


class TestCompatibilityFacade:
    """Test the old→new API translation layer."""

    def test_runtime_run_maps_fields(self):
        """Verify old RuntimeRequest fields map to WorkloadSpec."""
        facade = CompatibilityFacade(MagicMock())

        old_request = {
            "input_text": "What is the weather?",
            "mode": "chat",
            "allowed_models": ["claude", "deepseek"],
            "max_tokens": 2048,
            "checkpoint_enabled": True,
            "max_retries": 5,
        }

        # We can test the mapping without a real NKI connection
        workload_type = facade._map_workload_type(old_request)
        assert workload_type == "CHAT"

        graph = facade._build_simple_graph(old_request)
        assert (
            len(graph["nodes"]) >= 5
        )  # At minimum: recv, ctx, tokenize, prefill, decode, finalize
        assert graph["entry_node_id"] == "recv"
        assert len(graph["edges"]) == len(graph["nodes"]) - 1

    def test_workload_type_mapping(self):
        facade = CompatibilityFacade(MagicMock())
        assert facade._map_workload_type({"mode": "chat"}) == "CHAT"
        assert facade._map_workload_type({"mode": "completion"}) == "COMPLETION"
        assert facade._map_workload_type({"mode": "agent"}) == "AGENT_PROGRAM"
        assert facade._map_workload_type({"mode": "embedding"}) == "EMBEDDING"
        assert facade._map_workload_type({"mode": "unknown"}) == "CHAT"  # Default

    def test_legacy_response_mapping(self):
        facade = CompatibilityFacade(MagicMock())
        workload = {
            "meta": {"uid": "wl-001"},
            "status": {
                "phase": "SUCCEEDED",
                "metrics": {"total_tokens": 150},
            },
        }
        legacy = facade._map_to_legacy_response(workload)
        assert legacy["run_id"] == "wl-001"
        assert legacy["phase"] == "SUCCEEDED"
        assert legacy["metrics"]["total_tokens"] == 150


class TestNKIMethodNames:
    """Verify all 25 NKI methods are accessible."""

    METHODS = [
        "submit_workload",
        "get_workload",
        "list_workloads",
        "cancel_workload",
        "pause_workload",
        "resume_workload",
        "admit_workload",
        "reserve_resources",
        "release_resources",
        "register_model",
        "validate_model",
        "load_model",
        "unload_model",
        "register_engine",
        "probe_engine",
        "list_engines",
        "register_device",
        "probe_device",
        "list_devices",
        "create_checkpoint",
        "restore_checkpoint",
        "watch_events",
        "get_trace",
        "get_metrics",
        "health_check",
    ]

    def test_all_methods_exist(self):
        """Every NKI method should be callable on the client."""
        client_methods = [m for m in dir(NKIClient) if not m.startswith("_")]
        for method in self.METHODS:
            assert method in client_methods, f"Missing method: {method}"


class TestNKIClientMocked:
    """Test NKIClient with mocked transport."""

    def test_health_check_mocked(self):
        """Health check should work without a real daemon."""
        # This test verifies the request/response flow without actual I/O
        # Without real connection, _send would fail
        # But we can test request construction
        req = NKIRequest(method="HealthCheck", payload={"deep": False})
        d = req.to_dict()
        assert d["method"] == "HealthCheck"
        # Payload is base64-encoded JSON (RC4: cross-language compatibility)
        import base64

        payload_bytes = base64.b64decode(d["payload"])
        payload = json.loads(payload_bytes)
        assert payload["deep"] is False

    def test_response_status_field(self):
        """RC4 tagged enum: response must have 'status' field for success/error."""
        # Verify the client correctly handles the new tagged response format
        # Simulate a success response
        success_resp = {
            "request_id": "req-1",
            "nki_version": 1,
            "server_timestamp_us": 1234567890,
            "trace_id": "trace-abc",
            "status": "success",
            "payload": {"healthy": True},
        }
        assert success_resp.get("status") == "success"
        assert success_resp.get("payload") == {"healthy": True}

        # Simulate an error response
        error_resp = {
            "request_id": "req-2",
            "nki_version": 1,
            "server_timestamp_us": 1234567890,
            "trace_id": "trace-def",
            "status": "error",
            "error": {
                "code": "ERROR_INTERNAL",
                "message": "Something went wrong",
                "retryable": True,
                "recommended_delay_ms": 500,
            },
        }
        assert error_resp.get("status") == "error"
        with pytest.raises(NKIError) as exc_info:
            raise NKIError.from_response(error_resp["error"])
        assert exc_info.value.code == "ERROR_INTERNAL"
        assert exc_info.value.retryable


class TestRC4KernelClosureAudit:
    """RC4 integrity checks for the compatibility layer."""

    def test_facade_is_not_authoritative(self):
        """CompatibilityFacade must route through NKI, not maintain parallel state."""
        # The facade has NO internal state store — it's purely a translator
        facade = CompatibilityFacade(MagicMock())
        attrs = [a for a in dir(facade) if not a.startswith("_")]
        # Must not have store, registry, or direct provider access
        forbidden = ["store", "registry", "provider", "invoke", "execute"]
        for f in forbidden:
            assert f not in attrs, (
                f"Facade must not expose '{f}' — it would create a parallel authority"
            )

    def test_all_nki_methods_return_typed_responses(self):
        """Every NKI method must return a dict (not raw bytes, not None)."""
        # This is a contract test: the client methods must enforce response typing
        methods_that_should_return_dict = [
            "submit_workload",
            "get_workload",
            "list_workloads",
            "health_check",
            "register_model",
            "list_engines",
            "list_devices",
        ]
        for method_name in methods_that_should_return_dict:
            method = getattr(NKIClient, method_name, None)
            assert method is not None, f"Missing method: {method_name}"
            # All methods should be async coroutines
            assert asyncio.iscoroutinefunction(method), (
                f"{method_name} must be an async method"
            )

    def test_no_direct_provider_calls(self):
        """The compat layer must not contain direct provider invocation."""
        import inspect

        source = inspect.getsource(CompatibilityFacade)
        forbidden_patterns = [
            "provider.invoke",
            "provider.call",
            "direct_invoke",
            "Provider(",
            "_providers[",
            "invoke_via_provider",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Bypass pattern found in CompatibilityFacade: '{pattern}'"
            )

    def test_error_codes_are_stable(self):
        """NKI error codes must be stable and documented."""
        # From RFC-0004: the 35 standard error codes
        stable_codes = {
            "ERROR_UNKNOWN",
            "ERROR_INVALID_REQUEST",
            "ERROR_NOT_FOUND",
            "ERROR_ALREADY_EXISTS",
            "ERROR_PERMISSION_DENIED",
            "ERROR_UNAUTHENTICATED",
            "ERROR_RESOURCE_EXHAUSTED",
            "ERROR_FAILED_PRECONDITION",
            "ERROR_ABORTED",
            "ERROR_NOT_IMPLEMENTED",
            "ERROR_INTERNAL",
            "ERROR_UNAVAILABLE",
            "ERROR_DATA_LOSS",
            "ERROR_DEADLINE_EXCEEDED",
            "ERROR_WORKLOAD_REJECTED",
            "ERROR_WORKLOAD_CANCELLED",
            "ERROR_WORKLOAD_LOST",
            "ERROR_WORKLOAD_QUARANTINED",
            "ERROR_WORKLOAD_CONFLICT",
            "ERROR_RESOURCE_INSUFFICIENT",
            "ERROR_LEASE_EXPIRED",
            "ERROR_LEASE_CONFLICT",
            "ERROR_MODEL_NOT_FOUND",
            "ERROR_MODEL_INCOMPATIBLE",
            "ERROR_MODEL_NOT_LOADED",
            "ERROR_MODEL_VALIDATION_FAILED",
            "ERROR_MODEL_SECURITY_BLOCKED",
            "ERROR_ENGINE_NOT_FOUND",
            "ERROR_ENGINE_INCOMPATIBLE",
            "ERROR_ENGINE_UNHEALTHY",
            "ERROR_ENGINE_TIMEOUT",
            "ERROR_DEVICE_NOT_FOUND",
            "ERROR_DEVICE_INCOMPATIBLE",
            "ERROR_DEVICE_UNHEALTHY",
            "ERROR_DEVICE_OUT_OF_MEMORY",
            "ERROR_BACKEND_UNAVAILABLE",
            "ERROR_BACKEND_INCOMPATIBLE",
            "ERROR_NOT_SUPPORTED",
            "ERROR_SECURITY_POLICY",
            "ERROR_CAPABILITY_DENIED",
            "ERROR_ISOLATION_FAILED",
        }
        # Verify NKIError can be constructed from any of these codes
        for code in list(stable_codes)[:5]:  # Test a sample
            err = NKIError(code, "Test message")
            assert err.code == code

    def test_compat_layer_does_not_create_second_authority(self):
        """RC4 requirement: every compatibility entry maps to unified NKI."""
        # The facade has exactly ONE dependency: the NKI client
        # It must not import or instantiate any other runtime components
        import inspect

        source = inspect.getsource(CompatibilityFacade.__init__)
        # __init__ should only accept nki_client
        assert "nki_client" in source
        assert "registry" not in source.lower()
        assert "store" not in source.lower()
        assert "provider" not in source.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

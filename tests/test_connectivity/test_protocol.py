# -*- coding: utf-8 -*-
"""Protocol contract tests — serialization, validation, redaction."""

import pytest

from nous_runtime.connectivity.protocol.envelope import ProtocolEnvelope
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.connectivity.protocol.pairing import (
    PairingCode, generate_pairing_code, hash_pairing_code, PAIRING_CODE_LENGTH,
)
from nous_runtime.connectivity.protocol.task import (
    TaskState, TaskSubmission, TaskResult, VALID_TRANSITIONS,
)
from nous_runtime.connectivity.protocol.error import ErrorCode, ProtocolError
from nous_runtime.connectivity.protocol.serialization import (
    redacted_serialization,
    validate_bounded_payload,
)


class TestProtocolEnvelope:
    """Envelope serialization, validation, signing."""

    def test_create_and_serialize(self):
        env = ProtocolEnvelope(
            message_type="HELLO",
            source_id="node_1",
            target_id="control_plane",
            payload={"test": "data"},
        )
        d = env.to_dict()
        assert d["schema_version"] == "1.0"
        assert d["protocol_version"] == "1.0"
        assert d["message_type"] == "HELLO"
        assert d["message_id"]

    def test_roundtrip(self):
        env = ProtocolEnvelope(
            message_type="HELLO",
            source_id="node_1",
            target_id="control_plane",
            payload={"key": "value"},
        )
        json_str = env.to_json()
        parsed = ProtocolEnvelope.from_json(json_str)
        assert parsed.message_id == env.message_id
        assert parsed.message_type == env.message_type
        assert parsed.payload == env.payload

    def test_deterministic_json(self):
        # Same logical data should produce identical JSON
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        from nous_runtime.connectivity.protocol.serialization import deterministic_json
        json1 = deterministic_json(d1)
        json2 = deterministic_json(d2)
        assert json1 == json2

    def test_validation_valid(self):
        env = ProtocolEnvelope(message_type="HELLO", source_id="a", target_id="b")
        valid, err = env.is_valid()
        assert valid, err

    def test_validation_missing_fields(self):
        env = ProtocolEnvelope()
        valid, err = env.is_valid()
        assert not valid

    def test_validation_unknown_type(self):
        env = ProtocolEnvelope(message_type="INVALID_TYPE", source_id="a", target_id="b")
        valid, err = env.is_valid()
        assert not valid

    def test_validation_version_mismatch(self):
        env = ProtocolEnvelope(
            message_type="HELLO", source_id="a", target_id="b",
            schema_version="99.0",
        )
        valid, err = env.is_valid()
        assert not valid

    def test_signing_and_verification(self):
        env = ProtocolEnvelope(message_type="HEARTBEAT", source_id="node_1", target_id="cp")
        env.sign("secret_key")
        assert env.signature
        assert env.verify("secret_key")
        assert not env.verify("wrong_key")

    def test_redacted_serialization(self):
        env = ProtocolEnvelope(
            message_type="PAIRING_REQUEST",
            source_id="node_1",
            target_id="cp",
            payload={"pairing_code": "ABCD1234", "api_key": "sk-secret123"},
        )
        redacted = env.to_redacted_dict()
        assert redacted["payload"]["pairing_code"] == "<REDACTED>"
        assert redacted["payload"]["api_key"] == "<REDACTED>"

    def test_expiration(self):
        env = ProtocolEnvelope(
            message_type="HEARTBEAT", source_id="a", target_id="b",
            expires_at="2020-01-01T00:00:00Z",
        )
        assert env.is_expired()

    def test_hash_determinism(self):
        from nous_runtime.connectivity.protocol.serialization import deterministic_hash
        h1 = deterministic_hash({"x": 1, "y": 2})
        h2 = deterministic_hash({"y": 2, "x": 1})
        assert h1 == h2

    def test_oversized_payload_rejected(self):
        with pytest.raises(ValueError):
            validate_bounded_payload("x" * 2_000_000, max_bytes=1_000_000)


class TestNodeIdentity:
    def test_create_and_serialize(self):
        identity = NodeIdentity.create(
            node_name="test", node_role="personal_node",
            platform_os="Linux", platform_os_version="5.15",
            platform_arch="x86_64", platform_hostname="test-host",
            public_key="abc123", capabilities=["system.echo"],
        )
        d = identity.to_dict()
        assert d["node_id"].startswith("node_")
        assert d["node_name"] == "test"
        assert d["platform"]["os"] == "Linux"

    def test_roundtrip(self):
        identity = NodeIdentity.create(
            node_name="test", node_role="personal_node",
            platform_os="Linux", platform_os_version="5.15",
            platform_arch="x86_64", platform_hostname="test-host",
            public_key="abc123",
        )
        d = identity.to_dict()
        parsed = NodeIdentity.from_dict(d)
        assert parsed.node_id == identity.node_id
        assert parsed.node_name == identity.node_name

    def test_immutable(self):
        identity = NodeIdentity.create(
            node_name="test", node_role="personal_node",
            platform_os="Linux", platform_os_version="5.15",
            platform_arch="x86_64", platform_hostname="test-host",
            public_key="abc123",
        )
        with pytest.raises(Exception):
            identity.node_name = "changed"  # frozen dataclass


class TestPairingCode:
    def test_generate(self):
        code = generate_pairing_code()
        assert len(code) == PAIRING_CODE_LENGTH
        assert all(c in "ABCDEFGHJKMNPQRSTUVWXYZ23456789" for c in code)

    def test_create_and_verify(self):
        plaintext, code = PairingCode.create()
        assert code.verify(plaintext)
        assert not code.verify("WRONG123")

    def test_expiration(self):
        plaintext, code = PairingCode.create()
        assert not code.is_expired()

    def test_attempts(self):
        plaintext, code = PairingCode.create()
        assert code.attempts == 0
        code2 = code.with_attempt()
        assert code2.attempts == 1

    def test_hash_determinism(self):
        h1 = hash_pairing_code("ABCDEFGH")
        h2 = hash_pairing_code("ABCDEFGH")
        assert h1 == h2
        assert h1 != hash_pairing_code("ABCDEFGX")


class TestTaskStateMachine:
    def test_valid_transitions(self):
        assert TaskState.COMPLETED in VALID_TRANSITIONS[TaskState.RUNNING]
        assert TaskState.FAILED in VALID_TRANSITIONS[TaskState.RUNNING]
        assert TaskState.RUNNING in VALID_TRANSITIONS[TaskState.ACCEPTED]

    def test_terminal_states(self):
        terminal = TaskState.terminal_states()
        assert TaskState.COMPLETED in terminal
        assert TaskState.FAILED in terminal
        assert TaskState.CANCELLED in terminal
        assert TaskState.EXPIRED in terminal
        assert TaskState.QUEUED not in terminal
        assert TaskState.RUNNING not in terminal

    def test_no_transition_from_terminal(self):
        for state in TaskState.terminal_states():
            assert VALID_TRANSITIONS[state] == set()


class TestTaskSubmission:
    def test_create(self):
        sub = TaskSubmission.create("system.echo", {"message": "hello"})
        assert sub.task_id.startswith("task_")
        assert sub.capability_id == "system.echo"
        assert sub.idempotency_key.startswith("idem_")

    def test_roundtrip(self):
        sub = TaskSubmission.create("system.echo", {"message": "hello"})
        d = sub.to_dict()
        parsed = TaskSubmission.from_dict(d)
        assert parsed.task_id == sub.task_id
        assert parsed.capability_id == sub.capability_id


class TestTaskResult:
    def test_success(self):
        result = TaskResult.success("task_1", {"echo": "hello"}, "node_1", duration_ms=42)
        assert result.status == "completed"
        assert result.result == {"echo": "hello"}

    def test_failure(self):
        result = TaskResult.failure("task_1", "something broke", "node_1")
        assert result.status == "failed"
        assert result.error == "something broke"


class TestProtocolError:
    def test_create(self):
        err = ProtocolError.create(ErrorCode.TASK_EXPIRED, original_message_id="msg_1")
        assert err.error_code == ErrorCode.TASK_EXPIRED
        assert err.error_message == "Task deadline passed"

    def test_roundtrip(self):
        err = ProtocolError.create(ErrorCode.INVALID_MESSAGE, details={"field": "message_type"})
        d = err.to_dict()
        parsed = ProtocolError.from_dict(d)
        assert parsed.error_code == err.error_code


class TestRedactedSerialization:
    def test_redact_secret_keys(self):
        obj = {"api_key": "sk-secret", "name": "test", "nested": {"token": "abc", "value": 42}}
        redacted = redacted_serialization(obj)
        assert redacted["api_key"] == "<REDACTED>"
        assert redacted["name"] == "test"
        assert redacted["nested"]["token"] == "<REDACTED>"
        assert redacted["nested"]["value"] == 42

    def test_redact_in_list(self):
        obj = {"items": [{"key": 1, "secret": "x"}, {"key": 2}]}
        redacted = redacted_serialization(obj)
        assert redacted["items"][0]["secret"] == "<REDACTED>"
        # Second item has no sensitive keys, should pass through
        assert "key" in redacted["items"][1]
        assert "secret" not in redacted["items"][1]

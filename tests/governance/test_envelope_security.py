import asyncio

from nous_runtime.connectivity.control_plane.gateway import ControlPlaneGateway
from nous_runtime.connectivity.protocol.envelope import ProtocolEnvelope


def signed_message(**overrides):
    env = ProtocolEnvelope(
        message_type="HEARTBEAT",
        source_id="node-a",
        target_id="control-plane",
        sequence_number=1,
        nonce="nonce-1",
        payload={"session_id": "missing"},
    )
    for key, value in overrides.items():
        setattr(env, key, value)
    env.sign("secret")
    return env


def test_signature_binds_nonce_sequence_and_target():
    env = signed_message()
    assert env.verify("secret")
    env.nonce = "changed"
    assert not env.verify("secret")

    env = signed_message()
    env.sequence_number = 2
    assert not env.verify("secret")

    env = signed_message()
    env.target_id = "other"
    assert not env.verify("secret")


def test_gateway_rejects_duplicate_message_id_after_first_seen():
    gateway = ControlPlaneGateway(signing_key="secret")
    env = signed_message(message_id="fixed-msg")
    first = asyncio.run(gateway._dispatch(env.to_dict(), ("127.0.0.1", 1000)))
    second = asyncio.run(gateway._dispatch(env.to_dict(), ("127.0.0.1", 1000)))
    assert first["message_type"] == "PROTOCOL_ERROR"
    assert first["payload"]["error_code"] == "SESSION_EXPIRED"
    assert second["payload"]["error_code"] == "TASK_DUPLICATE"


def test_gateway_rejects_sequence_rollback():
    gateway = ControlPlaneGateway(signing_key="secret")
    first = signed_message(message_id="msg-1", nonce="nonce-1", sequence_number=2)
    second = signed_message(message_id="msg-2", nonce="nonce-2", sequence_number=1)
    asyncio.run(gateway._dispatch(first.to_dict(), ("127.0.0.1", 1000)))
    result = asyncio.run(gateway._dispatch(second.to_dict(), ("127.0.0.1", 1000)))
    assert result["payload"]["error_code"] == "SEQUENCE_GAP"


def test_gateway_rejects_duplicate_nonce():
    gateway = ControlPlaneGateway(signing_key="secret")
    first = signed_message(message_id="msg-1", nonce="nonce-x", sequence_number=1)
    second = signed_message(message_id="msg-2", nonce="nonce-x", sequence_number=2)
    asyncio.run(gateway._dispatch(first.to_dict(), ("127.0.0.1", 1000)))
    result = asyncio.run(gateway._dispatch(second.to_dict(), ("127.0.0.1", 1000)))
    assert result["payload"]["error_code"] == "TASK_DUPLICATE"

from __future__ import annotations

import asyncio

from integrations.opcua import OPCUANKIAdapter
from integrations.ros2 import ROS2NKIAdapter


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []

    async def execute_operation(
        self,
        operation: dict,
        idempotency_key: str = "",
    ) -> dict:
        self.calls.append((operation, idempotency_key))
        return {"workload_id": "w1"}


def test_ros2_adapter_uses_nki() -> None:
    client = RecordingClient()
    result = asyncio.run(
        ROS2NKIAdapter(client).submit_message(
            topic="/camera",
            message_type="sensor_msgs/Image",
            payload={"frame": 1},
            sequence=7,
        )
    )
    assert result["workload_id"] == "w1"
    assert client.calls[0][1] == "ros2:/camera:7"
    assert client.calls[0][0]["backend"] == "reference"
    assert client.calls[0][0]["delivery"] == "IDEMPOTENT"


def test_opcua_adapter_uses_nki() -> None:
    client = RecordingClient()
    asyncio.run(
        OPCUANKIAdapter(client).submit_observation(
            server_id="line-1",
            node_id="ns=2;s=Temperature",
            value=42,
            source_timestamp_us=9,
        )
    )
    assert '"adapter":"opcua"' in client.calls[0][0]["input"]


def test_integrations_reject_embedded_credentials() -> None:
    client = RecordingClient()
    try:
        asyncio.run(
            ROS2NKIAdapter(client).submit_message(
                topic="/unsafe",
                message_type="example/Unsafe",
                payload={"api_key": "not-allowed"},
                sequence=1,
            )
        )
    except ValueError as error:
        assert "credential" in str(error)
    else:
        raise AssertionError("credential-bearing observation was accepted")

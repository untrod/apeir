"""ROS 2 bridge that translates messages into NKI workloads.

The bridge has no authority over execution state and never controls devices
directly. A caller supplies a connected NKI client.
"""

from __future__ import annotations

from typing import Any

from integrations.nki_operation import (
    OperationClientProtocol,
    observation_operation,
)


class ROS2NKIAdapter:
    def __init__(self, client: OperationClientProtocol, *, namespace: str = "ros2") -> None:
        self._client = client
        self._namespace = namespace

    async def submit_message(
        self,
        *,
        topic: str,
        message_type: str,
        payload: dict[str, Any],
        sequence: int,
    ) -> dict[str, Any]:
        if not topic.startswith("/") or not message_type.strip() or sequence < 0:
            raise ValueError("ROS 2 topic, message type, or sequence is invalid")
        idempotency_key = f"ros2:{topic}:{sequence}"
        operation = observation_operation(
            adapter="ros2",
            idempotency_key=idempotency_key,
            payload={
                "namespace": self._namespace,
                "adapter": "ros2",
                "topic": topic,
                "message_type": message_type,
                "sequence": sequence,
                "payload": payload,
            },
        )
        return await self._client.execute_operation(
            operation,
            idempotency_key=idempotency_key,
        )


__all__ = ["ROS2NKIAdapter"]

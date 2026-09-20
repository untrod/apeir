"""OPC UA bridge that submits observed state through NKI."""

from __future__ import annotations

from typing import Any

from integrations.nki_operation import (
    OperationClientProtocol,
    observation_operation,
)


class OPCUANKIAdapter:
    def __init__(self, client: OperationClientProtocol, *, namespace: str = "opcua") -> None:
        self._client = client
        self._namespace = namespace

    async def submit_observation(
        self,
        *,
        server_id: str,
        node_id: str,
        value: Any,
        source_timestamp_us: int,
    ) -> dict[str, Any]:
        if not server_id.strip() or not node_id.strip() or source_timestamp_us < 0:
            raise ValueError("OPC UA server, node, or source timestamp is invalid")
        idempotency_key = (
            f"opcua:{server_id}:{node_id}:{source_timestamp_us}"
        )
        operation = observation_operation(
            adapter="opcua",
            idempotency_key=idempotency_key,
            payload={
                "namespace": self._namespace,
                "adapter": "opcua",
                "server_id": server_id,
                "node_id": node_id,
                "value": value,
                "source_timestamp_us": source_timestamp_us,
            },
        )
        return await self._client.execute_operation(
            operation,
            idempotency_key=idempotency_key,
        )


__all__ = ["OPCUANKIAdapter"]

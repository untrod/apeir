"""Probe ROS 2 and OPC UA observation adapters against a real nousd."""

from __future__ import annotations

import argparse
import asyncio
import json

from compat.nki_client import NKIClient
from integrations.opcua import OPCUANKIAdapter
from integrations.ros2 import ROS2NKIAdapter


async def probe(endpoint: str) -> dict[str, object]:
    client = NKIClient(endpoint)
    await client._connect()
    try:
        ros = await ROS2NKIAdapter(client).submit_message(
            topic="/nous/reference",
            message_type="nous_msgs/ReferenceObservation",
            payload={"value": 42},
            sequence=1,
        )
        opcua = await OPCUANKIAdapter(client).submit_observation(
            server_id="reference-server",
            node_id="ns=2;s=ReferenceValue",
            value=42,
            source_timestamp_us=1,
        )
    finally:
        await client.close()
    return {
        "ros2": {
            "operation_id": ros.get("operation_id"),
            "workload_id": ros.get("workload_id"),
            "committed": bool(
                ros.get("operation_id")
                and ros.get("output_digest")
                and ros.get("decision_trace")
            ),
        },
        "opcua": {
            "operation_id": opcua.get("operation_id"),
            "workload_id": opcua.get("workload_id"),
            "committed": bool(
                opcua.get("operation_id")
                and opcua.get("output_digest")
                and opcua.get("decision_trace")
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-endpoint", required=True)
    args = parser.parse_args()
    result = asyncio.run(probe(args.kernel_endpoint))
    print(json.dumps(result, separators=(",", ":")))
    if not all(item["committed"] for item in result.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

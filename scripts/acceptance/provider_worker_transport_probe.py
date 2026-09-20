"""Inspect the provider-worker request body without contacting a real provider."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.models import ModelRequest


class _CaptureHandler(BaseHTTPRequestHandler):
    body: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length") or 0)
        type(self).body = json.loads(self.rfile.read(length) or b"{}")
        payload = {
            "id": "probe",
            "object": "chat.completion",
            "model": "probe-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "probe-call",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"result.txt","content":"done"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _ProbeProvider:
    provider_id = "probe"
    provider_name = "Provider worker probe"
    model = "probe-model"
    credential_ref = "env:DEEPSEEK_API_KEY"
    locality = "remote"

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    @staticmethod
    def list_capabilities() -> list[str]:
        return ["model.reason"]

    @staticmethod
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @staticmethod
    def invoke(_capability_id: str, **_params: object) -> dict[str, object]:
        raise AssertionError("direct provider path must not be used")


async def _run(kernel_endpoint: str, provider_endpoint: str) -> dict[str, object]:
    os.environ["NOUS_KERNEL_ENDPOINT"] = kernel_endpoint
    gateway = build_gateway_from_providers([_ProbeProvider(provider_endpoint)])
    gateway._nki_endpoint = kernel_endpoint
    tool = {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a UTF-8 file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    }
    response = await gateway.invoke(
        ModelRequest(
            task_id="provider-worker-transport-probe",
            messages=({"role": "user", "content": "Call write_file."},),
            metadata={"tools": [tool], "tool_choice": "required", "max_tokens": 128},
        )
    )
    body = dict(_CaptureHandler.body)
    content = response.content if isinstance(response.content, dict) else {}
    return {
        "request_keys": sorted(body),
        "tool_count_sent": len(body.get("tools") or []),
        "tool_choice_sent": body.get("tool_choice"),
        "tool_call_count_received": len(content.get("tool_calls") or []),
        "execution_path": response.metadata.get("execution_path"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-endpoint", required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(
            _run(args.kernel_endpoint, f"http://localhost:{server.server_port}/v1/chat/completions")
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["tool_count_sent"] == 1 and result["tool_call_count_received"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

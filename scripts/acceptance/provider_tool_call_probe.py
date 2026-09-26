"""Safe diagnostic for an OpenAI-compatible provider tool-call envelope.

The credential is supplied only through the process environment.  Output is
limited to protocol metadata and never includes prompts, content, or secrets.
"""

from __future__ import annotations

import argparse
import json

from nous_runtime.provider.adapters.openai import OpenAIProvider


def _invoke_tool(provider: OpenAIProvider, tool_choice: str) -> dict[str, object]:
    result = provider.invoke(
        "model.reason",
        messages=(
            {
                "role": "system",
                "content": "Call the supplied tool exactly once; do not answer in prose.",
            },
            {"role": "user", "content": "Create result.txt containing done."},
        ),
        tools=(
            {
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
            },
        ),
        tool_choice=tool_choice,
        max_tokens=256,
    )
    return {
        "ok": bool(result.get("ok")),
        "tool_call_count": len(result.get("tool_calls") or ()),
        "has_content": bool(result.get("content")),
        "error_code": str(result.get("error_code") or ""),
        "http_status": result.get("http_status"),
    }


def _invoke_structured(provider: OpenAIProvider) -> dict[str, object]:
    result = provider.invoke(
        "model.reason",
        messages=(
            {
                "role": "system",
                "content": "Return the requested JSON object and no prose.",
            },
            {"role": "user", "content": "Report readiness as true."},
        ),
        response_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["ready"],
            "properties": {"ready": {"type": "boolean"}},
        },
        max_tokens=64,
    )
    content = result.get("content")
    try:
        payload = json.loads(content) if isinstance(content, str) else {}
    except json.JSONDecodeError:
        payload = {}
    return {
        "ok": bool(result.get("ok")),
        "schema_valid": payload == {"ready": True},
        "error_code": str(result.get("error_code") or ""),
        "http_status": result.get("http_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default="https://api.deepseek.com/v1/chat/completions",
    )
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--provider-id", default="deepseek")
    parser.add_argument("--provider-name", default="DeepSeek")
    parser.add_argument("--credential-ref", default="env:DEEPSEEK_API_KEY")
    parser.add_argument(
        "--structured-output-mode",
        choices=("json_schema", "json_object"),
        default="json_object",
    )
    args = parser.parse_args()
    provider = OpenAIProvider(
        provider_id=args.provider_id,
        provider_name=args.provider_name,
        endpoint=args.endpoint,
        model=args.model,
        credential_ref=args.credential_ref,
        structured_output_mode=args.structured_output_mode,
    )
    safe = {
        "required": _invoke_tool(provider, "required"),
        "auto": _invoke_tool(provider, "auto"),
        "structured": _invoke_structured(provider),
    }
    print(json.dumps(safe, separators=(",", ":")))
    tools_ok = all(
        item["ok"] and item["tool_call_count"] == 1
        for item in (safe["required"], safe["auto"])
    )
    structured_ok = safe["structured"]["ok"] and safe["structured"]["schema_valid"]
    return 0 if tools_ok and structured_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

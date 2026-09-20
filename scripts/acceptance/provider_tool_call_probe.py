"""Safe diagnostic for an OpenAI-compatible provider tool-call envelope.

The credential is supplied only through the process environment.  Output is
limited to protocol metadata and never includes prompts, content, or secrets.
"""

from __future__ import annotations

import json

from nous_runtime.provider.adapters.openai import OpenAIProvider


def _invoke(provider: OpenAIProvider, tool_choice: str) -> dict[str, object]:
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


def main() -> int:
    provider = OpenAIProvider(
        provider_id="deepseek",
        provider_name="DeepSeek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-chat",
        credential_ref="env:DEEPSEEK_API_KEY",
    )
    safe = {"required": _invoke(provider, "required"), "auto": _invoke(provider, "auto")}
    print(json.dumps(safe, separators=(",", ":")))
    return 0 if all(
        item["ok"] and item["tool_call_count"] == 1 for item in safe.values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

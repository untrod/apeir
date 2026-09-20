"""Configurable Anthropic-compatible Provider adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any

from nous_runtime.compat.provider import Provider
from nous_runtime.provider.credentials import resolve_credential

_SUPPORTED = {"model.reason", "model.code", "model.vision"}


class AnthropicProvider(Provider):
    """Provider for Anthropic-compatible Messages APIs."""

    provider_id = "anthropic"
    provider_name = "Anthropic Compatible"
    version = "1.1.0"

    def __init__(
        self,
        *,
        provider_id: str = "anthropic",
        provider_name: str = "Anthropic Compatible",
        endpoint: str = "https://api.anthropic.com/v1/messages",
        model: str = "",
        credential_ref: str = "",
        capabilities: Iterable[str] = ("model.reason", "model.code"),
        capability_models: dict[str, str] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.endpoint = endpoint
        self.model = model
        self.credential_ref = credential_ref
        self.capabilities = tuple(
            capability
            for capability in capabilities
            if capability in _SUPPORTED
        ) or ("model.reason", "model.code")
        self.capability_models = {
            str(capability).strip(): str(model_id).strip()
            for capability, model_id in (capability_models or {}).items()
            if str(capability).strip() and str(model_id).strip()
        }

    def list_capabilities(self) -> list[str]:
        return list(self.capabilities)

    def invoke(
        self,
        capability_id: str,
        **params: Any,
    ) -> dict[str, Any]:
        if capability_id not in self.capabilities:
            return {
                "ok": False,
                "error": f"Capability '{capability_id}' is not configured",
                "error_code": "NOUS_PROVIDER_CAPABILITY_UNAVAILABLE",
            }
        credential = self._credential()
        if not credential:
            return {
                "ok": False,
                "error": "Configured credential reference is unavailable",
                "error_code": "NOUS_PROVIDER_CREDENTIAL_UNAVAILABLE",
            }
        content: Any = str(params.get("prompt") or "")
        system, messages = self._normalize_messages(
            params.get("messages") or ()
        )
        if capability_id == "model.vision" and params.get("image_url"):
            content = [
                {
                    "type": "text",
                    "text": content or "Describe the image",
                },
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": str(params["image_url"]),
                    },
                },
            ]
        body: dict[str, Any] = {
            "model": str(params.get("model") or self.model),
            "max_tokens": int(params.get("max_tokens") or 1024),
            "messages": messages
            or [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system
        tools = self._normalize_tools(params.get("tools") or ())
        if tools:
            body["tools"] = tools
        body = self._with_persona(body, params)
        try:
            request = urllib.request.Request(
                self.endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": credential,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(
                request,
                timeout=float(params.get("timeout_s") or 30),
            ) as response:
                payload = json.loads(response.read())
            return self._parse_response(payload, body["model"])
        except urllib.error.HTTPError as exc:
            try:
                return {
                    "ok": False,
                    "error": f"HTTP {exc.code}: {exc.reason}",
                    "error_code": "NOUS_PROVIDER_HTTP_ERROR",
                    "http_status": exc.code,
                }
            finally:
                exc.close()
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "error_code": "NOUS_PROVIDER_CONNECTION_ERROR",
            }

    def health(self) -> dict[str, Any]:
        if not self.model:
            return {
                "status": "degraded",
                "error": "Default model is not configured",
            }
        if not self._credential():
            return {
                "status": "degraded",
                "error": "Credential reference is unavailable",
            }
        return {
            "status": "ok",
            "model": self.model,
            "endpoint_configured": bool(self.endpoint),
        }

    def _with_persona(
        self,
        body: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Inject the Runtime system prompt via the top-level system field."""
        try:
            from nous_runtime.persona.system_prompt import (
                apply_persona_anthropic,
            )
        except ImportError:
            return body
        return apply_persona_anthropic(body, params, self)

    @staticmethod
    def _parse_response(
        payload: Mapping[str, Any],
        model: str,
    ) -> dict[str, Any]:
        blocks = payload.get("content") or ()
        text = "".join(
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, Mapping)
            and block.get("type") == "text"
        )
        tool_calls = [
            {
                "id": str(block.get("id") or ""),
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    "arguments": json.dumps(
                        block.get("input") or {},
                        ensure_ascii=False,
                    ),
                },
            }
            for block in blocks
            if isinstance(block, Mapping)
            and block.get("type") == "tool_use"
        ]
        result: dict[str, Any] = {
            "ok": True,
            "content": text,
            "model": str(payload.get("model") or model),
        }
        if tool_calls:
            result["tool_calls"] = tool_calls
        if payload.get("usage"):
            result["usage"] = dict(payload["usage"])
        return result

    @staticmethod
    def _normalize_tools(
        tools: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized = []
        for tool in tools:
            function = dict(tool.get("function") or {})
            normalized.append(
                {
                    "name": str(
                        function.get("name")
                        or tool.get("name")
                        or ""
                    ),
                    "description": str(
                        function.get("description")
                        or tool.get("description")
                        or ""
                    ),
                    "input_schema": dict(
                        function.get("parameters")
                        or tool.get("input_schema")
                        or {"type": "object", "properties": {}}
                    ),
                }
            )
        return normalized

    @staticmethod
    def _normalize_messages(
        messages: Iterable[Mapping[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        normalized: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = message.get("content")
            if role == "system":
                system_parts.append(str(content or ""))
                continue
            if role == "tool":
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": str(
                            message.get("tool_call_id") or ""
                        ),
                        "content": str(content or ""),
                    }
                ]
                role = "user"
            elif role == "assistant" and message.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append(
                        {"type": "text", "text": str(content)}
                    )
                for call in message.get("tool_calls") or ():
                    function = dict(call.get("function") or {})
                    try:
                        arguments = json.loads(
                            str(function.get("arguments") or "{}")
                        )
                    except (TypeError, ValueError):
                        arguments = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(call.get("id") or ""),
                            "name": str(function.get("name") or ""),
                            "input": arguments,
                        }
                    )
                content = blocks
            normalized.append(
                {"role": role, "content": content or ""}
            )
        return "\n\n".join(system_parts), normalized

    def _credential(self) -> str:
        try:
            return resolve_credential(self.credential_ref)
        except (RuntimeError, ValueError):
            return ""

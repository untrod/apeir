"""Configurable OpenAI-compatible Provider adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterable

from nous_runtime.compat.provider import Provider
from nous_runtime.provider.credentials import resolve_credential

_SUPPORTED = {
    "model.reason",
    "model.code",
    "model.embed",
    "model.vision",
    "model.rerank",
}


class OpenAIProvider(Provider):
    """Provider for OpenAI-compatible HTTP APIs with per-instance configuration."""

    provider_id = "openai"
    provider_name = "openai"
    version = "1.1.0"

    def __init__(
        self,
        *,
        provider_id: str = "openai",
        provider_name: str = "OpenAI Compatible",
        endpoint: str = "",
        model: str = "",
        credential_ref: str = "",
        authentication_required: bool | None = None,
        capabilities: Iterable[str] = ("model.reason", "model.code"),
        capability_endpoints: dict[str, str] | None = None,
        capability_models: dict[str, str] | None = None,
        max_concurrency: int = 3,
        structured_output_mode: str = "json_schema",
    ) -> None:
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.endpoint = endpoint
        self.model = model
        self.credential_ref = credential_ref
        self.authentication_required = (
            bool(credential_ref)
            if authentication_required is None
            else bool(authentication_required)
        )
        self.max_concurrency = max(1, min(int(max_concurrency), 8))
        output_mode = str(structured_output_mode or "json_schema").strip()
        if output_mode not in {"json_schema", "json_object"}:
            raise ValueError(
                "structured_output_mode must be json_schema or json_object"
            )
        self.structured_output_mode = output_mode
        self.capabilities = tuple(
            capability for capability in capabilities if capability in _SUPPORTED
        ) or ("model.reason", "model.code")
        self.capability_endpoints = dict(capability_endpoints or {})
        self.capability_models = {
            str(capability).strip(): str(model_id).strip()
            for capability, model_id in (capability_models or {}).items()
            if str(capability).strip() and str(model_id).strip()
        }

    def list_capabilities(self) -> list[str]:
        return list(self.capabilities)

    def invoke(self, capability_id: str, **params: Any) -> dict[str, Any]:
        if capability_id not in self.capabilities:
            return {
                "ok": False,
                "error": f"Capability '{capability_id}' is not configured",
                "error_code": "NOUS_PROVIDER_CAPABILITY_UNAVAILABLE",
            }
        model = str(
            params.get("model") or self.model or os.environ.get("NOUS_LLM_MODEL") or ""
        )
        endpoint = self._endpoint(capability_id)
        if not endpoint or not model:
            return {
                "ok": False,
                "error": "Provider endpoint or model is not configured",
                "error_code": "NOUS_PROVIDER_CONFIG_INCOMPLETE",
            }
        api_key = self._credential()
        if self.authentication_required and not api_key:
            return {
                "ok": False,
                "error": "Configured credential reference is unavailable",
                "error_code": "NOUS_PROVIDER_CREDENTIAL_UNAVAILABLE",
            }
        body = self._request_body(
            capability_id,
            model,
            params,
            structured_output_mode=self.structured_output_mode,
        )
        if capability_id in ("model.reason", "model.code", "model.vision"):
            body = self._with_persona(body, params)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
            return self._parse_response(capability_id, payload, model)
        except urllib.error.HTTPError as exc:
            try:
                balance_exhausted = exc.code == 402
                return {
                    "ok": False,
                    "error": f"HTTP {exc.code}: {exc.reason}",
                    "error_code": (
                        "NOUS_PROVIDER_BALANCE_EXHAUSTED"
                        if balance_exhausted
                        else "NOUS_PROVIDER_HTTP_ERROR"
                    ),
                    "http_status": exc.code,
                    "retryable": False if balance_exhausted else None,
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
        if not (self.model or os.environ.get("NOUS_LLM_MODEL")):
            return {"status": "degraded", "error": "Default model is not configured"}
        if self.authentication_required and not self._credential():
            return {
                "status": "degraded",
                "error": "Credential reference is unavailable",
            }
        return {
            "status": "ok",
            "model": self.model or os.environ.get("NOUS_LLM_MODEL", ""),
            "endpoint_configured": bool(
                self.endpoint or os.environ.get("NOUS_LLM_API_URL")
            ),
        }

    def _with_persona(
        self, body: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        """Inject the Nous Runtime system prompt; degrades to a no-op."""
        try:
            from nous_runtime.persona.system_prompt import apply_persona_openai
        except ImportError:
            return body
        return apply_persona_openai(body, params, self)

    def _credential(self) -> str:
        if self.credential_ref:
            try:
                return resolve_credential(self.credential_ref)
            except (RuntimeError, ValueError):
                return ""
        return os.environ.get("NOUS_LLM_API_KEY", "")

    def _endpoint(self, capability_id: str) -> str:
        configured = self.capability_endpoints.get(capability_id)
        if configured:
            return configured
        endpoint = self.endpoint or os.environ.get(
            "NOUS_LLM_API_URL",
            "https://api.openai.com/v1/chat/completions",
        )
        replacements = {
            "model.embed": "embeddings",
            "model.rerank": "rerank",
        }
        suffix = replacements.get(capability_id)
        if not suffix:
            return endpoint
        if endpoint.endswith("/chat/completions"):
            return endpoint[: -len("chat/completions")] + suffix
        return endpoint.rstrip("/") + f"/{suffix}"

    @staticmethod
    def _request_body(
        capability_id: str,
        model: str,
        params: dict[str, Any],
        *,
        structured_output_mode: str = "json_schema",
    ) -> dict[str, Any]:
        if capability_id == "model.embed":
            return {
                "model": model,
                "input": params.get("text") or params.get("input") or "",
            }
        if capability_id == "model.rerank":
            return {
                "model": model,
                "query": params.get("query") or "",
                "documents": params.get("documents") or (),
            }
        content: Any = params.get("prompt", "")
        if capability_id == "model.vision" and params.get("image_url"):
            content = [
                {
                    "type": "text",
                    "text": str(params.get("prompt") or "Describe the image"),
                },
                {"type": "image_url", "image_url": {"url": str(params["image_url"])}},
            ]
        body = {
            "model": model,
            "messages": params.get("messages")
            or [{"role": "user", "content": content}],
            "max_tokens": int(params.get("max_tokens") or 1024),
        }
        tools = params.get("tools") or ()
        if tools:
            body["tools"] = list(tools)
            if params.get("tool_choice") in {"auto", "none", "required"}:
                body["tool_choice"] = str(params["tool_choice"])
        response_schema = params.get("response_schema") or {}
        if response_schema:
            if structured_output_mode == "json_object":
                body["response_format"] = {"type": "json_object"}
            else:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "nous_response",
                        "schema": response_schema,
                    },
                }
        return body

    @staticmethod
    def _parse_response(
        capability_id: str,
        payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        if capability_id == "model.embed":
            items = sorted(
                payload.get("data") or (),
                key=lambda item: int(item.get("index") or 0),
            )
            vectors = [list(item.get("embedding") or ()) for item in items]
            return {
                "ok": True,
                "embedding": vectors[0] if vectors else [],
                "embeddings": vectors,
                "vector_dim": len(vectors[0]) if vectors else 0,
                "usage": dict(payload.get("usage") or {}),
                "model": model,
            }
        if capability_id == "model.rerank":
            return {"ok": True, "results": payload.get("results") or (), "model": model}
        message = (payload.get("choices") or [{}])[0].get("message", {})
        return {
            "ok": True,
            "content": message.get("content", ""),
            "tool_calls": list(message.get("tool_calls") or ()),
            "usage": dict(payload.get("usage") or {}),
            "model": str(payload.get("model") or model),
        }

# -*- coding: utf-8 -*-
"""
Ollama local inference adapter for Nous Runtime.

Implements §10.3 (Local Inference Access) of the master plan.
Supports chat, streaming, embeddings, tool calling via Ollama's
OpenAI-compatible API.
"""

from __future__ import annotations

import json
import logging
import time

from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.ollama")


class OllamaProvider(Provider):
    """Provider for Ollama local inference engine."""

    name = "ollama"
    version = "1.0.0"

    def __init__(self, endpoint: str = "http://localhost:11434",
                 default_model: str = ""):
        self._endpoint = endpoint.rstrip("/")
        self._default_model = default_model

    def list_capabilities(self) -> list[str]:
        caps = ["model.chat", "model.stream"]
        if self._check_api():
            try:
                models = self._list_models()
                if any("embed" in m.lower() for m in models):
                    caps.append("model.embed")
            except Exception:
                pass
        return caps

    def invoke(self, capability_id: str, **params) -> dict:
        model = params.get("model", self._default_model)
        messages = params.get("messages", [])
        system = params.get("system", "")

        if capability_id == "model.embed":
            return self._embed(params)

        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": params.get("temperature", 0.7),
                "num_predict": params.get("max_tokens", 2048),
            },
        }
        if system:
            body["system"] = system

        try:
            import urllib.request

            req = urllib.request.Request(
                f"{self._endpoint}/api/chat",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            start = time.monotonic()
            with urllib.request.urlopen(req, timeout=params.get("timeout", 300)) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            return {
                "ok": True,
                "text": data.get("message", {}).get("content", ""),
                "model": data.get("model", model),
                "usage": {
                    "prompt_eval_count": data.get("prompt_eval_count", 0),
                    "eval_count": data.get("eval_count", 0),
                },
                "latency_ms": int((time.monotonic() - start) * 1000),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stream_invoke(self, capability_id: str, **params):
        """Stream tokens from Ollama."""
        model = params.get("model", self._default_model)
        messages = params.get("messages", [])

        body = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        try:
            import urllib.request

            req = urllib.request.Request(
                f"{self._endpoint}/api/chat",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                for line in resp:
                    line = line.decode("utf-8").strip()
                    if line:
                        try:
                            event = json.loads(line)
                            content = event.get("message", {}).get("content", "")
                            if content:
                                yield {"token": content}
                            if event.get("done"):
                                yield {"done": True}
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield {"error": str(e)}

    def _embed(self, params: dict) -> dict:
        model = params.get("model", self._default_model)
        text = params.get("text", "")

        body = {"model": model, "input": text if isinstance(text, list) else [text]}

        try:
            import urllib.request

            req = urllib.request.Request(
                f"{self._endpoint}/api/embed",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "embeddings": data.get("embeddings", [])}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        try:
            models = self._list_models()
            return {
                "status": "ok" if models else "degraded",
                "models": models[:20],
                "model_count": len(models),
                "endpoint": self._endpoint,
            }
        except Exception as e:
            return {"status": "down", "error": str(e), "endpoint": self._endpoint}

    def _list_models(self) -> list[str]:
        import urllib.request
        req = urllib.request.Request(f"{self._endpoint}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]

    def _check_api(self) -> bool:
        try:
            import urllib.request
            urllib.request.urlopen(f"{self._endpoint}/api/tags", timeout=2)
            return True
        except Exception:
            return False

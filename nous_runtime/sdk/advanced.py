# -*- coding: utf-8 -*-
"""
Nous Python SDK -Advanced Features.

Streaming, async, event subscriptions, and authentication helpers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Generator
from typing import Any

from nous_runtime.sdk.client import NousClient, CapabilityResult

log = logging.getLogger("nous.sdk.advanced")


class StreamingClient(NousClient):
    """SDK client with streaming support."""

    def run_stream(self, capability_id: str, **params) -> Generator[str, None, CapabilityResult]:
        """
        Execute a capability with streaming output.

        Yields tokens as they arrive, returns the final CapabilityResult.

        Usage:
            client = StreamingClient()
            for token in client.run_stream("model.reason", prompt="Explain"):
                print(token, end="", flush=True)
        """
        import time
        start = time.time()

        try:
            from nous_runtime.capability.resolver import execute_capability
            result = execute_capability(capability_id, **params)

            if result.ok:
                content = result.result.get("content", "") if isinstance(result.result, dict) else str(result.result)
                # Simulate streaming by yielding chunks
                chunk_size = 4
                for i in range(0, len(content), chunk_size):
                    yield content[i:i+chunk_size]
                    time.sleep(0.01)  # Smooth streaming feel

            return CapabilityResult(
                ok=result.ok,
                capability_id=capability_id,
                provider_id=result.provider_id,
                result=result.result,
                error=result.error,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CapabilityResult(
                ok=False, capability_id=capability_id,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )


class AsyncClient:
    """
    Async SDK client for asyncio-based applications.

    Usage:
        client = AsyncClient()
        result = await client.run("model.reason", prompt="Explain")
    """

    def __init__(self, host: str = "localhost", port: int = 8770, token: str = ""):
        self._sync = NousClient(host=host, port=port, token=token)

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.health)

    async def status(self):
        return await asyncio.to_thread(self._sync.status)

    async def run(self, capability_id: str, **params) -> CapabilityResult:
        return await asyncio.to_thread(self._sync.run, capability_id, **params)

    async def list_capabilities(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._sync.list_capabilities)

    async def list_providers(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._sync.list_providers)

    async def list_packs(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._sync.list_packs)

    async def trace(self, limit: int = 10) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._sync.trace, limit=limit)


class EventSubscriber:
    """
    Subscribe to Runtime events.

    Usage:
        def on_job_done(event):
            print(f"Job {event['job_id']} completed")

        sub = EventSubscriber()
        sub.on("job.done", on_job_done)
        sub.listen()
    """

    def __init__(self, client: NousClient | None = None):
        self._client = client or NousClient()
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False

    def on(self, event_pattern: str, handler: Callable) -> None:
        """Register a handler for an event pattern (supports * wildcard)."""
        self._handlers.setdefault(event_pattern, []).append(handler)

    def listen(self, interval: float = 2.0) -> None:
        """Start polling for events in a background thread."""
        self._running = True

        def _poll():
            while self._running:
                try:
                    from nous_runtime.services.events import list_events
                    events = list_events(limit=10)
                    for evt in events:
                        etype = evt.get("type", "") if isinstance(evt, dict) else ""
                        for pattern, handlers in self._handlers.items():
                            if _match_pattern(etype, pattern):
                                for h in handlers:
                                    try:
                                        h(evt)
                                    except Exception:
                                        pass
                except Exception:
                    pass
                time.sleep(interval)

        t = threading.Thread(target=_poll, daemon=True)
        t.start()

    def stop(self) -> None:
        self._running = False


def _match_pattern(event_type: str, pattern: str) -> bool:
    """Simple fnmatch-style matching."""
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return event_type.startswith(pattern[:-1])
    return event_type == pattern


# Authentication Helper

class AuthConfig:
    """Authentication configuration for the Runtime."""

    @staticmethod
    def from_env() -> dict[str, str]:
        """Load auth config from environment variables."""
        import os
        return {
            "token": os.environ.get("NOUS_AUTH_TOKEN", ""),
            "llm_api_key": os.environ.get("NOUS_LLM_API_KEY", ""),
            "llm_api_url": os.environ.get("NOUS_LLM_API_URL", ""),
            "agent_signing_secret": os.environ.get("NOUS_AGENT_SIGNING_SECRET", ""),
        }

    @staticmethod
    def validate(config: dict[str, str]) -> list[str]:
        """Validate auth config. Returns list of missing required fields."""
        missing = []
        if not config.get("token"):
            missing.append("NOUS_AUTH_TOKEN")
        return missing

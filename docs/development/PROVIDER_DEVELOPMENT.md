# Provider Development Guide

## Overview

A Provider is any component that executes capabilities. Models, devices, storage backends, and external services are all Providers.

## The Provider Interface

```python
from abc import ABC, abstractmethod

class Provider(ABC):
    name: str               # Unique provider name
    version: str            # Semver

    @abstractmethod
    def list_capabilities(self) -> list[str]:
        """Capability IDs this provider can execute."""

    @abstractmethod
    def invoke(self, capability_id: str, **params) -> dict:
        """Execute a capability. Return {'ok': True/False, ...}."""

    @abstractmethod
    def health(self) -> dict:
        """Return {'status': 'ok'|'degraded'|'down', ...}."""
```

## Example: Model Provider

```python
from remote_terminal.nous_core.provider import Provider

class OpenAIProvider(Provider):
    name = "openai"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["model.reason", "model.code"]

    def invoke(self, capability_id: str, **params) -> dict:
        prompt = params.get("prompt", "")
        # Call OpenAI API...
        return {"ok": True, "content": "..."}

    def health(self) -> dict:
        # Check API availability
        return {"status": "ok", "latency_ms": 120}
```

## Example: Device Provider

```python
class RobotProvider(Provider):
    name = "robot_arm"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["robot.move", "robot.grip", "robot.status"]

    def invoke(self, capability_id: str, **params) -> dict:
        if capability_id == "robot.move":
            x, y, z = params["x"], params["y"], params["z"]
            # Send move command to robot...
            return {"ok": True, "position": [x, y, z]}
        # ...

    def health(self) -> dict:
        # Check robot connection
        return {"status": "ok", "joints": 6}
```

## Provider Types

| Type | Examples | Capability Pattern |
|------|----------|-------------------|
| Model | OpenAI, Claude, Ollama | `model.*` |
| Device | PC Agent, Robot, ESP32 | `device.*` |
| Storage | ChromaDB, S3 | `rag.*`, `storage.*` |
| Service | Web Search, Email | `tool.*` |

## Registration

```python
from nous_runtime.provider import register_adapter
register_adapter(MyProvider())
```

## Health Checks

The Runtime calls `health()` on every registered provider periodically. Return:
- `{"status": "ok"}` — provider is healthy
- `{"status": "degraded", "error": "..."}` — provider is degraded but usable
- `{"status": "down", "error": "..."}` — provider is unavailable

## Rules

1. Providers implement the Provider ABC
2. One Provider can serve multiple Capabilities
3. Providers never depend on specific models
4. Provider failure must not crash the Runtime
5. Provider credentials come from environment variables, never hardcoded

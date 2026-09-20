# Provider Contract v1.0

## Definition

A Provider declares **WHO** executes capabilities and **HOW**.

## Interface

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
        """Execute a capability. Returns {'ok': True/False, ...}."""

    @abstractmethod
    def health(self) -> dict:
        """Return {'status': 'ok'|'degraded'|'down', ...}."""

    # Optional
    def estimate_cost(self, capability_id: str, **params) -> dict | None:
        """Estimate resource cost for an invocation."""
        return None

    def validate_params(self, capability_id: str, **params) -> bool:
        """Validate parameters before execution."""
        return True
```

## Provider Types

| Type | Examples | Capability Pattern |
|------|----------|-------------------|
| **Model** | OpenAI, Claude, DeepSeek, Ollama, Whisper | `model.*` |
| **Device** | PC Agent, Android, ESP32, Robot, PLC | `device.*` |
| **Storage** | ChromaDB, SQLite, S3, Weaviate | `storage.*`, `rag.*` |
| **Service** | Web Search, Notification, Calendar, Email | `tool.*`, `notification.*` |
| **Node** | Remote Runtime, Edge Node, Cloud Function | `node.*` |

## Lifecycle

```
DISCOVER
  ↓
CONNECT        <- Establish transport
  ↓
AUTHENTICATE   <- Verify identity
  ↓
ADVERTISE      <- Announce capabilities
  ↓
HEALTH_CHECK   <- Verify readiness
  ↓
READY          <- Available for execution
  ↓
EXECUTE        <- Handling capability invocations
  ↓
DEGRADED       <- Partial failure
  ↓
RECONNECT      <- Attempt recovery
  ↓
DISCONNECT     <- Graceful shutdown
```

## Provider Metadata

```yaml
identity: "openai-gpt4"
version: "1.0.0"
capabilities: ["model.reason", "model.code"]
health: "ok"
latency_ms: 450
cost_per_1k_tokens: 0.03
reliability: 0.999
trust_level: "high"
location: "us-east"
resource_availability: 0.95
```

## Registration

```python
from nous_runtime.provider import register_adapter
from nous_runtime.provider.adapters.openai import OpenAIProvider

register_adapter(OpenAIProvider())
# Raises TypeError if not a Provider subclass
```

## Rules

1. Provider knows WHO and HOW, not WHAT (that's Capability's job)
2. One Provider can serve multiple Capabilities
3. One Capability can be served by multiple Providers (routing)
4. Provider must implement all three abstract methods
5. Provider health is checked periodically by the Runtime
6. Provider failure does not crash the Runtime
7. Model providers are just one type — nothing special
8. Future providers (Robot, PLC, Browser) use the same interface

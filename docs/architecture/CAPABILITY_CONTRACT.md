# Capability Contract v1.0

## Definition

A Capability declares **WHAT** can be done. It does not know **WHO** executes it or **HOW**.

## Interface

```python
class Capability:
    id: str                  # Dotted name: "model.reason", "device.shell"
    version: str             # Semver: "1.0.0"
    description: str         # Human-readable
    category: str            # model | device | tool | rag | automation | notification | pack
    risk: str                # low | medium | high | critical

    # Schemas
    input_schema: dict       # JSON Schema for parameters
    output_schema: dict      # JSON Schema for return value

    # Constraints
    permissions: list[str]   # Required permissions
    depends_on: list[str]    # Capability IDs this depends on
    timeout_ms: int          # Maximum execution time
    retryable: bool          # Can be retried on failure

    # Lifecycle
    phase: str               # registered | validated | enabled | ready | disabled | deprecated
```

## Naming Convention

```
{domain}.{action}

Examples:
  model.reason          — LLM reasoning
  model.embed           — Text embedding
  device.shell          — Shell execution
  device.phone.tap      — Phone tap action
  rag.search            — Vector search
  rag.index             — Document indexing
  tool.web_search       — Web search
  notification.send     — Send notification
  automation.trigger    — Trigger automation rule
  study.plan.create     — Create study plan (from Study Pack)
  study.review.due      — Check due reviews (from Study Pack)
```

## Lifecycle

```
REGISTER
  ↓
VALIDATE    <- Schema validation, dependency check
  ↓
ENABLE      <- Make available for routing
  ↓
READY       <- Health check passed
  ↓
EXECUTE     <- Being invoked
  ↓
DISABLE     <- Taken offline
  ↓
DEPRECATE   <- Marked for removal
  ↓
UNREGISTER  <- Removed from registry
```

## Execution

```python
# Capability does NOT execute itself.
# Execution is handled by a Provider selected by the runtime.

result = runtime.request_capability(
    capability_id="model.reason",
    params={"prompt": "Explain recursion"},
)
# Runtime: resolve capability -> select provider -> execute -> audit -> return
```

## Rules

1. Capability knows WHAT, not WHO or HOW
2. Capability schemas are validated on registration
3. Dependencies are resolved before execution
4. Risk level determines security gating
5. Capabilities never call providers directly
6. Domain-specific capabilities come from Packs, not the Kernel

# Registry Contract v1.0

## Purpose

Every registry in the Runtime follows the same interface contract. No registry returns a mix of dict and list. CLI code never calls `.items()` on a registry result.

## Interface

```python
class Registry:
    def register(self, obj) -> str:        # Returns ID
    def unregister(self, id: str) -> bool: # True if removed
    def get(self, id: str) -> object | None:
    def list(self) -> list[dict]:          # ALWAYS returns list
    def count(self) -> int:
    def clear(self) -> None:
```

## Rules

1. `list()` always returns `list[dict]`, never `dict`
2. `list()` returns `[]` when empty, never `None`
3. `get()` returns `None` when not found, never raises
4. `register()` returns the object ID on success
5. `unregister()` returns `True` if object was removed, `False` if not found

## Registered Registries

| Registry | Module | Status |
|----------|--------|:------:|
| Provider Registry | `nous_core/provider.py` | Yes list[dict] |
| Capability Registry | `nous_core/capability/` | Yes list[dict] |
| Pack Registry | `nous_runtime/pack/registry.py` | Yes list[dict] |
| Device Registry | `nous_core/devices/` | Yes list[dict] |
| Job Registry | `nous_core/jobs/` | Yes list[dict] |
| Event Store | `nous_core/events/` | Yes list[dict] |

## Anti-Patterns (Forbidden)

```python
# Never call .items() on a list
for pid, p in registry.list().items():  # AttributeError!

# Never return dict from list()
def list(self) -> dict:  # Wrong!

# Correct
for p in registry.list():
    pid = p["id"]
```

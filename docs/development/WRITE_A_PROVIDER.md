# Write a Provider

Providers are how Nous connects to external systems: models, devices, services.

## 3 Methods

```python
from nous_core.provider import Provider

class MyProvider(Provider):
    provider_id = "my_service"
    provider_name = "My Service"

    def list_capabilities(self):
        return ["my_service.action", "my_service.query"]

    def invoke(self, capability_id, payload):
        if capability_id == "my_service.action":
            return {"ok": True, "result": do_action(payload)}
        return {"ok": False, "error": "Unknown capability"}

    def health(self):
        return {"status": "ok"}
```

## Register

```python
from nous_core.provider import register_adapter
register_adapter(MyProvider())
```

## Risk Levels

Always declare risk honestly:
- `low`: Read-only queries
- `medium`: Create/update
- `high`: Device control, file write
- `critical`: Delete, hardware motion

## Test with Demo Mode

`NOUS_DEMO_MODE=1` loads mock providers. Your provider runs alongside them.

# Write a Module

Modules group business logic: Learning, Capture, Notification.

## Module Manifest

```json
{
  "module_id": "my_module",
  "version": "1.0.0",
  "capabilities": ["my_module.analyze"],
  "permissions": ["read_data"],
  "events": ["my_module.completed"]
}
```

## Module Class

```python
class MyModule:
    module_id = "my_module"

    def on_init(self, kernel):
        self.kernel = kernel

    def on_event(self, event):
        if event.type == "chat.message.received":
            self.process(event.payload)
```

## Registration

```python
from nous_core.security import register_module_permissions
register_module_permissions("my_module", ["read_data", "send_notification"])
```

## Isolation Rules
- Module failure must not crash the kernel
- Module cannot access another module's internal state
- All external access must go through capabilities

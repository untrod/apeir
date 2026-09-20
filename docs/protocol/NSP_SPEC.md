# NSP: Nous Skill / Provider Protocol v0.1

> For third-party developers writing Skills, Providers, and Adapters.

## Module Manifest

Every module declares itself via `module.json`:

```json
{
  "module_id": "my_skill",
  "version": "1.0.0",
  "capabilities": [
    {
      "capability_id": "my_skill.analyze",
      "name": "My Analyzer",
      "risk_level": "low",
      "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
      "output_schema": {"type": "object", "properties": {"score": {"type": "number"}}},
      "timeout_ms": 30000
    }
  ],
  "permissions": ["read_files", "send_notification"],
  "events": ["my_skill.completed"]
}
```

## Provider Interface

```python
class MyProvider(Provider):
    provider_id = "my_provider"
    provider_name = "My Provider"

    def list_capabilities(self):
        return ["my_skill.analyze", "my_skill.report"]

    def invoke(self, capability_id, payload):
        if capability_id == "my_skill.analyze":
            return {"ok": True, "score": analyze(payload["text"])}
        return {"ok": False, "error": "Unknown capability"}

    def health(self):
        return {"status": "ok"}
```

## Error Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 100 | Invalid capability |
| 101 | Permission denied |
| 102 | Input validation failed |
| 103 | Execution failed |
| 104 | Timeout |

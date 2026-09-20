# Nous Model Adapter Template

Use this to connect a new model or provider to Nous in under 1 hour.

## Quick Start

```bash
nous dev create-adapter my-adapter
cd my-adapter
# Implement adapter
nous dev validate-adapter
nous dev test-adapter
```

## Adapter Structure

```
my-adapter/
├── adapter.json
├── README.md
└── src/
    ├── __init__.py
    └── adapter.py
```

## adapter.json

```json
{
  "adapter_id": "my-adapter",
  "name": "My Model Adapter",
  "version": "1.0.0",
  "adapter_type": "model",
  "provider": "my-provider",
  "models": ["my-model-v1"],
  "endpoint_type": "cloud",
  "capabilities": ["text_generation", "code_generation"],
  "modalities": ["text"],
  "context_length": 8192,
  "cost_per_1k_tokens": 0.005,
  "protocol_compatibility": ["1.0", "2.0"]
}
```

## Adapter Implementation (src/adapter.py)

```python
class MyModelAdapter:
    def __init__(self, config):
        self.api_key = config.get("api_key_env", "MY_API_KEY")
        self.endpoint = config.get("endpoint", "https://api.example.com/v1")

    def health_check(self) -> dict:
        return {"status": "healthy", "model": "my-model-v1"}

    def invoke(self, request) -> dict:
        # Implement model invocation
        return {"content": "...", "usage": {"input": 100, "output": 50}}

    def supports(self, capability: str) -> bool:
        return capability in ("text_generation", "code_generation")
```

## Registration

After implementation, register with Nous:

```bash
nous provider add --adapter my-adapter --config adapter.json
nous provider doctor --provider my-provider
```

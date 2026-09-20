# Nous Pack Guide

## What is a Pack?

A Pack bundles capabilities, providers, and configuration into a single installable unit. Packs are how you extend the Runtime with new functionality.

## Creating Your First Pack (5 minutes)

```bash
nous dev new pack hello
cd hello
nous dev validate
nous pack install .
nous capability run hello.hello
```

## Pack Structure

```
hello/
├── pack.yaml          # Manifest
├── src/
│   ├── __init__.py    # register() called on install
│   └── providers.py   # Provider implementations
├── tests/
│   └── test_providers.py
└── README.md
```

## pack.yaml

```yaml
name: hello
version: 1.0.0
description: My first pack

capabilities:
  - hello.greet

providers:
  - GreetProvider

dependencies:
  runtime: ">=1.0"
```

## Writing a Provider

```python
from remote_terminal.nous_core.provider import Provider

class GreetProvider(Provider):
    name = "greeter"
    version = "1.0.0"
    provider_id = "greeter_hello"

    def list_capabilities(self):
        return ["hello.greet"]

    def invoke(self, capability_id, **params):
        name = params.get("name", "World")
        return {"ok": True, "message": f"Hello, {name}!"}

    def health(self):
        return {"status": "ok"}
```

## Registration

In `src/__init__.py`:
```python
def register(pack):
    from remote_terminal.nous_core.provider import register_adapter
    from .providers import GreetProvider
    register_adapter(GreetProvider())
    pack.registered_providers.append("GreetProvider")
```

## Testing Your Pack

```bash
nous dev test
```

## Sharing Your Pack

For v1.1.0, share the directory. Registry support planned for v1.2.0.

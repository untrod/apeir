# Pack Development Guide

## Overview

A Pack is the distribution unit for the Nous ecosystem. It bundles capabilities, providers, and configuration into a single installable artifact.

## Quick Start

```bash
nous dev new pack my-pack
cd my-pack
nous dev validate
nous pack install .
```

## Pack Structure

```
my-pack/
├── pack.yaml          # Required: manifest
├── src/               # Python module
│   ├── __init__.py    # register() called on install
│   └── providers.py   # Provider implementations
├── tests/             # Pack tests
└── README.md          # Documentation
```

## Manifest (pack.yaml)

```yaml
name: my_pack
version: 1.0.0
description: What this pack does

capabilities:
  - my_pack.action_one
  - my_pack.action_two

providers:
  - MyProvider

dependencies:
  runtime: ">=1.0"

config:
  setting_one: default_value
```

## Writing a Provider

```python
from remote_terminal.nous_core.provider import Provider

class MyProvider(Provider):
    name = "my_provider"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["my_pack.action_one"]

    def invoke(self, capability_id: str, **params) -> dict:
        # Execute the capability
        return {"ok": True, "result": "done"}

    def health(self) -> dict:
        return {"status": "ok"}
```

## Registration

In `src/__init__.py`:

```python
def register(pack):
    from remote_terminal.nous_core.provider import register_adapter
    from .providers import MyProvider
    register_adapter(MyProvider())
    pack.registered_providers.append("MyProvider")
```

## Testing

```bash
nous dev test
```

## Distribution

```bash
nous dev pack           # Create distributable archive
nous pack install .     # Install from directory
```

## Rules

1. Packs must not modify Runtime kernel code
2. Packs must not access another Pack's internal state
3. Pack names must be snake_case
4. Capability IDs must be dot-separated: `pack_name.action`
5. Dependencies are checked on install

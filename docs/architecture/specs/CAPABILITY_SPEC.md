# Capability Specification v1.0

> Every system action is a capability. This document defines the standard.

## Capability Schema

```json
{
  "capability_id": "device.pc.shell",
  "name": "PC Shell Command",
  "category": "device",
  "description": "Execute a shell command on a Windows PC via Agent",
  "risk_level": "high",
  "input_schema": {
    "type": "object",
    "required": ["command"],
    "properties": {
      "command": {"type": "string", "description": "Shell command to execute"},
      "device_id": {"type": "string", "default": "laptop"},
      "cwd": {"type": "string", "description": "Working directory"}
    }
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "stdout": {"type": "string"},
      "stderr": {"type": "string"},
      "returncode": {"type": "integer"}
    }
  },
  "timeout_ms": 60000,
  "requires_approval": true,
  "requires_device": true,
  "provider": "pc_agent",
  "depends_on": [],
  "tags": ["shell", "windows", "dangerous"]
}
```

## Risk Levels

| Level | Policy | Example |
|-------|--------|---------|
| `low` | Auto-execute, audit only | model.reason, rag.search |
| `medium` | Execute, log, notify | model.code, study.plan |
| `high` | Require confirmation | device.pc.shell, file.write |
| `critical` | Confirm + revocable + 2nd audit | system.delete, robot.arm.move |

## Lifecycle

```
register -> enabled -> invoked -> observer verified -> audit logged
                ↓
            disabled (no new invocations, running ones complete)
```

## Validation Rules

1. `capability_id` must be dot-notation: `category.subcategory.action`
2. `risk_level` must be one of: low, medium, high, critical
3. `input_schema` and `output_schema` must be valid JSON Schema
4. `timeout_ms` must be > 0 and <= 600000 (10 min)
5. `provider` must reference a registered provider

## Runtime Manifest Export

The Runtime exports registered capabilities through:

```python
from nous_runtime.capability.manifest import export_capability_manifests

manifests = export_capability_manifests()
```

CLI:

```bash
nous capability manifest
nous capability manifest model.reason --json
nous capability manifest --validate
```

Manifest export filters sensitive metadata fields such as API keys,
tokens, passwords, private keys, and endpoints.

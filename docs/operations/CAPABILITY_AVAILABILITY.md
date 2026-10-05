# Capability Availability — Provider-Dependent Feature Degradation

## Overview

Not every capability is available at all times.  Availability depends on
which providers are registered and whether they are healthy.  Nous
Runtime shows you exactly what's available and what's not — with reasons.

## How Availability Is Determined

A capability is **available** when all three checks pass:

1. **Enabled** — the capability is not disabled in the database
2. **Provider registered** — the capability's declared provider exists
3. **Provider healthy** — the provider reports health status != "down"

If any check fails, the capability is **unavailable** with a specific
reason.

## Viewing Availability

```bash
# CLI
nous capability availability

# Interactive shell
/ capabilities
```

Example output:

```
Available (5):
  model.reason              openai           low
  file.read                 pc_agent         low
  project.scan              nous_core        low
  notification.send         nous_notify      low
  rag.search                chromadb         low

Unavailable (3):
  image.analyze             requires vision provider
  image.generate            requires image provider
  speech.transcribe         requires audio provider
```

## Degradation Paths

### Scenario: DeepSeek-only user (text-only)

If you only configure a DeepSeek provider:

- **Available**: `model.reason`, `model.code` (text capabilities)
- **Unavailable**: `model.transcribe` (requires whisper), `model.tts` (requires edge_tts), `image.*` (requires vision)

The user sees exactly what they can use and why the rest is unavailable.
No surprises, no "it should work but doesn't."

### Scenario: No providers configured

If no providers are registered at all:

- All capabilities show as unavailable
- Reason: "requires X provider"
- The system doesn't crash or throw errors

## Integration with Capability Resolver

The availability check is separate from execution.  Even if a capability
is marked "available", execution can still fail (provider crash, timeout,
etc.).  Availability is a helpful overview, not a hard guarantee.

## API (Python)

```python
from nous_runtime.capability.availability import check_availability

result = check_availability()
for cap in result["available"]:
    print(f"Yes {cap['name']}")
for cap in result["unavailable"]:
    print(f"No {cap['name']} — {cap['reason']}")
```

## Design Principles

- **Honest** — never pretend a capability is available when it isn't
- **Specific** — every unavailable capability has a clear reason
- **Text-first** — users with only a text model can still use every text capability
- **No hardcoding** — availability is derived from live provider state

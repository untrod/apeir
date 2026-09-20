# Observation Layer — Unified Tool Output Schema

## Overview

Every tool and capability execution in the Runtime produces a single,
standardised output: an **Observation**.

Before P3.3, each tool returned ad-hoc dicts with inconsistent shapes.
Now, downstream consumers (Context Builder, LLM, Trace, Memory, future
Task Graph) receive a predictable `Observation` object regardless of
which tool produced it.

## Architecture

```
User Input
    ↓
Intent Detection
    ↓
Tool / Capability Execution
    ↓
Observation
    ↓
Context Builder
    ↓
LLM Invocation
    ↓
Response
```

The Observation is the **contract** between the Tool layer and everything
downstream.

## Schema (v1.0)

```python
@dataclass
class Observation:
    schema_version: str = "1.0"     # schema version for compatibility
    observation_id: str             # unique ID (auto-generated)
    tool: str                       # e.g. "project.scan"
    capability: str                 # resolved capability
    status: str                     # "success" | "failed" | "skipped"
    data: dict                      # structured result (JSON-serialisable)
    errors: list[str]               # error messages (empty on success)
    duration_ms: float              # wall-clock time
    started_at: str                 # ISO-8601 UTC
    finished_at: str                # ISO-8601 UTC
    metadata: dict                  # arbitrary annotations
```

## Factory Methods

```python
# Success
obs = Observation.success("project.scan", {"files": 1722, "languages": {...}})

# Failure
obs = Observation.failure("tool.file.read", ["README.md not found"])

# Skipped
obs = Observation.skipped("tool.x", "unavailable in this mode")
```

## LLM Context Block

`Observation.to_context_block()` renders a structured text block:

```
[Observation a1b2c3d4]
Tool: project.scan
Status: success
Duration: 245ms
Data:
{
  "workspace": "/srv/nous/project",
  "files": 1722,
  "languages": {"python": 1216, "markdown": 118}
}
```

The LLM never receives raw Python dicts, file paths, or internal state.
It receives structured, sanitised context. Absolute path values in common
path fields such as `workspace`, `root`, and `path` are redacted in the
context block; the original `Observation.data` remains unchanged for
internal runtime consumers.

## Tools That Produce Observations

| Tool | Observation.data keys |
|------|----------------------|
| `project.scan` | workspace, files, total_size_kb, languages, scanned_at |
| `project.summary` | workspace, project, files, pending_tasks, recent_events, last_events, tasks |
| `project.tasks` | total, tasks[] |
| `project.memory` | total_events, recent[] |
| `tool.file.read` | file, size, content |
| `tool.project.search` | query, total, results[] |

## Capability Execution

New Runtime code should call:

```python
from nous_runtime.capability.resolver import execute_capability_observation

obs = execute_capability_observation("model.reason", prompt="...")
```

`execute_capability()` remains as a compatibility adapter for existing
SDK, CLI, and dispatcher callers. Internally it now creates an
`Observation` first and converts it into the legacy `ExecutionResult`.

Capability resolver failures, provider failures, and execution failures
therefore carry the same fields as local tool observations:

- `status`
- `errors`
- `duration_ms`
- `metadata.provider_id`
- `metadata.error_code`

## Provider Invocation

Provider invocation is also Observation-first:

```python
from nous_runtime.provider import invoke_via_provider_observation

obs = invoke_via_provider_observation("openai", "model.reason", {"prompt": "..."})
```

`invoke_via_provider()` is kept for legacy callers and converts the
Observation back to the old dict shape. New Runtime code should not parse
raw provider dicts directly.

## Design Rules

1. **No downstream consumer receives a raw dict from a tool.**
   Everything goes through `Observation`.
2. **Schema versioned** — consumers check `schema_version` for compatibility.
3. **Every tool returns Observation** — even on failure.
4. **Every new capability execution path returns Observation first.**
5. **Every new provider execution path returns Observation first.**
6. **Observation.id** is unique and traceable through logs and timeline.

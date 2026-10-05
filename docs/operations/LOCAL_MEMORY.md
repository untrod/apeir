# Local Memory

## Overview

Nous stores project memory in `.nous/memory/` as append-only JSONL files.
There is no vector database, cloud storage, or network dependency in P3.4.

## Memory Streams

| File | Purpose |
|------|---------|
| `events.jsonl` | Structured runtime and task events |
| `timeline.jsonl` | Compatibility alias for older timeline users |
| `decisions.jsonl` | User-confirmed decisions with rationale |
| `summaries.jsonl` | Compact project, task, and graph summaries |
| `facts.jsonl` | Stable facts with supersession metadata |
| `experiences.jsonl` | Provider/capability reliability candidates |
| `artifacts.jsonl` | References to generated artifacts |

`timeline.jsonl` keeps the older `{id, timestamp, type, detail}` shape.
New code should prefer `events.jsonl`.

## Record Shape

Structured records share common fields:

```json
{
  "schema_version": "1.0",
  "memory_id": "mem_a1b2c3d4e5f6",
  "record_type": "event",
  "project_id": "nous",
  "task_graph_id": "",
  "task_id": "",
  "observation_id": "obs123",
  "capability_id": "project.scan",
  "provider_id": "",
  "created_at": "2026-07-09T14:30:00Z",
  "source_type": "observation",
  "confidence": 1.0,
  "tags": ["event", "project.scan"],
  "metadata": {}
}
```

Facts also include `key`, `value`, `stable_key`, `supersedes`, and
`active`. Files remain append-only; `active_facts()` returns the latest
fact per stable key.

## Python API

```python
from nous_runtime.project.memory import (
    add_event, add_decision, add_summary, add_fact,
    active_facts, recent_events, search_memory,
)

add_event(workspace, "scan_completed", "142 files indexed")
add_decision(workspace, "Use SQLite?", "yes", "Zero dependency")
add_summary(workspace, "Completed P3.4", tags=["memory"])
add_fact(workspace, "project.files.total", 142, source="project.scan")

events = recent_events(workspace, limit=20)
facts = active_facts(workspace)
matches = search_memory(workspace, "project.scan")
```

## Observation Ingestion

Long-term memory ingests `Observation` objects, not raw provider output.
The rule-based ingestor currently extracts:

- `project.scan` success into events and project facts
- `task.execute` into task events and task summaries
- `plan.execute` into graph events and graph summaries
- failed provider/capability observations into experience candidates
- artifact metadata into artifact references

Raw prompts, complete responses, API keys, tokens, passwords, private keys,
and similar fields are not stored by default.

## CLI

```bash
nous memory status
nous memory search "project.scan"
nous memory facts
nous memory decisions
nous memory summaries
nous memory experiences
```

Shell:

```text
/memory
/memory facts
/memory decisions
/memory search project.scan
```

## Design Notes

- Append-only writes.
- Malformed JSONL lines are skipped on read.
- Fact deduplication is logical through `stable_key` and `supersedes`.
- Retrieval is keyword and structured-filter based; no vector database is used.

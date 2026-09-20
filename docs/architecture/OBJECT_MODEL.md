# Nous Object Model v1.0

## Purpose

All core objects in the Runtime share a common identity, lifecycle, and status model. No object defines its own ID format, version scheme, or state machine independently.

## Base Object Structure

```yaml
metadata:
  id: "string"           # Unique ID (prefix_YYYYMMDD_8hex)
  kind: "string"         # Object kind (Goal, Plan, Task, Job, Capability, Provider, Pack, Node, Policy)
  api_version: "string"  # API version (e.g., "v1")
  name: "string"         # Human-readable name
  namespace: "string"    # Isolation namespace (default: "default")
  owner: "string"        # Owner reference
  labels: {}             # Arbitrary key-value labels
  created_at: "string"   # ISO 8601 UTC
  updated_at: "string"   # ISO 8601 UTC
  generation: 0          # Monotonic update counter

spec:
  # Object-specific desired state

status:
  phase: "string"        # Current lifecycle phase
  health: "string"       # ok | degraded | down | unknown
  conditions: []         # List of Condition objects
  message: "string"      # Human-readable status
  observed_at: "string"  # Last observation timestamp
```

## Condition

```yaml
type: "string"           # Condition type (Ready, Healthy, Progressing, Degraded)
status: "string"         # True | False | Unknown
reason: "string"         # Machine-readable reason
message: "string"        # Human-readable message
last_transition: "string"
```

## Lifecycle Phases by Kind

| Kind | Phases |
|------|--------|
| Goal | Pending -> Planning -> Active -> Completed -> Failed -> Cancelled |
| Plan | Pending -> Building -> Ready -> Executing -> Completed -> Failed |
| Task | Pending -> Scheduled -> Running -> Completed -> Failed -> Cancelled |
| Job | Pending -> Claimed -> Running -> Done -> Failed -> Cancelled |
| Capability | Registered -> Validated -> Enabled -> Ready -> Disabled -> Deprecated -> Unregistered |
| Provider | Discovered -> Connected -> Authenticated -> Ready -> Degraded -> Disconnected |
| Pack | Installed -> Validated -> Enabled -> Ready -> Disabled -> Removed |
| Node | Discovered -> Connected -> Authenticated -> Ready -> Degraded -> Disconnected |
| Policy | Defined -> Enabled -> Active -> Disabled -> Removed |

## ID Generation

- Format: `{prefix}_{YYYYMMDD}_{8-hex-rand}`
- Prefix by kind: `goal_`, `plan_`, `task_`, `job_`, `cap_`, `prov_`, `pack_`, `node_`, `pol_`
- Implementation: `nous_core/ids.py`

## Versioning

- All objects carry `api_version` (e.g., "v1")
- Schema evolution: add fields, never remove; bump api_version on breaking change
- Backward compatibility: v1 readers must accept v1 objects with unknown fields

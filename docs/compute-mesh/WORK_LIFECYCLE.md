# Distributed Work lifecycle

The Controller owns the durable Work record. The Node owns execution reality.
Neither side may infer the other side's state without signed evidence.

```text
CREATED
  -> SCHEDULED
  -> ASSIGNED
  -> RUNNING
  -> SUCCEEDED
  -> VERIFIED
  -> COMMITTED
```

- `CREATED`: intent and requirements are durable; no placement has occurred.
- `SCHEDULED`: placement was attempted. No matching Node leaves the Work here.
- `ASSIGNED`: one deterministic placement and immutable assignment exist.
- `RUNNING`: the assigned Node signed an acknowledgement of `WORKLOAD_START`.
- `SUCCEEDED`: a signed successful terminal Node result exists.
- `VERIFIED`: receipt bindings and committed Artifact digests passed.
- `COMMITTED`: the verified result is the durable workflow-visible outcome.

Failure and uncertainty are explicit:

```text
ASSIGNED/RUNNING -> FAILED
ASSIGNED/RUNNING/SUCCEEDED -> RECOVERING or UNKNOWN
FAILED/UNKNOWN -> RECOVERING
```

`UNKNOWN` means an at-most-once effect may have happened but cannot be proven.
It is not permission to retry. Reassignment is never implicit; any recovery
that changes a Node or effect must be an explicit policy decision.

## Invariants

- Invalid transitions fail closed and require a recorded reason.
- `ASSIGNED` and `RUNNING` require the same Node binding.
- One assignment produces at most one immutable dispatch record.
- Output and evidence references are immutable once recorded.
- `COMMITTED` is terminal.
- Repeated terminal results do not create new effects or Artifacts.

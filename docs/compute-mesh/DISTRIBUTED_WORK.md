# Distributed Work

APEIR Compute Mesh represents a distributed operation as a durable `Work`
before it selects a Node or causes an external effect. This is a Distribution
layer contract; it does not change the Kernel, Kernel authority, or the
compatibility Node Protocol.

## Contract

A Work records:

- a stable `work_id`, creator, priority, and intent;
- architecture, capability, memory, and GPU requirements;
- immutable `artifact://` input references;
- delivery and signed-receipt policy;
- the assigned Node, output artifacts, and evidence references;
- a timestamped state history.

The state machine is:

```text
CREATED -> SCHEDULED -> ASSIGNED -> RUNNING -> SUCCEEDED
                                                |
                                                v
                                            VERIFIED -> COMMITTED

FAILED -> RECOVERING
UNKNOWN -> RECOVERING
```

Invalid transitions fail closed. `ASSIGNED` and `RUNNING` require an explicit
Node binding. A Work cannot silently move to another Node. `UNKNOWN` is a
first-class result for effects whose outcome cannot be proven; it is never an
instruction to replay a write or execution.

## Create and inspect

Creation persists the Work but does not dispatch it:

```bash
apeir-controller submit-work \
  --state-dir /var/lib/apeir-controller \
  --intent "Run computer vision inference" \
  --architecture aarch64 \
  --os linux \
  --capability cuda \
  --minimum-memory-bytes 8589934592 \
  --gpu-required \
  --input-artifact artifact://sha256/<digest> \
  --creator operator
```

Read one Work or list the registry:

```bash
apeir-controller work-status <work-id> \
  --state-dir /var/lib/apeir-controller

apeir-controller work-status \
  --state-dir /var/lib/apeir-controller
```

## Deterministic placement

The rule-based scheduler evaluates only signed, recently observed Node facts:

```bash
apeir-controller schedule-work <work-id> \
  --state-dir /var/lib/apeir-controller
```

It checks architecture, operating system, every required capability, available
memory, and reported GPU devices. The decision lists every candidate and its
rejection reasons. A successful decision moves the Work from `CREATED` through
`SCHEDULED` to `ASSIGNED`; it remains `placement-only`, grants no capability,
and does not dispatch an effect. If no Node matches, the Work stays
`SCHEDULED` and the command exits unsuccessfully.

## Execute and reconcile

An assigned Work is staged for the running Controller without bypassing the
existing signed Node Protocol:

```bash
apeir-controller dispatch-work <work-id> \
  --state-dir /var/lib/apeir-controller

apeir-controller reconcile-work <work-id> \
  --state-dir /var/lib/apeir-controller
```

`dispatch-work` verifies every input in the Controller CAS before creating an
at-most-once request. The Node receives all inputs before `WORKLOAD_START`. Its
signed acknowledgement advances the Work to `RUNNING`; a terminal result is
not trusted until identity, assignment, receipt, and Artifact digests verify.

Successful reconciliation stores separate output and evidence Artifacts, then
advances `SUCCEEDED -> VERIFIED -> COMMITTED`. Repeating dispatch or
reconciliation is idempotent. A `RECOVERY_REQUIRED` result becomes `UNKNOWN`
and is never replayed automatically.

For the wire path and trust boundary, see
[Distributed execution](DISTRIBUTED_EXECUTION.md). For exact state and restart
semantics, see [Work lifecycle](WORK_LIFECYCLE.md) and
[Execution recovery](EXECUTION_RECOVERY.md).

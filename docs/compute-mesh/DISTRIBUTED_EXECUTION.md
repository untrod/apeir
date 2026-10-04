# Distributed execution

APEIR Distribution connects deterministic placement to the existing Node
Protocol. It does not introduce a second execution authority or modify APEIR
Kernel contracts.

```text
Distributed Work
  -> deterministic placement
  -> durable WorkAssignment
  -> provider spool
  -> Nous Node Protocol v1
  -> bounded Node capability
  -> signed WORKLOAD_STATUS
  -> receipt and Artifact verification
  -> COMMITTED
```

## Assignment and dispatch

`WorkAssignment` binds one `work_id` to one `node_id`, a requirements snapshot,
immutable input Artifact references, and an at-most-once execution policy. The
placement decision remains `placement-only` and grants no capability.

Dispatch requires all of the following:

- the Work is `ASSIGNED`;
- the execution capability is part of the admitted requirements;
- every input uses `artifact://sha256/<digest>` and verifies in Controller CAS;
- delivery is `at_most_once`;
- assignment, target, request, and effect bindings are immutable.

The bridge stages the existing `nous.remote-provider-request/v1` contract. The
running Controller sends input Artifacts before the existing
`WORKLOAD_START` message. Compatibility protocol identifiers remain unchanged.

## Observation and verification

The Node verifies Controller identity and executes only a locally registered,
bounded capability. Its signed `ACK` proves receipt of the assignment and moves
the Work to `RUNNING`. Its signed terminal status is persisted before it is
projected into a Work result.

Controller reconciliation verifies:

1. the enrolled Node signature and replay window;
2. the result source against the durable assignment;
3. at-most-once request and target bindings;
4. the OperationReceipt;
5. output and evidence bytes in CAS by SHA-256.

Only after these checks does the Work become `COMMITTED`. Model output, a Node
claim, or a successful process exit alone is not sufficient.

Reality simulation Work additionally sets `require_effect_verification=true`.
For this Work, receipt and CAS checks stop at `VERIFIED`. A separate read-only
Distributed Work on the same assigned Node acquires an Observation, and only an
independent `MATCH` permits `COMMITTED`. `MISMATCH` and `UNKNOWN` keep the Work
uncommitted. The additive `WorkRequirements.node_ids` constraint keeps both
mutation and observation on the Device's hosting Node. Ordinary Work retains
its existing receipt/CAS commit behavior and dispatch bindings.

## Workflow integration

`DistributedWorkflowAdapter` is an ordinary handler for the existing
`WorkflowRuntime`. It creates a stable Work per workflow run and step, waits for
verified completion, and returns Artifact references to the next step. A later
step may declare `input_from_steps` to consume those Artifacts. This adapter is
not a new scheduler or workflow engine.

`RealityOperationWorkflowHandler` supplies the existing adapter's verification
finalizer. The AgentSession planner returns an ordinary Plan step with action
`reality.operation`, `device_id`, `capability=device.state.set`, structured
`mutation`, and non-empty `expected_effect`. Mutation inputs are stored in CAS
before dispatch. Workflow failure checkpoints retain the Work reference;
resuming the same run consumes that Work and its immutable arguments. See the
[Reality architecture audit](../architecture/REALITY_ARCHITECTURE_AUDIT.md).

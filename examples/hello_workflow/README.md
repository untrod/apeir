# Hello workflow

A minimal definition accepted by the existing durable Workflow engine. After
the [Source Quick Start](../../docs/operations/getting-started/QUICK_START.md), run
from the checkout; these commands persist a definition and run in the selected
local workspace:

```bash
apeir --no-intelligence workflow validate examples/hello_workflow/workflow.json
apeir --no-intelligence workflow register examples/hello_workflow/workflow.json
apeir --no-intelligence workflow run example.workflow
```

The single pure transform returns `Hello from APEIR`; this is not a physical
effect or a Governance bypass. Workflow registration and the run are persisted
by the existing owners. Use the [Verified Execution Demo](../hello_runtime/README.md)
for approval, Node execution and independent effect verification.

The [HTTP SDK examples](../sdk/python_quickstart.py) require an already-running,
authenticated Server Runtime and this registered definition. They are not the
zero-key standalone Demo; native Server prerequisites still apply.

## Consume a governed simulated Automation

Select a dedicated writable workspace before running the commands below. This
fixed structured template reads simulated firmware and proposes a version-only
update through the existing signed Node/Work path. Each new firmware Work needs
its own human approval. No physical device, model credentials or arbitrary tool
executor is involved.

```bash
export NOUS_WORKSPACE_ROOT=/tmp/apeir-automation-example
apeir --no-intelligence automation add "Simulated firmware" --simulation
# Use the automation id returned above.
apeir --no-intelligence automation trigger AUTO_ID --trigger-key first --simulation
# Inspect and approve the exact original request returned by the waiting run.
apeir --no-intelligence approval show APPROVAL_ID --json
apeir --no-intelligence approval approve APPROVAL_ID
apeir --no-intelligence automation resume AUTO_ID RUN_ID --simulation
apeir --no-intelligence automation history AUTO_ID --simulation
```

The result identifies the original Work, signed receipt, fresh independent
observation, verification and CAS references. Only MATCH allows that Work to be
COMMITTED. Repeating `first` returns the same run; a new trigger key proposes
a new Work with separate authority. Restart uses the same workspace and original
run. `automation reconcile AUTO_ID RUN_ID --simulation` consults original
receipt journals and independently observes; it never re-enters mutation.
`automation cancel` fences future admission, without claiming that a previous
effect stopped or never happened.

For a single due proposal, add `--due-at 2026-10-12T12:00:00Z`, then invoke
`automation run-due --limit 1 --simulation`. Due polling consumes each proposal
once; there is no background timer or recurring Cron support. Legacy free-text
Automation configuration remains UNQUALIFIED. Read the
[Automation execution contract](../../docs/architecture/EXECUTION_PATH.md#bounded-automation-consumer)
for API identity/permission requirements and scope limits.

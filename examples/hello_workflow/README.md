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

# Project Runtime and workspace state

An APEIR workspace is a filesystem root containing the compatibility directory
`.nous/`. A Project is an existing Project Runtime record with a lifecycle,
plan and checkpoints; it is not a second Work or authority system. See
[state ownership](STATE_OWNERSHIP.md) for canonical owners and
[the Source Quick Start](../operations/getting-started/QUICK_START.md) for onboarding.

## Current public commands

```bash
apeir project --help
apeir project create thermal-review --description "Review simulated evidence" --json
apeir project list --json
```

Use `apeir project show`, `start`, `continue`, `pause`, `resume`, `cancel`,
`progress`, `checkpoints`, `events` and `plan` according to their `--help`.
These manage existing Project records. The old `project init` and `project scan`
commands are not supported public commands. Shell-specific workspace detection
and `/scan` are separate from the Project lifecycle.

## Persisted state and safety

The existing workspace helper discovers `.nous/` upwards from the current path,
or uses `NOUS_WORKSPACE_ROOT` when configured. Individual Runtime owners store
their data under this workspace; the directory is not an authorization source.
Legacy workspace initialization retains project/config/goals/tasks files,
memory/index/traces and artifacts. AgentSession, Workflow, Governance,
Distributed Work, Node and Reality stores remain owned by their canonical
implementations, not this document or a new unified database.

Keep `.nous/`, generated artifacts, credentials, private keys and local databases
out of source control. Local-first persistence does not mean every operation is
offline: an explicitly configured Provider may use network resources under its
existing policy and credential boundaries.

Do not delete workspace state to "reset" uncertain effects or clear revocation.
Stopping a process or deleting evidence cannot undo an effect. Interrupt future
admission and reconcile persisted evidence, acquire independent observation and
verify through the existing recovery path before retiring state.

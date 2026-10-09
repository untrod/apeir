# Example Gallery

- [Verified Execution](hello_runtime/README.md) — real governed simulated firmware Work, independent observation, MATCH-only commit and no-replay recovery.
- [Hello Provider](hello_provider/README.md) — public SDK, explicit read-only Governance, signed Node Work, CAS evidence, error mapping and removal.
- [Hello Skill](hello_skill/README.md) — existing Registry discovery, instruction loading, CAS provenance and persistent disable; no authority or operation execution.
- `hello_connector/` — workspace-scoped Connector execution with Governance blocking writes.
- `hello_plugin/` — checksum-bound, permission-declared Plugin lifecycle.
- [Hello Workflow](hello_workflow/README.md) — runnable registered pure-transform definition.
- `sdk/python_quickstart.py` — governed Workflow execution through the Python Server Runtime client.
- `sdk/typescript_quickstart.ts` — the same Workflow path through the TypeScript client.

Start with the [Source Quick Start](../docs/operations/getting-started/QUICK_START.md).
Use dedicated workspaces and retain uncertain-effect evidence until reconciled;
do not publish private keys or Runtime databases. The connector uses a contract
test double, not full Governance acceptance; Plugin lifecycle is not isolated
execution qualification. HTTP SDK examples need an authenticated existing
Server Runtime. Legacy edge/capture scripts are compatibility examples, not
recommended Developer Preview entry points. No example establishes physical
hardware or production-release acceptance.

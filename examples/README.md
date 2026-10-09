# Example Gallery

- [Verified Execution](hello_runtime/README.md) — real governed simulated firmware Work, independent observation, MATCH-only commit and no-replay recovery.
- [Hello Provider](hello_provider/README.md) — public SDK, explicit read-only Governance, signed Node Work, CAS evidence, error mapping and removal.
- [Hello Skill](hello_skill/README.md) — existing Registry discovery, instruction loading, CAS provenance and persistent disable; no authority or operation execution.
- `hello_connector/` — workspace-scoped contract probe with an approval test double, not full Governance acceptance.
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

## Scientific computation and reports

The existing [thermal scientific reference](../docs/architecture/GOVERNED_SCIENTIFIC_RUNTIME.md)
composes SimulationRuntime → independent SciPy DOP853 comparison → Research
Claim/Evidence → ArtifactRegistry → DocumentRuntime DOCX/PDF. It does not use a
second scientific or document system. Current Cloud report generation is
**BLOCKED** because the existing local-sandbox path requires a ready strong
Windows Sandbox backend. Numerical dependencies alone are insufficient; no
ordinary host fallback, fabricated report or theorem-proof claim is allowed.

The existing [native qualification command](../scripts/acceptance/scientific_native_acceptance.ps1)
contains the reproducible inputs and governed API flow, approval of each original
request, artifact hashes, provider/code versions, Claims, report structure and
cleanup checks. It requires qualified native components and strong isolation;
it is not a zero-prerequisite Cloud command. Its reference inputs are:

| Input | Value |
| --- | --- |
| Simulation / analysis | spacecraft-thermal/v1 / spacecraft-thermal-analysis/v1 |
| Initial / external temperature | 290 K / 3 K |
| Solar flux cases / area | 1,000 and 1,361 W/m² / 2 m² |
| Emissivity / absorptivity / thermal capacity | 0.8 / 0.7 / 10,000 J/K |
| Solver / step / duration / seed | explicit Euler / 1 s / 30 s / 42 |
| Independent reference / tolerance | SciPy DOP853 / 0.05 K |
| Network / reports | none / DOCX and PDF |

A qualified run must preserve these inputs, exact computational versions,
per-case maximum error and RMSE, evidence identifiers and limitations. Numerical
agreement validates this bounded computation; symbolic expressions are not a
formal mathematical proof. Existing scientific/simulation/report tests remain
the structural and integrity checks. Historical Windows evidence is retained;
this source preview claims no new native report qualification.

# Examples

<!-- Compatibility anchors for existing documentation links. -->
<a name="example-gallery"></a>


Start from an existing supported task. These examples use the installed Runtime
and public interfaces; they do not require reading Core internals. Use a
dedicated workspace and the matching [Quick Start](../docs/operations/getting-started/QUICK_START.md).

| Task | Prerequisite | Example / actual outcome |
| --- | --- | --- |
| Start Runtime and open Studio | Downloaded matching Runtime/Studio pair, Python3.10+ | [Quick Start](../docs/operations/getting-started/QUICK_START.md): authenticated service, real file/status views; no model needed |
| Inspect execution and recovery | Installed public CLI, empty dedicated workspace | [Verified Execution](hello_runtime/README.md): original simulated Work, approval, receipt, independent observation and effect-count-one recovery |
| Run a supported Workflow | Installed CLI and the checked-in definition | [Hello Workflow](hello_workflow/README.md): validate/register, completed pure transform, original Run and same-key recovery |
| Add a Provider adapter | Matching beta SDK and this example copied outside the checkout | [Hello Provider](hello_provider/README.md): read-only signed loopback Work returning a greeting, refusal and removal checks; no cloud model call |
| Add a declarative Widget | Running authenticated Runtime/Studio, independent lifecycle approval | [System Monitor](studio_system_monitor/README.md): review/install/enable, sanitized status, disable/revoke/remove; no arbitrary JavaScript |

For an actual API or local model, use [Models and Providers](../docs/operations/guides/PROVIDER_GUIDE.md).
It requires the real endpoint, credentials and authorized inference budget.
A successful deterministic Provider example does not qualify that model.

## More examples

- [Hello Skill](hello_skill/README.md): catalog, instruction loading, CAS integrity
  and disable; instruction loading does not execute its suggested tools.
- [Connector](hello_connector/README.md): contract probe with an approval test
  double, not complete Governance acceptance.
- [Plugin](hello_plugin/README.md): checksum/permission-declared lifecycle, not
  arbitrary-code isolation qualification.
- [Python HTTP client](sdk/python_quickstart.py) and
  [TypeScript HTTP client](sdk/typescript_quickstart.ts): require an existing
  authenticated service, registered Workflow and current permission.

Keep original Run/Work records after a lost response. Do not publish private Node
keys, Runtime databases or credentials. Legacy edge/capture scripts remain
compatibility examples, not recommended Preview entry points. No example alone
establishes physical hardware, live-model or native-installation acceptance.

<details>
<summary>Scientific reference: prerequisites and retained parameters</summary>

## Scientific computation and reports

The existing [thermal scientific reference](../docs/architecture/GOVERNED_SCIENTIFIC_RUNTIME.md)
composes SimulationRuntime → independent SciPy DOP853 comparison → Research
Claim/Evidence → ArtifactRegistry → DocumentRuntime DOCX/PDF. It does not use a
second scientific or document system. Current Cloud report generation is
**BLOCKED** because the existing local-sandbox path requires a ready strong
Windows Sandbox backend. Numerical dependencies alone are insufficient; no
ordinary host fallback, fabricated report or theorem-proof claim is allowed.

After installing the optional scientific dependencies from the Quick Start,
check actual prerequisites without executing a calculation:

```bash
python -m scripts.acceptance.scientific_preview_preflight
```

The [read-only probe](../scripts/acceptance/scientific_preview_preflight.py)
prints actual isolation and provider versions. Exit **2 / BLOCKED** is expected
in this Cloud environment. READY_FOR_GOVERNED_RUN is only a prerequisite result,
never report generation or acceptance; `execution_performed` stays false and
`reports_created` stays empty. Continue through the existing governed native
qualification flow only when its separate prerequisites are met.

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

</details>

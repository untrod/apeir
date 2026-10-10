# Source Quick Start

This is the recommended entry point for APEIR Developer Preview. Use Git,
Python 3.10–3.12 and a writable checkout. No model API key, GPU or real device
is needed for source inspection and simulated examples. Current acceptance
and blockers live only in [ROADMAP](../../../ROADMAP.md).

## Install

```bash
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
```

Activate on Linux/macOS:

```bash
source .venv/bin/activate
```

Or on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the source package and check the actual entry points:

```bash
python -m pip install -e .
apeir version
apeir --help
apeir-node --help
apeir-controller --help
```

The package is `apeir-distribution`, currently `0.1.0-rc1` (Python metadata may
normalize it to `0.1.0rc1`). `nous`, `nous_runtime` and `NOUS_*` remain
compatibility names. Do not install obsolete `nous-runtime==0.1.0a0` or use an
unverified one-line installer, container image or Homebrew formula.

## First inspection

```bash
apeir --no-intelligence status
apeir --no-intelligence capability list
apeir --no-intelligence provider list
```

These commands inspect actual local Runtime state. Missing Providers, Kernel
services or optional dependencies are reported; they do not establish execution
or hardware acceptance.

## First verified execution

```bash
apeir demo --workspace ./demo-match --phase prepare --json
apeir demo --workspace ./demo-match --phase resume --approve-once --json
```

Use an empty dedicated directory. The first command persists an AgentSession,
Plan and Work and pauses for approval. The second explicitly approves once as
the local OS user, resumes the original Work through signed Node execution,
observes independently and commits only on MATCH. Without approval no mutation
occurs. [Verified Demo details](../../../examples/hello_runtime/README.md) include
Deny, MISMATCH, UNKNOWN, lost-response reconciliation and process restart commands.
This is simulated Runtime-service execution; Kernel is not traversed and no
physical or remote-human acceptance is claimed. Keep generated private keys and
databases out of Git and public issue attachments.

See the [example gallery](../../../examples/README.md),
[public Developer SDK](../../development/DEVELOPER_PLATFORM.md) and
[canonical architecture](../../architecture/README.md). Models never grant
authority; a Receipt is not an Observation, and UNKNOWN cannot commit an effect.

## Public SDK examples

After the source installation above, install the existing Provider SDK from the
same checkout; no published SDK wheel is assumed:

```bash
python -m pip install -e sdk/provider/python
python examples/hello_provider/run_example.py --workspace ./provider-demo
python examples/hello_skill/run_example.py --workspace ./skill-demo
```

Use separate empty directories. The [Provider example](../../../examples/hello_provider/README.md)
executes an explicitly allowed read-only Work through a signed Node and checks
denied/unknown/approval-required requests. The [Skill example](../../../examples/hello_skill/README.md)
installs, discovers, loads and disables actual instructions with CAS provenance;
it grants no authority and runs no device operation. Both import public SDK
contracts, not internal Runtime modules. Their printed workspaces retain evidence.

## Development and optional components

For repository tests and the numerical reference task:

```bash
python -m pip install -e ".[dev,a2a,mcp,scientific]"
python -m pytest -q tests/repository tests/developer_platform
```

For the existing thermal report reference, run
`python -m scripts.acceptance.scientific_preview_preflight` to inspect actual
prerequisites. Exit 2 / BLOCKED is expected without the existing strong sandbox;
the probe performs no computation or report generation. See the
[scientific gallery](../../../examples/README.md#scientific-computation-and-reports)
for inputs, the independent reference and the qualified native command.

The [contribution guide](../../../CONTRIBUTING.md) defines full validation and
supported process-lifecycle environments. This focused command does not replace
the full merge/release gate. Desktop development needs Node.js 22; follow
[Desktop architecture](../../architecture/DESKTOP_ARCHITECTURE.md).
Install heavy AI, local LLM and installer extras only when specifically needed.

The [Compute Mesh runbook](../compute-mesh/OPERATIONS.md) covers persistent
Controller/Node deployment. [Installation notes](../INSTALLATION.md) explain
optional dependencies and platform boundaries. Native binary release acceptance
requires the separate [Release Runbook](../../acceptance/RELEASE_RUNBOOK.md).

## Troubleshooting and feedback

Run `apeir doctor`, retain the command, platform and exact error, and follow
[troubleshooting](TROUBLESHOOTING.md). Inspect diagnostics before sharing and
remove credentials and private paths. Report reproducible issues through
[GitHub](https://github.com/untrod/apeir/issues); security reports follow
[SECURITY](../../../SECURITY.md).

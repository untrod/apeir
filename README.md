# APEIR

APEIR is an open, local-first distribution for governed execution across models,
software tools, compute nodes, and device adapters. It combines a native
desktop application, a headless Runtime API, provider and extension adapters,
and deployment services with the independently released
[APEIR Kernel](https://github.com/untrod/apeir-kernel).

APEIR Kernel is the authority for workloads admitted through NKI: admission,
permits, resource leases, scheduling, durable Kernel state, governed effects,
and execution proof. This repository owns the product experience, integrations,
and bounded local services. It does not contain a second copy of the Rust Kernel.

[简体中文](README.zh-CN.md) · [Architecture](docs/architecture/FOUNDATION_1_0.md) ·
[Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## Release status

The current line is **APEIR Distribution 0.1.0-rc1**. It is intended for
development and evaluation on Windows 10 x64. It is not yet a general-
availability release. Remote multi-host, Linux, Jetson, MCU, and physical
device support remain qualification targets and are not implied by a local or
simulated test result.

## Components

- **Desktop** — native Tauri application for setup, chat, tasks, documents,
  development tools, environments, simulations, nodes, and diagnostics.
- **Runtime API** — authenticated loopback service and product orchestration.
- **Kernel client** — the only production route for Kernel-managed requests to NKI.
- **Providers** — model, MCP, skill, document, scientific, and device adapters.
- **Node services** — identity, relay, artifact transfer, deployment, health,
  cancellation, and recovery.
- **Cost control** — request limits, daily budgets, retry budgets, normalized
  usage receipts, and per-task/model/credential-reference accounting.

## Execution boundary

```text
Kernel-managed workload
  Desktop / CLI / API / extension
    → Runtime policy and cost preflight
    → NKI authentication and version validation
    → Kernel admission → permit → lease → execution → receipt
    → Runtime projection and user-visible result

Bounded local service
  Desktop / CLI / API
    → Runtime authorization and optional one-use approval
    → local document / environment / network / simulation service
    → Runtime event and artifact evidence
```

Production construction fails closed when the Kernel is unavailable or the NKI
version is unsupported. Direct Provider execution exists only as an explicit
compatibility/test mode and is never selected automatically.

Local file, document, environment, network, simulation, and scientific services
are governed by the Runtime authorization layer in this candidate. They report
`execution_scope=runtime-service` and `kernel_traversed=false`; they are not
represented as Kernel-executed operations.

## Requirements

- Windows 10 x64
- Python 3.10–3.12 for source development
- Node.js 20 and Rust stable for Desktop development
- Visual Studio 2022 C++ Build Tools and a Windows 10/11 SDK for native builds
- A separately checked out APEIR Kernel at the revision recorded in
  [`runtime-components.lock.json`](runtime-components.lock.json)

## Quick Start

```powershell
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Validate the Runtime:

```powershell
python -m pytest -q
python -m ruff check nous_runtime tests scripts integrations sdk
python scripts/security_scan.py
```

Validate the Desktop:

```powershell
cd desktop
npm ci
npm run lint
npm test
npm run typecheck
npm run build
```

Build the Windows x64 installer and portable bundle from the repository root:

```powershell
.\scripts\build-windows-x64-launcher.ps1 -KernelRoot C:\path\to\apeir-kernel
```

The build refuses a Kernel checkout that does not match the locked revision.
Generated sidecars, installers, databases, logs, credentials, and validation
evidence are excluded from the public source tree.

## Cost controls

APEIR applies limits before a model request reaches the Kernel. Defaults can be
changed through `APEIR_MAX_INPUT_TOKENS`, `APEIR_MAX_OUTPUT_TOKENS`,
`APEIR_MAX_REQUEST_TOKENS`, `APEIR_MAX_DAILY_TOKENS`,
`APEIR_MAX_DAILY_COST_USD`, `APEIR_MAX_MODEL_ATTEMPTS`,
`APEIR_MAX_RETRY_TOKENS`, and `APEIR_MAX_RETRY_COST_USD`.

Provider prices are intentionally configuration data because vendors change
them independently of APEIR releases. Point `APEIR_MODEL_PRICING_FILE` to a
reviewed catalog using [`config/model-pricing.example.json`](config/model-pricing.example.json).
Unknown prices still receive Token limits, but cost estimates remain zero until
a price is configured. Actual Provider usage is normalized and stored locally;
credential values are never written to the usage database.

## Compatibility

The public brand, desktop title, package, and new command names use APEIR.
The `nous_runtime` Python import, `nous` command aliases, `NOUS_*` environment
variables, and `nous.*.v1` protocol identifiers remain available for migration
and wire compatibility. Protocol identities are not renamed in place.

## Security

The Runtime API and NKI listener bind to loopback by default. Provider secrets
are held by the operating-system credential store or referenced environment
variables, never declarative source configuration. Effectful work requires
explicit authority and produces evidence; unsupported or unverified paths fail
closed.

Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/untrod/apeir/security/advisories/new).
Do not place credentials, private prompts, runtime state, or exploit details in
public issues.

## License

Apache License 2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE), and the third-party
notices generated for each release bundle.

# APEIR

An open execution, governance and verification runtime for heterogeneous
intelligence and real-world resources.

APEIR uses local-first durable state and replaceable Providers.
It connects intelligence from models, external agents, algorithms or humans
to governed Work on heterogeneous Nodes and Devices. It records authorization,
execution evidence and independently observed effects so that recovery can
reconcile what happened. A successful response alone does not prove an effect.

[Roadmap and status](ROADMAP.md) · [Architecture](docs/architecture/README.md) ·
[Operations](docs/operations/README.md) · [Developer SDK](docs/development/DEVELOPER_PLATFORM.md) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [简体中文](README.zh-CN.md)

## Architecture

```text
Goal → AgentSession / Plan → durable Workflow
                              ↓
                     Governance / human approval
                              ↓
                Distributed Work → Node → Provider → Device
                              ↓
                    Receipt + Artifact evidence
                              ↓
             independent Observation → EffectVerification → COMMIT
```

Models and placement are never authorities. Credentials are scoped to authorized
execution. UNKNOWN fails closed, and uncertain effects are reconciled rather
than blindly retried. Device identity is independent of its transport address.
The [five canonical architecture contracts](docs/architecture/README.md) explain
these boundaries and distinguish Runtime-service execution from Kernel-managed
NKI workloads. The independently released [APEIR Kernel](https://github.com/untrod/apeir-kernel)
is pinned by [component lock](runtime-components.lock.json).

## Current status

Distribution is `0.1.0-rc1`, for development and evaluation. M3.1–M3.4 software,
M3.5 Control Plane and M3.6 SDK software Gates have passed within their documented
scope. A generic external-agent OCI reference is exercised; other M4 integrations
remain incomplete. Serial/ESP32 host contracts are read-only preparation.
**M3.3-C physical acceptance, M5 physical writes/power-loss and a second hardware
family remain PENDING. M6/M7 are not accepted.** Native locked-binary hash
verification is BLOCKED by missing binaries. See the [exact matrix](ROADMAP.md).

The Operations Console uses backend state for health, Work, Nodes, Devices,
approvals, evidence and recovery, with responsive mobile controls. It does not
grant authority. Real IdP deployment and native/physical qualification are
separate from deterministic Cloud contract tests.

## Source quick start

Python 3.10–3.12 is supported for source development. Desktop development uses
Node.js 22 and Rust stable; Windows native builds additionally require MSVC/SDK
and the exact locked Kernel artifacts.

```bash
git clone https://github.com/untrod/apeir.git
cd apeir
python -m venv .venv
# Activate .venv for your shell
python -m pip install -e ".[dev,a2a,mcp,scientific]"
python -m pytest -q
apeir --help
```

For setup, Controller/Node launch and installation, use the
[operations guides](docs/operations/README.md) and
[Compute Mesh runbook](docs/operations/compute-mesh/OPERATIONS.md).
Production Kernel-managed paths fail closed if Kernel is unavailable. Desktop:

```bash
npm --prefix desktop ci
npm --prefix desktop run lint
npm --prefix desktop test
npm --prefix desktop run typecheck
npm --prefix desktop run build
```

The public brand is APEIR / APEIR Runtime. `nous_runtime`, `nous`, `NOUS_*` and
existing wire identifiers remain internal/compatibility names. Source archives
exclude credentials, generated binaries, local databases and private evidence.

Apache-2.0: [LICENSE](LICENSE), [NOTICE](NOTICE), [third-party notices](THIRD_PARTY_NOTICES.md).

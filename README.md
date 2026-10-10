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
scope. Generic external-agent OCI, OPA policy and OpenBao KV-v2 software references
are exercised within their documented scopes;
other M4 integrations remain incomplete. Serial/ESP32 host contracts are read-only
preparation.
**M3.3-C physical acceptance, M5 physical writes/power-loss and a second hardware
family remain PENDING. M6/M7 are not accepted.** Native locked-binary hash
verification is BLOCKED by missing binaries. See the [exact matrix](ROADMAP.md).

The Operations Console uses backend state for health, Work, Nodes, Devices,
approvals, evidence and recovery, with responsive mobile controls. It does not
grant authority. Real IdP deployment and native/physical qualification are
separate from deterministic Cloud contract tests.

## Developer Preview

Start with the [Verified Execution Demo](examples/hello_runtime/README.md):
a real simulated firmware state change through existing Governance, original
Work, signed Node execution, Receipt, independent Observation and MATCH-only
EffectVerification. No API key or hardware is needed. The failure gallery
exercises Deny, MISMATCH, UNKNOWN, response loss without another mutation, and
persistent restart. Results are Runtime records, not preset success JSON.

The [Provider](examples/hello_provider/README.md) and
[Skill](examples/hello_skill/README.md) examples use the public SDK and existing
Registries. Read-only Work execution and loading Skill instructions have
different scopes; neither grants device permission.
The [scientific reference](docs/architecture/GOVERNED_SCIENTIFIC_RUNTIME.md)
already composes simulation, independent numerical comparison, Claim/Evidence
and DOCX/PDF reporting. Its current Cloud run is BLOCKED by the existing strong
sandbox prerequisite; no substitute host execution or new report is claimed.
The gallery includes a [short video script](examples/hello_runtime/README.md#five-minute-video-script),
reproducible commands, actual result fields and feedback guidance.

This is a source Developer Preview, not a production binary release. Kernel
traversal, native packaging/signatures, real IdP and physical hardware have
separate acceptance gates. Evaluate in dedicated workspaces and share sanitized
reproductions through [issues](https://github.com/untrod/apeir/issues).

## Quick start

Follow the [source Quick Start](docs/operations/getting-started/QUICK_START.md)
for the single recommended installation and first-run path. It needs no API key
or hardware. Distribution and SDK versions have separate compatibility contracts;
this source preview is not a certified binary release.

For Controller/Node launch and deployment, use the
[operations guides](docs/operations/README.md) and
[Compute Mesh runbook](docs/operations/compute-mesh/OPERATIONS.md).
Production Kernel-managed paths fail closed if Kernel is unavailable. Desktop
development uses Node.js 22 and Rust stable; Windows native builds also require
MSVC/SDK and the exact locked Kernel artifacts:

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

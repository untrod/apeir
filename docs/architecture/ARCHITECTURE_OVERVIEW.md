# Nous Architecture Overview

## The Big Picture

```
Applications (CLI, Web, Desktop, Mobile)
        │
        ▼
   Nous Client SDK (Python, JS)
        │
        ▼
   Runtime API (/api/v1/*)
        │
        ▼
┌──────────────────────────┐
│     Nous Runtime Kernel   │
├──────────────────────────┤
│ 01 Runtime Core          │
│ 02 Object Model          │
│ 03 Capability System     │
│ 04 Provider System       │
│ 05 Planner & Execution   │
│ 06 State, Memory & Exp.  │
│ 07 Security & Policy     │
│ 08 Protocol & Federation │
│ 09 Observability         │
└──────────────────────────┘
        │
        ▼
   Providers (Models, Devices, Services)
```

## Key Principles

1. **Runtime Neutrality**: The Runtime contains no domain knowledge
2. **Capability/Provider Separation**: WHAT vs WHO/HOW
3. **Everything Extensible is External**: Packs, not kernel modifications
4. **One Runtime, Multiple Surfaces**: CLI, Web, Desktop, Mobile all use the same API

## Core Concepts

- **Capability**: What can be done (`model.reason`, `device.shell`)
- **Provider**: Who executes it (OpenAI, PC Agent, Robot)
- **Pack**: Distribution unit for capabilities + providers + config
- **Goal**: What the user wants to accomplish
- **Plan**: How to accomplish it (tasks + dependencies)
- **Job**: A scheduled and tracked execution unit
- **Trace**: Complete execution record for observability

## Work Harness

`apeir work` is the product-level entry for goal-directed work. The Harness is
a thin composition layer over existing Runtime owners:

```text
Work request
  -> TaskAnalyzer
  -> Goal + optional versioned Plan
  -> ModelGateway structured decision
  -> AgentExecutionRuntime invocation boundary
  -> existing governed tool/capability runtime
  -> observation + verification
  -> EventStream projection + SQLite checkpoint
```

The Harness is not an authority. Tool availability, model output, plan metadata,
and skill guidance cannot grant permission or bypass Kernel/Runtime admission.
Simple tasks may complete without a Plan. Long-running runs persist Goal, Plan
revision history, observations, artifacts, blockers, and Agent checkpoints in the
workspace and reassess current state before acting after resume.

`ToolCatalog` is the Work-facing discovery projection over existing tool
runtimes. It publishes compact capability categories first and exposes full
schemas only through `catalog_expand`. Invocation is delegated to the original
Workspace or governed Extension/MCP executor; catalog metadata always carries
`authority=none` and cannot make an unavailable or unauthorized action legal.
The first concrete providers expose bounded workspace file discovery, read-only
Git queries when strong sandboxing is available, and the existing workspace
ContentAddressedArtifactStore. Catalog inspection itself does not initialize an
Artifact store or execute a process.

`SkillRegistry` is the corresponding progressive Skill projection. It reads
legacy JSON Skills through the existing Extension adapters, discovers project
and user `SKILL.md` packages, verifies installed packages through
`ExtensionRegistry`, and exposes catalog entries as untrusted summaries. Full
instructions and resource names enter Work context only after `skill_load`.
Installation never executes packaged scripts: the existing Extension supply
chain path validates and copies the package, while a deterministic bundle is
stored and pinned in the existing workspace Artifact Runtime. Declared
capabilities remain requests with `authority=none`.

## For Developers

Start here:
1. `docs/user/guides/USER_GUIDE.md` — User concepts
2. `docs/user/guides/CLI_GUIDE.md` — CLI reference
3. `docs/user/guides/PACK_GUIDE.md` — Create your first pack
4. `docs/user/guides/PROVIDER_GUIDE.md` — Build a provider
5. `docs/architecture/` — Deep architecture contracts

## For Contributors

- `CONTRIBUTING.md` — How to contribute
- `docs/architecture/KERNEL_MODULE_MAP.md` — Codebase navigation
- `docs/architecture/*_CONTRACT.md` — Interface contracts

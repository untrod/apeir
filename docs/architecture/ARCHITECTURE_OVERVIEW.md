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

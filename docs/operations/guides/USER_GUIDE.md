# APEIR Runtime — User Guide

## What is APEIR?

APEIR is an open execution, governance and verification runtime for heterogeneous
intelligence and real-world resources.

The source preview is intended for developers and evaluation. Existing `nous`
commands remain compatibility aliases for `apeir`.

## Installation

Follow the [source Quick Start](../getting-started/QUICK_START.md). It owns the
recommended installation and first inspection; service deployment follows the
[Compute Mesh runbook](../compute-mesh/OPERATIONS.md).

## Your First Interaction

```
❯ analyze my project
❯ check system status
❯ list installed packs
❯ /help
```

## Concepts

- **Runtime**: The engine that runs everything
- **Capability**: Something that can be done (e.g., `model.reason`, `device.shell`)
- **Provider**: The thing that executes a capability (e.g., OpenAI, your PC)
- **Pack**: A bundle of capabilities, providers, and configuration
- **Workspace**: Your local environment

## Common Tasks

| Task | Command |
|------|---------|
| Inspect Runtime | `apeir status` |
| Interactive Shell | `nous` |
| Check Status | `/status` |
| List Packs | `/packs` |
| List Capabilities | `/capabilities` |
| Install Pack | `nous pack install ./my-pack` |
| Remove Pack | `nous pack remove my-pack` |
| Health Check | `nous doctor` |

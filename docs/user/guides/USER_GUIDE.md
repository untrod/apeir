# Nous Runtime — User Guide

## What is Nous?

Nous is an open intelligence runtime. It runs on your machine and connects AI models, devices, tools, and knowledge through standardized capabilities.

**You don't need to be a developer to use Nous.** If you can type in a terminal, you can use Nous.

## Installation (30 seconds)

```bash
pip install nous-runtime
export NOUS_DEMO_MODE=1
nous start
nous
```

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
| Start Runtime | `nous start` |
| Interactive Shell | `nous` |
| Check Status | `/status` |
| List Packs | `/packs` |
| List Capabilities | `/capabilities` |
| Install Pack | `nous pack install ./my-pack` |
| Remove Pack | `nous pack remove my-pack` |
| Health Check | `nous doctor` |

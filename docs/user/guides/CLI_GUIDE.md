# Nous CLI Guide

## Overview

The `nous` command is the primary interface to the Runtime.

## Global Commands

```bash
nous                      # Interactive shell
nous init [path]          # Initialize workspace
nous start                # Start Runtime daemon
nous status               # Runtime health + stats
nous health               # Provider health aggregation
nous doctor               # Security diagnostics
nous version              # Show version
```

## Capability

```bash
nous capability list                  # All capabilities
nous capability run <id>              # Execute a capability
nous capability run model.reason --params '{"prompt":"Hello"}'
```

## Provider

```bash
nous provider list                    # All providers
nous provider health                  # Health aggregation
```

## Pack

```bash
nous pack install <path>              # Install from directory
nous pack list                        # List installed
nous pack remove <name>               # Remove a pack
```

## Execution

```bash
nous run <capability>                 # Run capability
nous trace [--limit N] [--session-id] # Execution traces
```

## Developer

```bash
nous dev new pack <name>              # Scaffold new pack
nous dev validate [path]              # Validate pack.yaml
nous dev test [path]                  # Run pack tests
```

## Interactive Shell Slash Commands

```
/help           Show all commands
/status         Runtime health
/providers      List providers
/capabilities   List capabilities
/packs          List installed packs
/jobs           Recent jobs
/trace [N]      Execution traces
/workspace      Workspace info
/clear          Clear screen
/quit           Exit shell
```

## Shell Tips

- Type natural language — the Runtime plans and executes
- Use `/` commands for structured queries
- Tab completion planned for v1.2
- History is preserved within a session

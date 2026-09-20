# Nous CLI Reference

## Global Commands

```bash
nous --help              # Show help
nous version             # Show version
nous init [path]         # Initialize workspace
nous status              # Runtime status
nous start               # Start runtime
nous health              # Provider health
nous doctor              # Security diagnostics
```

## Capability

```bash
nous capability list                # List all capabilities
nous capability run <id> [--params] # Execute a capability
```

## Provider

```bash
nous provider list        # List registered providers
```

## Pack

```bash
nous pack install <path>  # Install from directory
nous pack list            # List installed packs
nous pack remove <name>   # Remove a pack
```

## Execution

```bash
nous run <capability> [--params '{"key":"value"}']  # Run capability
nous trace [--session-id] [--limit]                  # Execution traces
```

## Developer

```bash
nous dev new pack <name>  # Scaffold new pack
nous dev validate [path]  # Validate pack.yaml
nous dev test [path]      # Run pack tests
```

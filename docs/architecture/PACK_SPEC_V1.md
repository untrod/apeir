# Pack Specification v1.0

## Definition

A Pack is the distribution unit for the Nous ecosystem. It bundles capabilities, providers, resource types, workflows, policies, and documentation into a single installable artifact.

## Pack Structure

```
my-pack/
├── pack.yaml          # Required: manifest
├── src/               # Python module (optional)
│   ├── __init__.py    # register() called on install
│   ├── capabilities.py
│   └── providers.py
├── tests/             # Pack tests (optional)
└── README.md          # Documentation (recommended)
```

## Manifest (pack.yaml)

```yaml
name: my_pack                    # snake_case, unique
version: 1.0.0                   # Semver
description: "..."               # One-line description
author: "..."                    # Optional
license: "Apache-2.0"            # Optional

capabilities:                    # Capability IDs this pack provides
  - example.hello
  - example.echo

providers:                       # Provider class names to register
  - MyProvider

dependencies:                    # Required packs + version constraints
  runtime: ">=1.0"

config:                          # Default configuration
  greeting: "Hello World"
  max_retries: 3
```

## Lifecycle

```
INSTALL       <- Validate manifest, check deps, load module, register
  ↓
VALIDATE      <- Verify all capabilities resolve, providers are healthy
  ↓
ENABLE        <- Activate for use
  ↓
READY         <- Available
  ↓
DISABLE       <- Deactivate without removing data
  ↓
REMOVE        <- Unregister capabilities, delete (prompt for data retention)
```

## CLI Commands

```bash
nous pack install ./my-pack       # Install from directory
nous pack list                    # List installed packs
nous pack inspect my_pack         # Show manifest + status
nous pack enable my_pack          # Enable
nous pack disable my_pack         # Disable
nous pack remove my_pack          # Remove
nous pack update my_pack          # Update to latest version
```

## Pack Development

```bash
nous dev new pack my-pack         # Scaffold new pack from template
nous dev validate                 # Validate pack.yaml
nous dev test                     # Run pack tests
nous dev pack                     # Build distributable archive
```

## Rules

1. A Pack must have a valid pack.yaml
2. A Pack must declare its capabilities and providers
3. A Pack must not modify Runtime kernel code
4. A Pack must not access another Pack's internal state
5. A Pack's dependencies are checked on install
6. Removing a Pack removes its capabilities (data retention is user's choice)
7. Packs can register slash commands (e.g., `/git:commit`) in namespaced form
8. Packs must not pollute the Runtime core command namespace
9. The Runtime never ships with pre-installed Packs
10. All domain knowledge belongs in Packs, not the Runtime

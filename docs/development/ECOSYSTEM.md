# Nous Developer Ecosystem v1.0

## Getting Started

```bash
# 1. Install
pip install nous-runtime[all]

# 2. Verify
nous version
nous doctor

# 3. Create your first pack
nous dev new pack hello
cd hello
nous dev validate
nous pack install .
nous capability run hello.hello

# Total time: under 5 minutes
```

## Pack Registry (Concept)

The Pack Registry is where packs are published and discovered.

```
nous pack search study        # Search for packs
nous pack install study_pack  # Install by name
nous pack publish             # Publish your pack
```

For v1.0.0, packs are installed from local directories. Registry support planned for v1.1.

## Pack Templates

| Template | Command | Description |
|----------|---------|-------------|
| `pack` | `nous dev new pack` | Basic pack with one capability |
| *(more in v1.1)* | | |

## Development Workflow

```
1. nous dev new pack <name>     # Scaffold
2. Edit src/providers.py        # Add logic
3. nous dev validate            # Check manifest
4. nous dev test                # Run tests
5. nous pack install .          # Install locally
6. nous capability run <id>     # Test capability
7. git commit && git push       # Share
```

## Community

- Architecture: `docs/architecture/`
- Contracts: `docs/architecture/*_CONTRACT.md`
- Developer guides: `docs/development/`
- Example packs: `packs/examples/`

## Contributing

See `CONTRIBUTING.md` for:
- Provider development
- Capability registration
- Pack creation
- Documentation
- Testing

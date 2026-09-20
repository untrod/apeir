# Compatibility Policy v1.0

## Versioning

Nous Runtime follows Semantic Versioning (SemVer): `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking API changes
- **MINOR**: New features, backward-compatible
- **PATCH**: Bug fixes, backward-compatible

## API Stability

### Stable APIs (no breaking changes in MINOR/PATCH)
- Capability Contract
- Provider Contract
- Execution Contract
- Pack Manifest schema
- CLI command interface
- HTTP API endpoints (once marked stable)
- Object Model metadata fields

### Evolving APIs (may change in MINOR)
- Internal module structure (refactoring)
- Log message formats
- Dashboard UI layout
- Configuration key names (with deprecation notice)

### Unstable (may change anytime)
- `remote_terminal/brain.py` internals (undergoing extraction)
- `tools.py` internal dispatch (undergoing migration to Capability)
- `learn_db.py` domain-specific tables (being moved to Packs)

## Deprecation Process

1. **Announce**: Mark as deprecated in CHANGELOG
2. **Warn**: Emit deprecation warning for one MINOR version
3. **Remove**: Remove in next MAJOR version

## Migration Support

- Database schema changes: provide migration scripts
- API changes: provide migration guide
- Config changes: support old keys with deprecation warning for one MINOR version

## What v1.0.0 Freezes

After v1.0.0:
- The 9 kernel subsystem boundaries are STABLE
- The Capability Contract is STABLE
- The Provider Contract is STABLE
- The Pack Manifest schema is STABLE
- The Object Model is STABLE
- The Error Model error codes are STABLE (additive only)

## What v1.0.0 Does NOT Freeze

- Internal implementation of brain.py (being extracted)
- Learning engine domain split (ongoing)
- NFP/NSP protocols (still draft)
- Desktop app pages (evolving)
- Android app (evolving)

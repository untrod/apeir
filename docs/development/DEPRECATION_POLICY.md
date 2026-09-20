# Deprecation Policy v1.0

## Policy

1. **Announce**: Feature marked deprecated in CHANGELOG with migration path
2. **Warn**: Deprecation warning emitted for one full MINOR version
3. **Remove**: Feature removed in next MAJOR version

## Currently Deprecated (v1.0)

None — this is the first stable release.

## Planned Deprecations (v1.x)

| Feature | Reason | Target Removal |
|---------|--------|:-------------:|
| `learn_db.py` domain tables | Moving to Study Pack | v2.0 |
| `brain.py` bare `_register_provider()` | Replaced by Provider adapters | v2.0 |
| `devices.json` (legacy) | Replaced by SQLite registry | v2.0 |
| `sessions.json` (legacy) | Migrate to SQLite | v2.0 |

## Migration Support

- Schema changes: provide migration script
- API changes: provide before/after examples
- Config changes: support old keys with warning for one version

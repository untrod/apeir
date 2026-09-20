# Nous Kernel Versioning Policy

> RC4 Kernel Closure
> Date: 2026-08-04

## Versioning Scheme

Nous Kernel uses a three-component versioning scheme:

```
MAJOR.MINOR.PATCH
```

- **MAJOR**: Breaking changes to any stable ABI (NKI, Engine ABI, Device ABI, Workload IR)
- **MINOR**: Backward-compatible additions (new methods, new fields with defaults)
- **PATCH**: Bug fixes, performance improvements, security patches

## Current API Versions

| API | Version | Stability | Since |
|-----|---------|-----------|-------|
| NKI | v1alpha | Experimental — breaking changes allowed with notice | RC4 |
| Engine ABI | v1alpha | Experimental — breaking changes allowed with notice | RC4 |
| Device ABI | v1alpha | Experimental — breaking changes allowed with notice | RC4 |
| Workload IR | v1alpha | Experimental — breaking changes allowed with notice | RC4 |
| Model Package | v1alpha | Experimental — breaking changes allowed with notice | RC4 |

## Compatibility Window

During the `alpha` phase:

1. Breaking changes allowed between release candidates (RC4→RC5)
2. Each breaking change documented in MIGRATION_GUIDE
3. At least one RC version overlap where both old and new are supported
4. `NOT_SUPPORTED` returned for removed methods (not silent failure)

When APIs reach `v1` (stable):

1. Breaking changes require MAJOR version bump
2. Old API versions supported for at least 2 MAJOR versions
3. Deprecation warnings issued at least 1 MAJOR version before removal
4. Migration path documented and tested

## Schema Versioning

WorkloadSpec.schema_version is validated on admission:
- Unknown versions: rejected with SCHEMA_INCOMPATIBLE
- Known versions: validated against that version's schema
- Default fields: added with backward-compatible defaults
- Removed fields: ignored (forward compatibility)

## What Requires a Breaking Change Notice

1. Changing NKI method names or signatures
2. Removing NKI methods
3. Changing WorkloadSpec required fields
4. Changing WorkloadPhase valid transitions
5. Changing ResourceLease semantics
6. Changing error code meanings
7. Changing NKI transport protocol
8. Changing checksum algorithm
9. Changing idempotency key format
10. Changing base serialization format (currently base64 JSON)

## What Does NOT Require Notice

1. Adding new NKI methods
2. Adding new optional fields to WorkloadSpec (with defaults)
3. Adding new WorkloadPhase states (if existing transitions unchanged)
4. Adding new error codes
5. Internal refactoring behind NKI boundary
6. Performance improvements
7. Adding new adapters
8. Adding new scheduler policies
9. Adding new integrity checks
10. Documentation improvements

## Current Breaking Changes Under Consideration (RC4→RC5)

| Change | Impact | Status |
|--------|--------|--------|
| NKIOutcome: untagged→tagged enum | All NKI clients need update | Pending approval |
| Python kernel.TaskPhase deprecation | Python product code needs migration | Planned RC5 |
| Legacy RuntimeRequest deprecation | CLI/API consumers need update | Planned RC5 |

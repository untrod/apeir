# Profile Store Spec

Nous is an Open Intelligence Runtime.

## Protocol

`ProfileStore` defines the persistence contract:

- `save_model_profile(profile) -> bool`
- `save_provider_profile(profile) -> bool`
- `append_capability_observation(obs) -> bool`
- `append_performance_observation(obs) -> bool`
- `append_probe_result(result) -> bool`
- `get_model_profile(model_id) -> ModelProfile | None`
- `list_model_profiles() -> list[ModelProfile]`
- `get_provider_profile(provider_id) -> ProviderProfile | None`
- `list_provider_profiles() -> list[ProviderProfile]`
- `find_stale_profiles() -> list`
- `verify_integrity() -> dict`
- `rebuild_indexes() -> dict`

## Implementations

### InMemoryProfileStore
Simple dict-based store for testing and single-process use.

### JsonlProfileStore
JSONL-based persistent store at `.nous/intelligence/profiles/`.

Properties:
- Idempotent append — duplicate detection by key field
- Truncated-line recovery — malformed lines counted in integrity check
- Schema migration hooks — schema_version on each record
- Secret redaction — `_sanitize()` on all values
- Deterministic snapshots — `ProfileSnapshot` records
- File locking via `fcntl`/`msvcrt` for `file_lock` mode

## Safety

- Local filesystem only
- Same-host concurrency only
- No network filesystem claims (NFS, SMB rejected)
- No multi-host writer claims

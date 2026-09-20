# Provider Profile Spec

Nous is an Open Intelligence Runtime.

## Overview

`ProviderProfile` captures provider identity, locality, privacy, health, and aggregate performance. It complements `ModelProfile` for provider-level scheduling decisions.

## Schema

- `provider_id: str` — unique identifier
- `schema_version: str`
- `runtime_version: str`
- `display_name: str`
- `provider_type: str` — "cloud", "local", "edge", "hybrid"
- `models: tuple[str, ...]` — associated model_ids
- `locality: ProfileValue` — geographic/political region
- `privacy_level: ProfileValue` — "local", "regional", "cloud"
- `data_residency: ProfileValue` — data handling jurisdiction
- `availability: ProfileValue` — availability status
- `health_status: str` — "ok", "degraded", "down", "unknown"
- `performance: PerformanceAggregate` — aggregate metrics
- `last_health_check: datetime | None`
- `discovered_at: datetime | None`
- `updated_at: datetime`
- `profile_hash: str`
- `discovery_source: str`
- `metadata: dict[str, Any]` — extensible (secrets redacted)

## Profile Storage

JSONL-based storage at `.nous/intelligence/profiles/`:

- `models.jsonl` — ModelProfile records
- `providers.jsonl` — ProviderProfile records
- `capability_observations.jsonl` — CapabilityObservation records
- `performance_observations.jsonl` — PerformanceObservation records
- `probes.jsonl` — ProbeResult records
- `snapshots.jsonl` — ProfileSnapshot records
- `discovery.jsonl` — DiscoveryRecord records
- `manifests/store.json` — store manifest

## Concurrency

Supported: `single_process`, `file_lock` (local filesystem only).
Explicitly unsupported: NFS, SMB, multi-host, distributed filesystems.

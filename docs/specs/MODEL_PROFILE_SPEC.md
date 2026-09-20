# Model Profile Spec

Nous is an Open Intelligence Runtime.

## Overview

`ModelProfile` is the canonical representation of a model's capabilities, performance, pricing, and lifecycle state. It replaces the ad-hoc `metadata` dict bag that previously flowed into the scheduler.

## Schema

- `model_id: str` — unique identifier
- `schema_version: str` — PROFILE_SCHEMA_VERSION ("1.0")
- `runtime_version: str` — nous_runtime version
- `display_name: str` — human-readable name
- `provider_family: str` — provider family name
- `lifecycle: ModelLifecycle` — one of: unknown, discovered, provisional, probing, verified, degraded, quarantined, retired
- `context_window: ProfileValue` — context window size in tokens
- `max_output_tokens: ProfileValue` — max output tokens
- `input_modalities: tuple[str, ...]` — e.g., ["text", "image"]
- `output_modalities: tuple[str, ...]` — e.g., ["text"]
- `supports_streaming: ProfileValue` — streaming support
- `supports_tool_calling: ProfileValue` — tool calling support
- `supports_structured_output: ProfileValue` — structured output support
- `supports_embedding: ProfileValue` — embedding support
- `capability_claims: tuple[CapabilityClaim, ...]` — declared/verified capabilities
- `pricing: PricingProfile` — cost information
- `rate_limits: RateLimitProfile` — rate limit information
- `performance: PerformanceAggregate` — aggregated metrics
- `quality_estimate: ProfileValue` — estimated quality
- `discovered_at: datetime | None` — discovery timestamp
- `updated_at: datetime` — last update timestamp
- `profile_hash: str` — deterministic content hash
- `discovery_source: str` — source of discovery
- `metadata: dict[str, Any]` — extensible metadata (secrets redacted)

## ProfileValue

Every structured property uses `ProfileValue`:

- `value: Any` — the actual value
- `unit: str` — unit (e.g., "tokens", "ms")
- `provenance: ValueProvenance` — declared, discovered, observed, probed, verified, inferred, unknown, stale
- `confidence: float` — 0.0–1.0
- `observed_at: datetime | None` — when observed
- `expires_at: datetime | None` — when it becomes stale
- `evidence_refs: tuple[str, ...]` — references to evidence
- `stale: bool` — whether currently stale

## Lifecycle

Models progress through lifecycle states:
- **unknown** -> discovered -> **provisional** -> probing -> **verified** -> (degraded -> quarantined -> retired)

Key invariants:
- Declared capability ≠ verified capability
- Absence of failures ≠ proven reliability
- Provisional models have conservative confidence
- Quarantined/retired models are excluded from scheduling

## Hashing

Profile hashes are deterministic based on: model_id, schema_version, lifecycle, context_window, capability_claims. Timestamps are excluded to ensure stability across instances with identical content.

## Security

- API keys, tokens, and secrets in metadata are redacted on `to_dict()`
- Endpoints in DiscoveryRecord are redacted
- Provider responses are treated as untrusted input
- Capability claims cannot grant Runtime permissions

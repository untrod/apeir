"""Model discovery adapters.

Discovery is explicit and bounded. No arbitrary network scanning, no automatic
model download, no automatic model execution. Duplicate discovery is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Protocol

from nous_runtime.intelligence.profiles.models import (
    CapabilityClaim,
    CapabilityState,
    DiscoveryRecord,
    ModelLifecycle,
    ModelProfile,
    ProfileValue,
    ProviderProfile,
    ValueProvenance,
)


class DiscoveryAdapter(Protocol):
    """Protocol for model/provider discovery adapters."""

    @property
    def source_name(self) -> str: ...

    def discover(self) -> list[DiscoveryRecord]: ...


# static configuration adapter

class StaticConfigDiscovery:
    """Discover models from static configuration (env vars, config files)."""

    source_name = "static_config"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def discover(self) -> list[DiscoveryRecord]:
        records: list[DiscoveryRecord] = []

        # Discover from environment
        model_env = os.environ.get("NOUS_LLM_MODEL", "")
        if model_env:
            records.append(DiscoveryRecord(
                discovery_id=_disc_id("static", model_env),
                source="static_config",
                model_id=model_env,
                provider_id=os.environ.get("NOUS_LLM_PROVIDER", "unknown"),
                discovered_at=datetime.now(timezone.utc),
                raw_metadata={"env_var": "NOUS_LLM_MODEL"},
            ))

        # Discover from config dict
        for entry in self._config.get("models", []):
            if isinstance(entry, dict) and entry.get("model_id"):
                records.append(DiscoveryRecord(
                    discovery_id=_disc_id("static", str(entry["model_id"])),
                    source="static_config",
                    model_id=str(entry["model_id"]),
                    provider_id=str(entry.get("provider_id", "")),
                    discovered_at=datetime.now(timezone.utc),
                    raw_metadata=dict(entry),
                ))

        return records


# provider registry adapter

class ProviderRegistryDiscovery:
    """Discover models from the existing provider registry."""

    source_name = "provider_registry"

    def discover(self) -> list[DiscoveryRecord]:
        records: list[DiscoveryRecord] = []
        try:
            from nous_runtime.provider.registry import registry
            providers = registry.list_all()
            for p in providers:
                pid = str(p.get("id") or p.get("name") or "")
                if not pid:
                    continue
                records.append(DiscoveryRecord(
                    discovery_id=_disc_id("registry", pid),
                    source="provider_registry",
                    provider_id=pid,
                    discovered_at=datetime.now(timezone.utc),
                    raw_metadata={"capabilities": p.get("capabilities", []), "health": p.get("health", {})},
                ))
        except Exception:
            pass
        return records


# local model manifest adapter

class LocalManifestDiscovery:
    """Discover models from a local manifest file."""

    source_name = "local_manifest"

    def __init__(self, manifest_path: str = "") -> None:
        self._manifest_path = manifest_path

    def discover(self) -> list[DiscoveryRecord]:
        records: list[DiscoveryRecord] = []
        if not self._manifest_path:
            return records
        try:
            with open(self._manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return records

        for entry in data.get("models", []) if isinstance(data, dict) else data:
            if isinstance(entry, dict) and entry.get("model_id"):
                records.append(DiscoveryRecord(
                    discovery_id=_disc_id("manifest", str(entry["model_id"])),
                    source="local_manifest",
                    model_id=str(entry["model_id"]),
                    provider_id=str(entry.get("provider_id", "")),
                    discovered_at=datetime.now(timezone.utc),
                    raw_metadata=dict(entry),
                ))
        return records


# discovery orchestrator

class ModelDiscoveryOrchestrator:
    """Coordinates discovery across multiple adapters. Idempotent — duplicate
    discoveries produce the same discovery_id and are safely ignorable."""

    def __init__(self, adapters: list[DiscoveryAdapter] | None = None) -> None:
        self._adapters = adapters or [
            StaticConfigDiscovery(),
            ProviderRegistryDiscovery(),
        ]

    def add_adapter(self, adapter: DiscoveryAdapter) -> None:
        self._adapters.append(adapter)

    def discover_all(self) -> list[DiscoveryRecord]:
        all_records: list[DiscoveryRecord] = []
        seen: set[str] = set()
        for adapter in self._adapters:
            try:
                for record in adapter.discover():
                    if record.discovery_id not in seen:
                        seen.add(record.discovery_id)
                        all_records.append(record)
            except Exception:
                # Discovery failures are recorded diagnostically, not fatal
                all_records.append(DiscoveryRecord(
                    discovery_id=_disc_id("error", adapter.source_name, str(hash(str(all_records)))),
                    source=adapter.source_name,
                    error=f"Discovery adapter {adapter.source_name} raised an exception.",
                    discovered_at=datetime.now(timezone.utc),
                ))
        return all_records


# provisional profile builder

def build_provisional_profile(record: DiscoveryRecord) -> ModelProfile:
    """Create a provisional ModelProfile from a discovery record.

    Provisional profiles have:
    - lifecycle = PROVISIONAL (or DISCOVERED if no model_id)
    - conservative confidence
    - unverified capability claims
    - unknown = explicit
    """
    lifecycle = ModelLifecycle.DISCOVERED if record.model_id else ModelLifecycle.PROVISIONAL
    raw = record.raw_metadata

    # Extract known fields from raw metadata
    caps_raw = raw.get("capabilities") or raw.get("capability_claims") or []
    claims = tuple(
        CapabilityClaim(
            capability_id=str(c),
            state=CapabilityState.DECLARED,
            provenance=ValueProvenance.DISCOVERED,
            confidence=0.3,  # conservative — not verified
        )
        for c in caps_raw
    )

    return ModelProfile(
        model_id=record.model_id or f"provisional_{record.discovery_id[:8]}",
        display_name=record.model_id or "Unknown Model",
        provider_family=record.provider_id,
        lifecycle=lifecycle,
        context_window=ProfileValue(
            raw.get("context_window"),
            unit="tokens",
            provenance=ValueProvenance.DISCOVERED,
            confidence=0.3 if raw.get("context_window") else 0.0,
        ),
        supports_tool_calling=ProfileValue(
            raw.get("tool_calling") or raw.get("supports_tool_calling"),
            provenance=ValueProvenance.DISCOVERED,
            confidence=0.3,
        ),
        supports_structured_output=ProfileValue(
            raw.get("structured_output") or raw.get("supports_structured_output"),
            provenance=ValueProvenance.DISCOVERED,
            confidence=0.3,
        ),
        capability_claims=claims,
        discovered_at=record.discovered_at,
        discovery_source=record.source,
        metadata={"discovery_id": record.discovery_id, "is_provisional": True},
    )


def build_provisional_provider_profile(record: DiscoveryRecord) -> ProviderProfile:
    """Create a provisional ProviderProfile from a discovery record."""
    return ProviderProfile(
        provider_id=record.provider_id or f"provisional_provider_{record.discovery_id[:8]}",
        display_name=record.provider_id or "Unknown Provider",
        health_status="unknown",
        availability=ProfileValue("unknown", provenance=ValueProvenance.DISCOVERED, confidence=0.3),
        discovered_at=record.discovered_at,
        discovery_source=record.source,
        metadata={"discovery_id": record.discovery_id, "is_provisional": True},
    )


# helpers

def _disc_id(*parts: str) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

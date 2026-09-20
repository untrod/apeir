# -*- coding: utf-8 -*-
"""Capability Manifest helpers.

The manifest is the open, stable contract for a capability. It is derived
from the runtime capability registry and can be exported for docs, packs,
devices, and runtime inspection without exposing local configuration.
"""

from __future__ import annotations

import json as _json
import re as _re
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.schema_registry import CAPABILITY_SCHEMA_VERSION as SCHEMA_VERSION

RISK_LEVELS = {"low", "medium", "high", "critical"}
CATEGORIES = frozenset(
    {"model", "rag", "device", "notification", "tool", "automation", "software", "agent", "connector"}
)
# executor_type is an open extension point (packs may declare e.g. "stm32_programmer");
# it is enforced at the dispatch layer, not in validate().
EXECUTOR_TYPES = frozenset({"provider", "connector", "subprocess", "node", "runtime"})
SIDE_EFFECT_CLASSES = frozenset({"read_only", "local_write", "external_write", "destructive"})
REVERSIBILITY_VALUES = frozenset({"reversible", "partially_reversible", "irreversible"})
LOCALITY_VALUES = frozenset({"local", "remote", "embedded"})
CONNECTION_TYPES = frozenset({"none", "ip", "usb", "wifi", "ble", "serial", "can"})
_REVERSIBILITY_ALIASES = {
    "partial": "partially_reversible",
    "partially": "partially_reversible",
    "full": "reversible",
    "none": "irreversible",
}
_CAPABILITY_ID_RE = _re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


@dataclass
class CapabilityManifest:
    """Stable capability contract exported by the Runtime.

    Universal capability fields (v0.2.0):
        executor_type: "provider" | "connector" | "subprocess" | "node" | "runtime"
        side_effect_class: declared side-effect (replaces prefix inference)
        reversibility: declared reversibility (replaces prefix inference)
        model_uncertainty: 0.0–1.0 inherent output uncertainty
        idempotent: safe to retry without side-effects
        privileged: requires elevated authorization
        locality: "local" | "remote" | "embedded"
        connection_type: "ip" | "usb" | "wifi" | "ble" | "serial" | "can"
        resource_requirements: {cpu, gpu, memory_mb, ...}
    """

    capability_id: str
    category: str = ""
    description: str = ""
    provider: str = ""
    risk_level: str = "low"
    version: str = "1.0.0"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30000
    max_retries: int = 1
    requires_approval: bool = False
    requires_auth: bool = False
    requires_device: bool = False
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    availability: str = "unknown"
    unavailable_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # v0.2.0: Universal capability fields
    executor_type: str = ""
    side_effect_class: str = ""
    reversibility: str = ""
    model_uncertainty: float = 0.0
    idempotent: bool = False
    privileged: bool = False
    locality: str = ""
    connection_type: str = ""
    resource_requirements: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_capability(cls, cap: dict[str, Any], availability: dict[str, str] | None = None) -> "CapabilityManifest":
        """Build a manifest from a capability registry row."""
        metadata = _coerce_dict(cap.get("metadata", {}))
        risk = str(cap.get("risk_level", cap.get("risk", "low")) or "low")
        availability = availability or {}
        tags = metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list):
            tags = []

        return cls(
            capability_id=str(cap.get("capability_id", cap.get("name", ""))),
            category=str(cap.get("category", "")),
            description=str(cap.get("description", "")),
            provider=str(cap.get("provider", "")),
            risk_level=risk,
            version=str(metadata.get("version", "1.0.0")),
            input_schema=_coerce_schema(metadata.get("input_schema")),
            output_schema=_coerce_schema(metadata.get("output_schema")),
            timeout_ms=int(cap.get("timeout_ms", metadata.get("timeout_ms", 30000)) or 30000),
            max_retries=int(cap.get("max_retries", metadata.get("max_retries", 1)) or 1),
            requires_approval=bool(metadata.get("requires_approval", risk in {"high", "critical"})),
            requires_auth=bool(cap.get("requires_auth", metadata.get("requires_auth", False))),
            requires_device=bool(cap.get("requires_device", metadata.get("requires_device", False))),
            depends_on=_coerce_list(cap.get("depends_on", metadata.get("depends_on", []))),
            tags=[str(t) for t in tags],
            availability=availability.get("status", "unknown"),
            unavailable_reason=availability.get("reason", ""),
            metadata=_public_metadata(metadata),
            # v0.2.0: Universal capability fields — top-level row keys win
            # (external JSON manifests), then metadata (registry storage)
            executor_type=str(_first_of(cap, metadata, "executor_type", "")),
            side_effect_class=str(_first_of(cap, metadata, "side_effect_class", "")),
            reversibility=_normalize_reversibility(_first_of(cap, metadata, "reversibility", "")),
            model_uncertainty=float(_first_of(cap, metadata, "model_uncertainty", 0.0)),
            idempotent=bool(_first_of(cap, metadata, "idempotent", False)),
            privileged=bool(_first_of(cap, metadata, "privileged", False)),
            locality=str(_first_of(cap, metadata, "locality", "")),
            connection_type=str(_first_of(cap, metadata, "connection_type", "")),
            resource_requirements=_coerce_resources(_first_of(cap, metadata, "resource_requirements", {})),
        )

    def validate(self) -> list[str]:
        """Return validation errors for this manifest."""
        errors: list[str] = []
        if not _CAPABILITY_ID_RE.match(self.capability_id):
            errors.append(f"invalid capability_id: {self.capability_id}")
        if self.risk_level not in RISK_LEVELS:
            errors.append(f"invalid risk_level: {self.risk_level}")
        if self.timeout_ms <= 0 or self.timeout_ms > 600000:
            errors.append("timeout_ms must be > 0 and <= 600000")
        if not isinstance(self.input_schema, dict):
            errors.append("input_schema must be an object")
        if not isinstance(self.output_schema, dict):
            errors.append("output_schema must be an object")
        for dep in self.depends_on:
            if not _CAPABILITY_ID_RE.match(dep):
                errors.append(f"invalid depends_on capability_id: {dep}")
        # v0.2.0: universal field validation (only when declared)
        if self.category and self.category not in CATEGORIES:
            errors.append(f"invalid category: {self.category}")
        if self.side_effect_class and self.side_effect_class not in SIDE_EFFECT_CLASSES:
            errors.append(f"invalid side_effect_class: {self.side_effect_class}")
        if self.reversibility and self.reversibility not in REVERSIBILITY_VALUES:
            errors.append(f"invalid reversibility: {self.reversibility}")
        if self.locality and self.locality not in LOCALITY_VALUES:
            errors.append(f"invalid locality: {self.locality}")
        if self.connection_type and self.connection_type not in CONNECTION_TYPES:
            errors.append(f"invalid connection_type: {self.connection_type}")
        if not 0.0 <= self.model_uncertainty <= 1.0:
            errors.append("model_uncertainty must be within [0.0, 1.0]")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "capability_id": self.capability_id,
            "version": self.version,
            "category": self.category,
            "description": self.description,
            "provider": self.provider,
            "risk_level": self.risk_level,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "timeout_ms": self.timeout_ms,
            "max_retries": self.max_retries,
            "requires_approval": self.requires_approval,
            "requires_auth": self.requires_auth,
            "requires_device": self.requires_device,
            "depends_on": self.depends_on,
            "tags": self.tags,
            "availability": self.availability,
            "unavailable_reason": self.unavailable_reason,
            "metadata": self.metadata,
            # v0.2.0 universal fields
            "executor_type": self.executor_type,
            "side_effect_class": self.side_effect_class,
            "reversibility": self.reversibility,
            "model_uncertainty": self.model_uncertainty,
            "idempotent": self.idempotent,
            "privileged": self.privileged,
            "locality": self.locality,
            "connection_type": self.connection_type,
            "resource_requirements": self.resource_requirements,
        }


def get_capability_manifest(capability_id: str, include_availability: bool = True) -> CapabilityManifest | None:
    """Return a manifest for one registered capability."""
    from nous_runtime.compat.capability import get_capability

    cap = get_capability(capability_id)
    if not cap:
        return None
    availability = _availability_map().get(capability_id, {}) if include_availability else {}
    return CapabilityManifest.from_capability(cap, availability=availability)


def export_capability_manifests(include_availability: bool = True) -> list[CapabilityManifest]:
    """Export all registered capabilities as manifests."""
    from nous_runtime.compat.capability import list_capabilities

    availability = _availability_map() if include_availability else {}
    manifests: list[CapabilityManifest] = []
    for cap in list_capabilities():
        if isinstance(cap, dict):
            manifest = CapabilityManifest.from_capability(
                cap,
                availability=availability.get(str(cap.get("name", "")), {}),
            )
            manifests.append(manifest)
    manifests.sort(key=lambda m: (m.category, m.capability_id))
    return manifests


def validate_capability_manifests(manifests: list[CapabilityManifest] | None = None) -> dict[str, list[str]]:
    """Validate manifests and return errors keyed by capability ID."""
    manifests = manifests if manifests is not None else export_capability_manifests()
    errors: dict[str, list[str]] = {}
    for manifest in manifests:
        manifest_errors = manifest.validate()
        if manifest_errors:
            errors[manifest.capability_id] = manifest_errors
    return errors


def _availability_map() -> dict[str, dict[str, str]]:
    try:
        from nous_runtime.capability.availability import check_availability

        result = check_availability()
    except Exception:
        return {}

    mapped: dict[str, dict[str, str]] = {}
    for cap in result.get("available", []):
        mapped[cap.get("name", "")] = {"status": "available"}
    for cap in result.get("unavailable", []):
        mapped[cap.get("name", "")] = {
            "status": "unavailable",
            "reason": cap.get("reason", ""),
        }
    return mapped


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = _json.loads(value)
        except _json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _first_of(cap: dict[str, Any], metadata: dict[str, Any], key: str, default: Any = None) -> Any:
    """Return the first declared value for a universal field.

    Top-level row keys win (external JSON manifests), then metadata
    (register_capability storage).  Guards preserve legitimate falsy
    values such as 0.0 and False.
    """
    for source in (cap, metadata):
        value = source.get(key)
        if value is not None and value != "":
            return value
    return default


def _normalize_reversibility(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _REVERSIBILITY_ALIASES.get(text, text)


def _coerce_resources(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {str(item): True for item in value}
    return _coerce_dict(value)


def _coerce_schema(value: Any) -> dict[str, Any]:
    schema = _coerce_dict(value)
    return schema or {"type": "object", "properties": {}}


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = _json.loads(value)
        except _json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    return []


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked_parts = ("api_key", "apikey", "token", "secret", "password", "private_key", "endpoint")
    return {
        str(k): v
        for k, v in metadata.items()
        if not any(part in str(k).lower().replace("-", "_") for part in blocked_parts)
        and k not in {"input_schema", "output_schema", "depends_on", "tags"}
    }


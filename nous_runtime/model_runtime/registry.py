"""Persistent registry for model descriptors and live instances."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.model_runtime.errors import ModelRegistryError
from nous_runtime.model_runtime.models import (
    CapabilityLevel,
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelLifecycleState,
    ModelModality,
    PrivacyClass,
    utc_now,
)


_ALLOWED_TRANSITIONS = {
    ModelLifecycleState.DISCOVERED: {
        ModelLifecycleState.DOWNLOADING,
        ModelLifecycleState.INSTALLED,
        ModelLifecycleState.REGISTERED,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.DOWNLOADING: {
        ModelLifecycleState.PARTIAL,
        ModelLifecycleState.INSTALLED,
        ModelLifecycleState.BROKEN,
    },
    ModelLifecycleState.PARTIAL: {
        ModelLifecycleState.DOWNLOADING,
        ModelLifecycleState.INSTALLED,
        ModelLifecycleState.BROKEN,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.INSTALLED: {
        ModelLifecycleState.REGISTERED,
        ModelLifecycleState.BROKEN,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.REGISTERED: {
        ModelLifecycleState.ENABLED,
        ModelLifecycleState.DISABLED,
        ModelLifecycleState.BROKEN,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.ENABLED: {
        ModelLifecycleState.DISABLED,
        ModelLifecycleState.BROKEN,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.DISABLED: {
        ModelLifecycleState.ENABLED,
        ModelLifecycleState.BROKEN,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.BROKEN: {
        ModelLifecycleState.REGISTERED,
        ModelLifecycleState.DISABLED,
        ModelLifecycleState.REMOVED,
    },
    ModelLifecycleState.REMOVED: set(),
}


@dataclass(frozen=True)
class ModelRecord:
    descriptor: ModelDescriptor
    state: ModelLifecycleState = ModelLifecycleState.REGISTERED
    source: str = ""
    location: str = ""
    endpoint: str = ""
    enabled_roles: tuple[str, ...] = ()
    install_info: Mapping[str, Any] = field(default_factory=dict)
    health: Mapping[str, Any] = field(default_factory=dict)
    benchmark: Mapping[str, Any] = field(default_factory=dict)
    success_rate: float | None = None
    last_used_at: str = ""
    registered_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        state = (
            self.state
            if isinstance(self.state, ModelLifecycleState)
            else ModelLifecycleState(str(self.state))
        )
        if self.success_rate is not None and not (
            0.0 <= float(self.success_rate) <= 1.0
        ):
            raise ModelRegistryError(
                "success_rate must be between 0.0 and 1.0"
            )
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "enabled_roles",
            tuple(dict.fromkeys(str(item) for item in self.enabled_roles)),
        )
        for name in (
            "install_info",
            "health",
            "benchmark",
            "metadata",
        ):
            object.__setattr__(self, name, dict(getattr(self, name)))

    @property
    def enabled(self) -> bool:
        return self.state is ModelLifecycleState.ENABLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "state": self.state.value,
            "source": self.source,
            "location": self.location,
            "endpoint": self.endpoint,
            "enabled_roles": list(self.enabled_roles),
            "install_info": dict(self.install_info),
            "health": dict(self.health),
            "benchmark": dict(self.benchmark),
            "success_rate": self.success_rate,
            "last_used_at": self.last_used_at,
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelRecord":
        return cls(
            descriptor=ModelDescriptor.from_dict(
                data.get("descriptor") or {}
            ),
            state=str(
                data.get("state") or ModelLifecycleState.REGISTERED.value
            ),
            source=str(data.get("source") or ""),
            location=str(data.get("location") or ""),
            endpoint=str(data.get("endpoint") or ""),
            enabled_roles=tuple(data.get("enabled_roles") or ()),
            install_info=dict(data.get("install_info") or {}),
            health=dict(data.get("health") or {}),
            benchmark=dict(data.get("benchmark") or {}),
            success_rate=(
                float(data["success_rate"])
                if data.get("success_rate") is not None
                else None
            ),
            last_used_at=str(data.get("last_used_at") or ""),
            registered_at=str(data.get("registered_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )


class ModelRuntimeRegistry:
    """Thread-safe model catalog with optional atomic JSON persistence."""

    from nous_runtime.schema_registry import MODEL_CONFIG_SCHEMA_VERSION as _SCHEMA_VER

    SCHEMA_VERSION = _SCHEMA_VER

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self._records: dict[str, ModelRecord] = {}
        self._instances: dict[str, ModelInstance] = {}
        self._instances_by_model: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self._load()

    def register(
        self,
        descriptor: ModelDescriptor,
        *,
        state: ModelLifecycleState = ModelLifecycleState.REGISTERED,
        source: str = "",
        location: str = "",
        endpoint: str = "",
        enabled_roles: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
        replace_existing: bool = False,
    ) -> ModelRecord:
        if not isinstance(descriptor, ModelDescriptor):
            raise ModelRegistryError(
                "descriptor must be a ModelDescriptor"
            )
        with self._lock:
            if descriptor.model_id in self._records and not replace_existing:
                raise ModelRegistryError(
                    f"model already registered: {descriptor.model_id}"
                )
            record = ModelRecord(
                descriptor=descriptor,
                state=state,
                source=str(source or ""),
                location=str(location or ""),
                endpoint=str(endpoint or ""),
                enabled_roles=enabled_roles,
                metadata=dict(metadata or {}),
            )
            self._records[descriptor.model_id] = record
            self._save_unlocked()
            return record

    def get(self, model_id: str) -> ModelRecord | None:
        with self._lock:
            return self._records.get(str(model_id))

    def require(self, model_id: str) -> ModelRecord:
        record = self.get(model_id)
        if record is None:
            raise ModelRegistryError(f"model not found: {model_id}")
        return record

    def list(
        self,
        *,
        state: ModelLifecycleState | str | None = None,
        include_removed: bool = False,
    ) -> list[ModelRecord]:
        normalized = (
            state
            if isinstance(state, ModelLifecycleState)
            else ModelLifecycleState(str(state))
            if state
            else None
        )
        with self._lock:
            records = list(self._records.values())
        if not include_removed:
            records = [
                item
                for item in records
                if item.state is not ModelLifecycleState.REMOVED
            ]
        if normalized is not None:
            records = [
                item for item in records if item.state is normalized
            ]
        return sorted(records, key=lambda item: item.descriptor.model_id)

    def transition(
        self,
        model_id: str,
        target: ModelLifecycleState | str,
    ) -> ModelRecord:
        target_state = (
            target
            if isinstance(target, ModelLifecycleState)
            else ModelLifecycleState(str(target))
        )
        with self._lock:
            current = self.require(model_id)
            if target_state is current.state:
                return current
            if target_state not in _ALLOWED_TRANSITIONS[current.state]:
                raise ModelRegistryError(
                    "invalid model lifecycle transition: "
                    f"{current.state.value} -> {target_state.value}"
                )
            updated = replace(
                current,
                state=target_state,
                updated_at=utc_now(),
            )
            self._records[model_id] = updated
            if target_state in {
                ModelLifecycleState.DISABLED,
                ModelLifecycleState.BROKEN,
                ModelLifecycleState.REMOVED,
            }:
                for instance in self.instances_for(model_id):
                    instance.state = ModelInstanceState.DISABLED
            self._save_unlocked()
            return updated

    def enable(self, model_id: str) -> ModelRecord:
        return self.transition(model_id, ModelLifecycleState.ENABLED)

    def disable(self, model_id: str) -> ModelRecord:
        return self.transition(model_id, ModelLifecycleState.DISABLED)

    def update_health(
        self,
        model_id: str,
        health: Mapping[str, Any],
    ) -> ModelRecord:
        with self._lock:
            current = self.require(model_id)
            updated = replace(
                current,
                health=dict(health),
                updated_at=utc_now(),
            )
            self._records[model_id] = updated
            self._save_unlocked()
            return updated

    def record_usage(
        self,
        model_id: str,
        *,
        success_rate: float | None = None,
    ) -> ModelRecord:
        with self._lock:
            current = self.require(model_id)
            updated = replace(
                current,
                success_rate=(
                    current.success_rate
                    if success_rate is None
                    else success_rate
                ),
                last_used_at=utc_now(),
                updated_at=utc_now(),
            )
            self._records[model_id] = updated
            self._save_unlocked()
            return updated

    def register_instance(
        self,
        instance: ModelInstance,
        *,
        replace_existing: bool = False,
    ) -> ModelInstance:
        if not isinstance(instance, ModelInstance):
            raise ModelRegistryError(
                "instance must be a ModelInstance"
            )
        with self._lock:
            record = self.require(instance.model_id)
            if not record.enabled:
                raise ModelRegistryError(
                    "model must be enabled before instances are registered"
                )
            if (
                instance.instance_id in self._instances
                and not replace_existing
            ):
                raise ModelRegistryError(
                    f"instance already registered: {instance.instance_id}"
                )
            existing = self._instances.get(instance.instance_id)
            if existing is not None:
                previous = self._instances_by_model.get(existing.model_id)
                if previous is not None:
                    previous.discard(existing.instance_id)
                    if not previous:
                        self._instances_by_model.pop(
                            existing.model_id,
                            None,
                        )
            self._instances[instance.instance_id] = instance
            self._instances_by_model.setdefault(
                instance.model_id,
                set(),
            ).add(instance.instance_id)
            self._save_unlocked()
            return instance

    def get_instance(self, instance_id: str) -> ModelInstance | None:
        with self._lock:
            return self._instances.get(str(instance_id))

    def instances_for(self, model_id: str) -> list[ModelInstance]:
        with self._lock:
            values = [
                self._instances[instance_id]
                for instance_id in self._instances_by_model.get(
                    str(model_id),
                    (),
                )
            ]
        return sorted(values, key=lambda item: item.instance_id)

    def list_instances(self) -> list[ModelInstance]:
        with self._lock:
            return sorted(
                self._instances.values(),
                key=lambda item: item.instance_id,
            )

    def remove_instance(self, instance_id: str) -> ModelInstance | None:
        with self._lock:
            instance = self._instances.pop(str(instance_id), None)
            if instance is not None:
                model_instances = self._instances_by_model.get(
                    instance.model_id
                )
                if model_instances is not None:
                    model_instances.discard(instance.instance_id)
                    if not model_instances:
                        self._instances_by_model.pop(
                            instance.model_id,
                            None,
                        )
                self._save_unlocked()
            return instance

    def enabled_descriptors(self) -> list[ModelDescriptor]:
        return [
            item.descriptor
            for item in self.list(state=ModelLifecycleState.ENABLED)
            if item.descriptor.availability
        ]

    def flush(self) -> None:
        """Persist the current mutable instance state when configured."""
        with self._lock:
            self._save_unlocked()

    def _load(self) -> None:
        if self.storage_path is None or not self.storage_path.is_file():
            return
        try:
            payload = json.loads(
                self.storage_path.read_text(encoding="utf-8")
            )
            if int(payload.get("schema_version") or 0) != self.SCHEMA_VERSION:
                raise ModelRegistryError(
                    "unsupported model registry schema version"
                )
            records = [
                ModelRecord.from_dict(item)
                for item in payload.get("models") or ()
            ]
            instances = [
                ModelInstance.from_dict(item)
                for item in payload.get("instances") or ()
            ]
            model_ids = [item.descriptor.model_id for item in records]
            instance_ids = [item.instance_id for item in instances]
            if len(model_ids) != len(set(model_ids)):
                raise ModelRegistryError(
                    "model registry contains duplicate model IDs"
                )
            if len(instance_ids) != len(set(instance_ids)):
                raise ModelRegistryError(
                    "model registry contains duplicate instance IDs"
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ModelRegistryError):
                raise
            raise ModelRegistryError(
                f"failed to load model registry: {exc}"
            ) from exc
        self._records = {
            item.descriptor.model_id: item for item in records
        }
        for instance in instances:
            record = self._records.get(instance.model_id)
            if record is None:
                raise ModelRegistryError(
                    "model registry contains an orphan instance: "
                    f"{instance.instance_id}"
                )
            if not record.enabled:
                instance.state = ModelInstanceState.DISABLED
            if instance.state in {
                ModelInstanceState.BUSY,
                ModelInstanceState.SATURATED,
            }:
                instance.state = ModelInstanceState.READY
                instance.metadata["recovered_transient_state"] = True
            elif instance.state in {
                ModelInstanceState.LOADING,
                ModelInstanceState.UNLOADING,
            }:
                instance.state = ModelInstanceState.NOT_LOADED
                instance.metadata["recovered_transient_state"] = True
            instance.active_requests = 0
        self._instances = {
            item.instance_id: item for item in instances
        }
        self._instances_by_model = {}
        for instance in instances:
            self._instances_by_model.setdefault(
                instance.model_id,
                set(),
            ).add(instance.instance_id)

    def _save_unlocked(self) -> None:
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(
            self.storage_path.suffix + ".tmp"
        )
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "models": [
                item.to_dict()
                for item in sorted(
                    self._records.values(),
                    key=lambda record: record.descriptor.model_id,
                )
            ],
            "instances": [
                item.to_dict()
                for item in sorted(
                    self._instances.values(),
                    key=lambda instance: instance.instance_id,
                )
            ],
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.storage_path)


def descriptor_from_profile(profile: Any) -> ModelDescriptor:
    """Translate the existing compact ModelProfile without changing it."""
    privacy = str(getattr(profile, "privacy_level", "cloud"))
    endpoint_type = (
        ModelEndpointType.LOCAL_SERVICE
        if privacy == "local"
        else ModelEndpointType.CLOUD_API
    )
    capabilities = frozenset(getattr(profile, "capabilities", ()))
    modalities = {ModelModality.TEXT}
    if getattr(profile, "vision_score", 0.0) > 0:
        modalities.add(ModelModality.IMAGE)

    def level(score: float) -> CapabilityLevel:
        if score >= 0.8:
            return CapabilityLevel.HIGH
        if score >= 0.4:
            return CapabilityLevel.MEDIUM
        if score > 0:
            return CapabilityLevel.LOW
        return CapabilityLevel.NONE

    return ModelDescriptor(
        model_id=str(profile.model_id),
        display_name=str(profile.model_id),
        provider_id=str(profile.provider),
        endpoint_type=endpoint_type,
        modalities=frozenset(modalities),
        capabilities=capabilities,
        context_length=int(getattr(profile, "context_window", 0)),
        tool_calling=bool(getattr(profile, "supports_tools", False)),
        structured_output=bool(
            getattr(profile, "supports_structured_output", False)
        ),
        reasoning_level=level(
            float(getattr(profile, "reasoning_score", 0.0))
        ),
        coding_level=level(float(getattr(profile, "coding_score", 0.0))),
        vision_level=level(float(getattr(profile, "vision_score", 0.0))),
        latency_level=level(float(getattr(profile, "speed_score", 0.0))),
        cost_level=level(float(getattr(profile, "cost_score", 0.0))),
        privacy_class=(
            PrivacyClass.PRIVATE
            if privacy == "local"
            else PrivacyClass.STANDARD
        ),
        metadata={
            "legacy_profile_version": getattr(
                profile,
                "profile_version",
                "",
            )
        },
    )


__all__ = [
    "ModelRecord",
    "ModelRuntimeRegistry",
    "descriptor_from_profile",
]

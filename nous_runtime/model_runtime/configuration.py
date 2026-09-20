"""Declarative, rollback-safe model configuration application service."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nous_runtime.yaml_compat import yaml

from nous_runtime.model_runtime.errors import (
    ModelRegistryError,
    ModelRuntimeError,
)
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
    ModelLifecycleState,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry

from nous_runtime.schema_registry import MODEL_CONFIG_SCHEMA_VERSION as CONFIG_SCHEMA_VERSION
_ENV_REF = re.compile(r"^env:[A-Za-z_][A-Za-z0-9_]*$")
_CREDENTIAL_REF = re.compile(r"^credential:[A-Za-z0-9_.:/-]+$")
_SENSITIVE = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "private_key",
    "secret",
    "token",
)


@dataclass(frozen=True)
class ModelConfigAction:
    action: str
    model_id: str
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "model_id": self.model_id,
            "before": dict(self.before),
            "after": dict(self.after),
        }


@dataclass(frozen=True)
class ModelConfigPlan:
    schema_version: int
    actions: tuple[ModelConfigAction, ...]
    defaults_before: Mapping[str, str] = field(default_factory=dict)
    defaults_after: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.actions) or (
            dict(self.defaults_before) != dict(self.defaults_after)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "changed": self.changed,
            "actions": [item.to_dict() for item in self.actions],
            "defaults": {
                "before": dict(self.defaults_before),
                "after": dict(self.defaults_after),
            },
            "warnings": list(self.warnings),
        }


class ModelDefaultsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ModelRegistryError(
                f"failed to load model defaults: {exc}"
            ) from exc
        return {
            str(role): str(model_id)
            for role, model_id in dict(
                payload.get("roles") or {}
            ).items()
        }

    def write(self, roles: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "roles": dict(sorted(roles.items())),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


class DeclarativeModelConfigService:
    """Validate, diff, stage, atomically apply, back up and export config."""

    def __init__(
        self,
        registry_path: str | Path,
        *,
        defaults_path: str | Path | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.defaults = ModelDefaultsStore(
            defaults_path
            or self.registry_path.with_name("defaults.json")
        )

    def load(self, path: str | Path) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(
                Path(path).read_text(encoding="utf-8")
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ModelRuntimeError(
                f"failed to load model config: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ModelRuntimeError(
                "model config root must be a mapping"
            )
        result = dict(payload)
        self.validate(result)
        return result

    def validate(self, config: Mapping[str, Any]) -> None:
        version = int(config.get("schema_version") or 0)
        if version != CONFIG_SCHEMA_VERSION:
            raise ModelRuntimeError(
                f"unsupported model config schema version: {version}"
            )
        _reject_secrets(config)
        providers = dict(config.get("providers") or {})
        for provider_id, raw in providers.items():
            if not str(provider_id).strip() or not isinstance(raw, Mapping):
                raise ModelRuntimeError(
                    "provider definitions require mapping values"
                )
            reference = str(raw.get("credential_ref") or "")
            if reference and not (
                _ENV_REF.fullmatch(reference)
                or _CREDENTIAL_REF.fullmatch(reference)
            ):
                raise ModelRuntimeError(
                    f"provider {provider_id} has invalid credential_ref"
                )
        seen = set()
        for raw in config.get("models") or ():
            if not isinstance(raw, Mapping):
                raise ModelRuntimeError(
                    "model definitions must be mappings"
                )
            model_id = str(raw.get("model_id") or "").strip()
            if not model_id or model_id in seen:
                raise ModelRuntimeError(
                    "model IDs must be present and unique"
                )
            seen.add(model_id)
            provider_id = str(raw.get("provider_id") or "").strip()
            if not provider_id:
                raise ModelRuntimeError(
                    f"model {model_id} requires provider_id"
                )
            if providers and provider_id not in providers:
                raise ModelRuntimeError(
                    f"model {model_id} references unknown provider "
                    f"{provider_id}"
                )
            _descriptor(raw)
        defaults = dict(config.get("defaults") or {})
        for role, model_id in defaults.items():
            if str(model_id) not in seen:
                raise ModelRuntimeError(
                    f"default role {role} references unknown model "
                    f"{model_id}"
                )

    def plan(self, config: Mapping[str, Any]) -> ModelConfigPlan:
        self.validate(config)
        registry = ModelRuntimeRegistry(self.registry_path)
        current = {
            record.descriptor.model_id: record
            for record in registry.list(include_removed=True)
        }
        actions = []
        for raw in config.get("models") or ():
            model_id = str(raw["model_id"])
            desired = _record_payload(raw, config)
            existing = current.get(model_id)
            if existing is None:
                actions.append(
                    ModelConfigAction("add", model_id, after=desired)
                )
            elif _comparable(existing.to_dict()) != _comparable(desired):
                actions.append(
                    ModelConfigAction(
                        "update",
                        model_id,
                        before=existing.to_dict(),
                        after=desired,
                    )
                )
        configured_ids = {
            str(raw["model_id"]) for raw in config.get("models") or ()
        }
        if bool(config.get("prune", False)):
            for model_id, existing in current.items():
                if model_id not in configured_ids:
                    actions.append(
                        ModelConfigAction(
                            "remove",
                            model_id,
                            before=existing.to_dict(),
                        )
                    )
        return ModelConfigPlan(
            schema_version=CONFIG_SCHEMA_VERSION,
            actions=tuple(actions),
            defaults_before=self.defaults.read(),
            defaults_after={
                str(role): str(model_id)
                for role, model_id in dict(
                    config.get("defaults") or {}
                ).items()
            },
        )

    def apply(
        self,
        config: Mapping[str, Any],
        *,
        dry_run: bool = False,
    ) -> ModelConfigPlan:
        plan = self.plan(config)
        if dry_run or not plan.changed:
            return plan
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        transaction_id = uuid.uuid4().hex
        staged_registry = self.registry_path.with_name(
            f".{self.registry_path.name}.{transaction_id}.staged"
        )
        staged_defaults = self.defaults.path.with_name(
            f".{self.defaults.path.name}.{transaction_id}.staged"
        )
        registry_backup = self.registry_path.with_suffix(
            self.registry_path.suffix + ".bak"
        )
        defaults_backup = self.defaults.path.with_suffix(
            self.defaults.path.suffix + ".bak"
        )
        try:
            if self.registry_path.is_file():
                shutil.copy2(self.registry_path, staged_registry)
            staged = ModelRuntimeRegistry(staged_registry)
            for action in plan.actions:
                if action.action == "remove":
                    staged.register(
                        staged.require(action.model_id).descriptor,
                        state=ModelLifecycleState.REMOVED,
                        replace_existing=True,
                    )
                    continue
                raw = next(
                    item
                    for item in config.get("models") or ()
                    if str(item["model_id"]) == action.model_id
                )
                payload = _record_payload(raw, config)
                staged.register(
                    _descriptor(raw),
                    state=ModelLifecycleState(payload["state"]),
                    source=str(payload.get("source") or ""),
                    location=str(payload.get("location") or ""),
                    endpoint=str(payload.get("endpoint") or ""),
                    enabled_roles=tuple(
                        payload.get("enabled_roles") or ()
                    ),
                    metadata=dict(payload.get("metadata") or {}),
                    replace_existing=True,
                )
            staged.flush()
            ModelDefaultsStore(staged_defaults).write(
                plan.defaults_after
            )
            if self.registry_path.is_file():
                shutil.copy2(self.registry_path, registry_backup)
            if self.defaults.path.is_file():
                shutil.copy2(self.defaults.path, defaults_backup)
            os.replace(staged_registry, self.registry_path)
            os.replace(staged_defaults, self.defaults.path)
            ModelRuntimeRegistry(self.registry_path)
            self.defaults.read()
        except Exception as exc:
            if registry_backup.is_file():
                os.replace(registry_backup, self.registry_path)
            if defaults_backup.is_file():
                os.replace(defaults_backup, self.defaults.path)
            raise ModelRuntimeError(
                f"model config apply rolled back: {exc}"
            ) from exc
        finally:
            for path in (staged_registry, staged_defaults):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return plan

    def export(self) -> dict[str, Any]:
        registry = ModelRuntimeRegistry(self.registry_path)
        models = []
        providers: dict[str, dict[str, Any]] = {}
        for record in registry.list(include_removed=False):
            descriptor = record.descriptor
            providers.setdefault(
                descriptor.provider_id,
                {
                    "kind": descriptor.endpoint_type.value,
                    "credential_ref": str(
                        record.metadata.get("credential_ref") or ""
                    ),
                },
            )
            models.append(
                {
                    **descriptor.to_dict(),
                    "state": record.state.value,
                    "source": record.source,
                    "location": record.location,
                    "endpoint": record.endpoint,
                    "enabled_roles": list(record.enabled_roles),
                    "metadata": dict(descriptor.metadata),
                    "record_metadata": {
                        key: value
                        for key, value in record.metadata.items()
                        if not any(
                            marker in str(key).casefold()
                            for marker in _SENSITIVE
                        )
                    },
                }
            )
        payload = {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "providers": providers,
            "models": models,
            "defaults": self.defaults.read(),
        }
        _reject_secrets(payload)
        return payload


def _descriptor(raw: Mapping[str, Any]) -> ModelDescriptor:
    data = dict(raw)
    data.setdefault(
        "display_name",
        str(data.get("model_id") or ""),
    )
    data.setdefault(
        "endpoint_type",
        ModelEndpointType.CLOUD_API.value,
    )
    return ModelDescriptor.from_dict(data)


def _record_payload(
    raw: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    provider = dict(
        dict(config.get("providers") or {}).get(
            str(raw.get("provider_id") or ""),
            {},
        )
    )
    record_metadata = dict(
        raw.get("record_metadata") or {}
    )
    state = str(
        raw.get("state")
        or (
            ModelLifecycleState.ENABLED.value
            if raw.get("enabled", True)
            else ModelLifecycleState.DISABLED.value
        )
    )
    if state not in {
        ModelLifecycleState.REGISTERED.value,
        ModelLifecycleState.ENABLED.value,
        ModelLifecycleState.DISABLED.value,
    }:
        raise ModelRuntimeError(
            f"declarative model state is unsupported: {state}"
        )
    return {
        "descriptor": _descriptor(raw).to_dict(),
        "state": state,
        "source": str(raw.get("source") or ""),
        "location": str(raw.get("location") or ""),
        "endpoint": str(
            raw.get("endpoint") or provider.get("endpoint") or ""
        ),
        "enabled_roles": list(raw.get("enabled_roles") or ()),
        "metadata": {
            **record_metadata,
            "credential_ref": str(provider.get("credential_ref") or ""),
            "route_priority": raw.get(
                "route_priority",
                record_metadata.get("route_priority"),
            ),
            "fallback": list(
                raw.get(
                    "fallback",
                    record_metadata.get("fallback") or (),
                )
            ),
            "download_sources": list(
                raw.get(
                    "download_sources",
                    record_metadata.get("download_sources") or (),
                )
            ),
            "install_target": str(
                raw.get(
                    "install_target",
                    record_metadata.get("install_target") or "",
                )
            ),
        },
    }


def _comparable(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    for key in (
        "registered_at",
        "updated_at",
        "last_used_at",
        "health",
        "benchmark",
        "success_rate",
        "install_info",
    ):
        data.pop(key, None)
    return data


def _reject_secrets(value: Any, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(marker in normalized for marker in _SENSITIVE):
                if normalized != "credential_ref":
                    raise ModelRuntimeError(
                        f"{path}.{key} cannot contain a secret"
                    )
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DeclarativeModelConfigService",
    "ModelConfigAction",
    "ModelConfigPlan",
    "ModelDefaultsStore",
]

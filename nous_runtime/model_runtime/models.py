"""Canonical data contracts for the unified model runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Mapping

from nous_runtime.model_runtime.errors import ModelRuntimeError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ModelEndpointType(str, Enum):
    LOCAL_MODEL = "local_model"
    LOCAL_SERVICE = "local_service"
    CLOUD_API = "cloud_api"
    REMOTE_CLUSTER = "remote_cluster"
    PROFESSIONAL_AGENT = "professional_agent"


class ModelModality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    IMAGE_GENERATION = "image_generation"
    AUDIO_GENERATION = "audio_generation"
    VIDEO_GENERATION = "video_generation"


class CapabilityLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PrivacyClass(str, Enum):
    PUBLIC = "public"
    STANDARD = "standard"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class ModelInstanceState(str, Enum):
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
    READY = "ready"
    BUSY = "busy"
    SATURATED = "saturated"
    UNLOADING = "unloading"
    FAILED = "failed"
    DISABLED = "disabled"


class ModelLifecycleState(str, Enum):
    DISCOVERED = "discovered"
    DOWNLOADING = "downloading"
    PARTIAL = "partial"
    INSTALLED = "installed"
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    BROKEN = "broken"
    REMOVED = "removed"


class RoutingMode(str, Enum):
    AUTO = "auto"
    PREFERRED = "preferred"
    LOCKED = "locked"
    LOCAL_ONLY = "local_only"
    REMOTE_ONLY = "remote_only"
    OFFLINE = "offline"


class ModelRole(str, Enum):
    RESIDENT = "resident"
    CONVERSATION = "conversation"
    PLANNER = "planner"
    WORKER = "worker"
    REVIEWER = "reviewer"
    SAFETY_REVIEWER = "safety_reviewer"
    VISION = "vision"
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    CODE_WORKER = "code_worker"


def _enum_value(value: Enum | str, enum_type: type[Enum], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ModelRuntimeError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _enum_set(
    values: tuple[Enum | str, ...] | list[Enum | str] | set[Enum | str],
    enum_type: type[Enum],
    field_name: str,
) -> frozenset[Any]:
    return frozenset(
        _enum_value(value, enum_type, field_name)
        for value in values
    )


@dataclass(frozen=True)
class ResourceRequirements:
    memory_mb: int = 0
    vram_mb: int = 0
    disk_mb: int = 0
    cpu_cores: float = 0.0
    gpu_required: bool = False
    accelerators: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("memory_mb", "vram_mb", "disk_mb"):
            value = int(getattr(self, name))
            if value < 0:
                raise ModelRuntimeError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)
        cpu_cores = float(self.cpu_cores)
        if cpu_cores < 0 or not math.isfinite(cpu_cores):
            raise ModelRuntimeError("cpu_cores must be non-negative")
        object.__setattr__(self, "cpu_cores", cpu_cores)
        object.__setattr__(
            self,
            "accelerators",
            tuple(dict.fromkeys(str(item) for item in self.accelerators)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_mb": self.memory_mb,
            "vram_mb": self.vram_mb,
            "disk_mb": self.disk_mb,
            "cpu_cores": self.cpu_cores,
            "gpu_required": self.gpu_required,
            "accelerators": list(self.accelerators),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResourceRequirements":
        return cls(
            memory_mb=int(data.get("memory_mb") or 0),
            vram_mb=int(data.get("vram_mb") or 0),
            disk_mb=int(data.get("disk_mb") or 0),
            cpu_cores=float(data.get("cpu_cores") or 0.0),
            gpu_required=bool(data.get("gpu_required", False)),
            accelerators=tuple(data.get("accelerators") or ()),
        )


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    display_name: str
    provider_id: str
    endpoint_type: ModelEndpointType
    modalities: frozenset[ModelModality] = field(
        default_factory=lambda: frozenset({ModelModality.TEXT})
    )
    capabilities: frozenset[str] = field(default_factory=frozenset)
    context_length: int = 0
    tool_calling: bool = False
    structured_output: bool = False
    reasoning_level: CapabilityLevel = CapabilityLevel.MEDIUM
    coding_level: CapabilityLevel = CapabilityLevel.MEDIUM
    vision_level: CapabilityLevel = CapabilityLevel.NONE
    latency_level: CapabilityLevel = CapabilityLevel.MEDIUM
    cost_level: CapabilityLevel = CapabilityLevel.MEDIUM
    privacy_class: PrivacyClass = PrivacyClass.STANDARD
    license_info: Mapping[str, Any] = field(default_factory=dict)
    resource_requirements: ResourceRequirements = field(
        default_factory=ResourceRequirements
    )
    availability: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("model_id", "display_name", "provider_id"):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ModelRuntimeError(f"{name} is required")
            object.__setattr__(self, name, normalized)
        object.__setattr__(
            self,
            "endpoint_type",
            _enum_value(
                self.endpoint_type,
                ModelEndpointType,
                "endpoint_type",
            ),
        )
        object.__setattr__(
            self,
            "modalities",
            _enum_set(
                tuple(self.modalities),
                ModelModality,
                "modalities",
            ),
        )
        object.__setattr__(
            self,
            "capabilities",
            frozenset(
                str(item).strip()
                for item in self.capabilities
                if str(item).strip()
            ),
        )
        context_length = int(self.context_length)
        if context_length < 0:
            raise ModelRuntimeError("context_length must be non-negative")
        object.__setattr__(self, "context_length", context_length)
        for name in (
            "reasoning_level",
            "coding_level",
            "vision_level",
            "latency_level",
            "cost_level",
        ):
            object.__setattr__(
                self,
                name,
                _enum_value(getattr(self, name), CapabilityLevel, name),
            )
        object.__setattr__(
            self,
            "privacy_class",
            _enum_value(
                self.privacy_class,
                PrivacyClass,
                "privacy_class",
            ),
        )
        if isinstance(self.resource_requirements, Mapping):
            object.__setattr__(
                self,
                "resource_requirements",
                ResourceRequirements.from_dict(self.resource_requirements),
            )
        if not isinstance(self.resource_requirements, ResourceRequirements):
            raise ModelRuntimeError(
                "resource_requirements must be ResourceRequirements"
            )
        object.__setattr__(self, "license_info", dict(self.license_info))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_local(self) -> bool:
        return self.endpoint_type in {
            ModelEndpointType.LOCAL_MODEL,
            ModelEndpointType.LOCAL_SERVICE,
        }

    def supports(
        self,
        capabilities: set[str] | frozenset[str] | tuple[str, ...],
        modalities: set[ModelModality] | frozenset[ModelModality] | tuple[ModelModality, ...],
    ) -> bool:
        required_modalities = _enum_set(
            tuple(modalities),
            ModelModality,
            "modalities",
        )
        return set(capabilities).issubset(self.capabilities) and (
            required_modalities.issubset(self.modalities)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "provider_id": self.provider_id,
            "endpoint_type": self.endpoint_type.value,
            "modalities": sorted(item.value for item in self.modalities),
            "capabilities": sorted(self.capabilities),
            "context_length": self.context_length,
            "tool_calling": self.tool_calling,
            "structured_output": self.structured_output,
            "reasoning_level": self.reasoning_level.value,
            "coding_level": self.coding_level.value,
            "vision_level": self.vision_level.value,
            "latency_level": self.latency_level.value,
            "cost_level": self.cost_level.value,
            "privacy_class": self.privacy_class.value,
            "license_info": dict(self.license_info),
            "resource_requirements": self.resource_requirements.to_dict(),
            "availability": self.availability,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelDescriptor":
        return cls(
            model_id=str(data.get("model_id") or ""),
            display_name=str(data.get("display_name") or ""),
            provider_id=str(data.get("provider_id") or ""),
            endpoint_type=str(
                data.get("endpoint_type") or ModelEndpointType.CLOUD_API.value
            ),
            modalities=frozenset(data.get("modalities") or ("text",)),
            capabilities=frozenset(data.get("capabilities") or ()),
            context_length=int(data.get("context_length") or 0),
            tool_calling=bool(data.get("tool_calling", False)),
            structured_output=bool(data.get("structured_output", False)),
            reasoning_level=str(
                data.get("reasoning_level") or CapabilityLevel.MEDIUM.value
            ),
            coding_level=str(
                data.get("coding_level") or CapabilityLevel.MEDIUM.value
            ),
            vision_level=str(
                data.get("vision_level") or CapabilityLevel.NONE.value
            ),
            latency_level=str(
                data.get("latency_level") or CapabilityLevel.MEDIUM.value
            ),
            cost_level=str(
                data.get("cost_level") or CapabilityLevel.MEDIUM.value
            ),
            privacy_class=str(
                data.get("privacy_class") or PrivacyClass.STANDARD.value
            ),
            license_info=dict(data.get("license_info") or {}),
            resource_requirements=ResourceRequirements.from_dict(
                data.get("resource_requirements") or {}
            ),
            availability=bool(data.get("availability", True)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ModelInstance:
    instance_id: str
    model_id: str
    node_id: str
    backend: str
    state: ModelInstanceState = ModelInstanceState.NOT_LOADED
    active_requests: int = 0
    max_concurrency: int = 1
    memory_mb: int = 0
    vram_mb: int = 0
    loaded_at: str = ""
    last_used_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("instance_id", "model_id", "node_id", "backend"):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ModelRuntimeError(f"{name} is required")
            setattr(self, name, normalized)
        self.state = _enum_value(
            self.state,
            ModelInstanceState,
            "state",
        )
        self.active_requests = int(self.active_requests)
        self.max_concurrency = int(self.max_concurrency)
        self.memory_mb = int(self.memory_mb)
        self.vram_mb = int(self.vram_mb)
        if self.active_requests < 0:
            raise ModelRuntimeError("active_requests must be non-negative")
        if self.max_concurrency < 1:
            raise ModelRuntimeError("max_concurrency must be at least 1")
        if self.memory_mb < 0 or self.vram_mb < 0:
            raise ModelRuntimeError(
                "instance memory values must be non-negative"
            )
        self.metadata = dict(self.metadata)

    @property
    def has_capacity(self) -> bool:
        return (
            self.state
            in {
                ModelInstanceState.READY,
                ModelInstanceState.BUSY,
            }
            and self.active_requests < self.max_concurrency
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "model_id": self.model_id,
            "node_id": self.node_id,
            "backend": self.backend,
            "state": self.state.value,
            "active_requests": self.active_requests,
            "max_concurrency": self.max_concurrency,
            "memory_mb": self.memory_mb,
            "vram_mb": self.vram_mb,
            "loaded_at": self.loaded_at,
            "last_used_at": self.last_used_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelInstance":
        return cls(
            instance_id=str(data.get("instance_id") or ""),
            model_id=str(data.get("model_id") or ""),
            node_id=str(data.get("node_id") or ""),
            backend=str(data.get("backend") or ""),
            state=str(
                data.get("state") or ModelInstanceState.NOT_LOADED.value
            ),
            active_requests=int(data.get("active_requests") or 0),
            max_concurrency=(
                int(data["max_concurrency"])
                if data.get("max_concurrency") is not None
                else 1
            ),
            memory_mb=int(data.get("memory_mb") or 0),
            vram_mb=int(data.get("vram_mb") or 0),
            loaded_at=str(data.get("loaded_at") or ""),
            last_used_at=str(data.get("last_used_at") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ModelRequest:
    task_id: str
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    required_modalities: frozenset[ModelModality] = field(
        default_factory=lambda: frozenset({ModelModality.TEXT})
    )
    messages: tuple[Mapping[str, Any], ...] = ()
    attachments: tuple[Mapping[str, Any], ...] = ()
    role: ModelRole = ModelRole.WORKER
    preferred_models: tuple[str, ...] = ()
    forbidden_models: frozenset[str] = field(default_factory=frozenset)
    routing_mode: RoutingMode = RoutingMode.AUTO
    privacy_policy: PrivacyClass = PrivacyClass.STANDARD
    required_location: str = ""
    min_context_length: int = 0
    quality_target: float = 0.5
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None
    timeout_s: float = 60.0
    stream: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: _identifier("modelreq"))

    def __post_init__(self) -> None:
        if not str(self.task_id or "").strip():
            raise ModelRuntimeError("task_id is required")
        if not str(self.request_id or "").strip():
            raise ModelRuntimeError("request_id is required")
        object.__setattr__(
            self,
            "required_capabilities",
            frozenset(
                str(item).strip()
                for item in self.required_capabilities
                if str(item).strip()
            ),
        )
        object.__setattr__(
            self,
            "required_modalities",
            _enum_set(
                tuple(self.required_modalities),
                ModelModality,
                "required_modalities",
            ),
        )
        object.__setattr__(
            self,
            "messages",
            tuple(dict(item) for item in self.messages),
        )
        object.__setattr__(
            self,
            "attachments",
            tuple(dict(item) for item in self.attachments),
        )
        object.__setattr__(
            self,
            "role",
            _enum_value(self.role, ModelRole, "role"),
        )
        object.__setattr__(
            self,
            "routing_mode",
            _enum_value(
                self.routing_mode,
                RoutingMode,
                "routing_mode",
            ),
        )
        object.__setattr__(
            self,
            "privacy_policy",
            _enum_value(
                self.privacy_policy,
                PrivacyClass,
                "privacy_policy",
            ),
        )
        object.__setattr__(
            self,
            "required_location",
            str(self.required_location or "").strip().lower(),
        )
        object.__setattr__(
            self,
            "min_context_length",
            int(self.min_context_length),
        )
        object.__setattr__(
            self,
            "quality_target",
            float(self.quality_target),
        )
        object.__setattr__(self, "timeout_s", float(self.timeout_s))
        if self.max_latency_ms is not None:
            object.__setattr__(
                self,
                "max_latency_ms",
                int(self.max_latency_ms),
            )
        if self.max_cost_usd is not None:
            object.__setattr__(
                self,
                "max_cost_usd",
                float(self.max_cost_usd),
            )
        if self.min_context_length < 0:
            raise ModelRuntimeError(
                "min_context_length must be non-negative"
            )
        if (
            not math.isfinite(self.quality_target)
            or not 0.0 <= self.quality_target <= 1.0
        ):
            raise ModelRuntimeError(
                "quality_target must be between 0.0 and 1.0"
            )
        if self.max_latency_ms is not None and self.max_latency_ms < 0:
            raise ModelRuntimeError(
                "max_latency_ms must be non-negative"
            )
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ModelRuntimeError(
                "max_cost_usd must be non-negative"
            )
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ModelRuntimeError("timeout_s must be positive")
        object.__setattr__(
            self,
            "preferred_models",
            tuple(dict.fromkeys(str(item) for item in self.preferred_models)),
        )
        object.__setattr__(
            self,
            "forbidden_models",
            frozenset(str(item) for item in self.forbidden_models),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "required_capabilities": sorted(self.required_capabilities),
            "required_modalities": sorted(
                item.value for item in self.required_modalities
            ),
            "messages": [dict(item) for item in self.messages],
            "attachments": [dict(item) for item in self.attachments],
            "role": self.role.value,
            "preferred_models": list(self.preferred_models),
            "forbidden_models": sorted(self.forbidden_models),
            "routing_mode": self.routing_mode.value,
            "privacy_policy": self.privacy_policy.value,
            "required_location": self.required_location,
            "min_context_length": self.min_context_length,
            "quality_target": self.quality_target,
            "max_latency_ms": self.max_latency_ms,
            "max_cost_usd": self.max_cost_usd,
            "timeout_s": self.timeout_s,
            "stream": self.stream,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelRequest":
        return cls(
            request_id=str(data.get("request_id") or _identifier("modelreq")),
            task_id=str(data.get("task_id") or ""),
            required_capabilities=frozenset(
                data.get("required_capabilities") or ()
            ),
            required_modalities=frozenset(
                data.get("required_modalities") or ("text",)
            ),
            messages=tuple(data.get("messages") or ()),
            attachments=tuple(data.get("attachments") or ()),
            role=str(data.get("role") or ModelRole.WORKER.value),
            preferred_models=tuple(data.get("preferred_models") or ()),
            forbidden_models=frozenset(data.get("forbidden_models") or ()),
            routing_mode=str(
                data.get("routing_mode") or RoutingMode.AUTO.value
            ),
            privacy_policy=str(
                data.get("privacy_policy") or PrivacyClass.STANDARD.value
            ),
            required_location=str(data.get("required_location") or ""),
            min_context_length=int(data.get("min_context_length") or 0),
            quality_target=(
                float(data["quality_target"])
                if data.get("quality_target") is not None
                else 0.5
            ),
            max_latency_ms=(
                int(data["max_latency_ms"])
                if data.get("max_latency_ms") is not None
                else None
            ),
            max_cost_usd=(
                float(data["max_cost_usd"])
                if data.get("max_cost_usd") is not None
                else None
            ),
            timeout_s=(
                float(data["timeout_s"])
                if data.get("timeout_s") is not None
                else 60.0
            ),
            stream=bool(data.get("stream", False)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RejectedModel:
    model_id: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"model_id": self.model_id, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class RouteDecision:
    request_id: str
    selected_model_id: str
    selected_instance_id: str
    fallback_model_ids: tuple[str, ...]
    score: float
    reasons: tuple[str, ...]
    rejected: tuple[RejectedModel, ...] = ()
    scores: Mapping[str, float] = field(default_factory=dict)
    decision_id: str = field(default_factory=lambda: _identifier("route"))
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "selected_model_id": self.selected_model_id,
            "selected_instance_id": self.selected_instance_id,
            "fallback_model_ids": list(self.fallback_model_ids),
            "score": self.score,
            "reasons": list(self.reasons),
            "rejected": [item.to_dict() for item in self.rejected],
            "scores": dict(self.scores),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ModelResponse:
    request_id: str
    model_id: str
    instance_id: str
    content: Any = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: str = "completed"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    response_id: str = field(default_factory=lambda: _identifier("modelresp"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_usd", float(self.cost_usd))
        object.__setattr__(self, "latency_ms", int(self.latency_ms))
        if (
            not math.isfinite(self.cost_usd)
            or self.cost_usd < 0
            or self.latency_ms < 0
        ):
            raise ModelRuntimeError(
                "response cost and latency must be non-negative"
            )
        object.__setattr__(self, "usage", dict(self.usage))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "request_id": self.request_id,
            "model_id": self.model_id,
            "instance_id": self.instance_id,
            "content": self.content,
            "usage": dict(self.usage),
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ModelPackage:
    package_id: str
    model_id: str
    capabilities: frozenset[str]
    modalities: frozenset[ModelModality]
    disk_mb: int
    vram_mb: int = 0
    license_approved: bool = True
    source: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.package_id or not self.model_id:
            raise ModelRuntimeError(
                "package_id and model_id are required"
            )
        object.__setattr__(self, "disk_mb", int(self.disk_mb))
        object.__setattr__(self, "vram_mb", int(self.vram_mb))
        if self.disk_mb < 0 or self.vram_mb < 0:
            raise ModelRuntimeError(
                "package resource values must be non-negative"
            )
        object.__setattr__(
            self,
            "capabilities",
            frozenset(str(item) for item in self.capabilities),
        )
        object.__setattr__(
            self,
            "modalities",
            _enum_set(
                tuple(self.modalities),
                ModelModality,
                "modalities",
            ),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class CapabilityResolution:
    selected_packages: tuple[ModelPackage, ...]
    covered_capabilities: frozenset[str]
    uncovered_capabilities: frozenset[str]
    covered_modalities: frozenset[ModelModality]
    uncovered_modalities: frozenset[ModelModality]
    estimated_disk_mb: int
    estimated_vram_mb: int
    alternative_plans: tuple[tuple[str, ...], ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.uncovered_capabilities and not self.uncovered_modalities


__all__ = [
    "CapabilityLevel",
    "CapabilityResolution",
    "ModelDescriptor",
    "ModelEndpointType",
    "ModelInstance",
    "ModelInstanceState",
    "ModelLifecycleState",
    "ModelModality",
    "ModelPackage",
    "ModelRequest",
    "ModelResponse",
    "ModelRole",
    "PrivacyClass",
    "RejectedModel",
    "ResourceRequirements",
    "RouteDecision",
    "RoutingMode",
    "utc_now",
]

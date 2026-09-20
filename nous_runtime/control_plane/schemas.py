# -*- coding: utf-8 -*-
"""
Control Plane API schemas — Pydantic v2 models for all v1 endpoints.

All request/response types are defined here. Frontend TypeScript types
MUST be generated from these schemas — no hand-written type duplication.

Design constraints:
- Stable error model with ErrorCode enum
- Pagination on all list endpoints
- Filter support via query parameters
- correlation_id + request_id on every request
- Idempotency keys on mutation requests
- No sensitive data in responses
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, field_validator



# Envelope


class ErrorCode(str, Enum):
    """Stable error codes. Never remove — only add."""
    # 4xx
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    UNPROCESSABLE_ENTITY = "UNPROCESSABLE_ENTITY"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    # 5xx
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    # Domain
    VALIDATION_ERROR = "VALIDATION_ERROR"
    STATE_TRANSITION_INVALID = "STATE_TRANSITION_INVALID"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    GOVERNANCE_DENIED = "GOVERNANCE_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    NODE_OFFLINE = "NODE_OFFLINE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    TASK_CANCELLED = "TASK_CANCELLED"
    PLATFORM_UNSUPPORTED = "PLATFORM_UNSUPPORTED"
    FEATURE_DISABLED = "FEATURE_DISABLED"


class ApiError(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: ApiError | None = None
    request_id: str | None = None
    correlation_id: str | None = None



# Pagination


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    sort_by: str | None = None
    sort_order: str = Field(default="asc", pattern=r"^(asc|desc)$")

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool



# Runtime


class RuntimeStatusResponse(BaseModel):
    version: str
    running: bool
    uptime_seconds: float
    demo_mode: bool
    providers_count: int
    capabilities_count: int
    nodes_count: int
    tasks_pending: int
    tasks_running: int
    workspace_path: str
    errors: list[str] = Field(default_factory=list)

class RuntimeHealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "down"
    runtime: str
    database: str
    providers: dict[str, str]
    workspace: str
    system: dict[str, Any] = Field(default_factory=dict)
    checks: dict[str, str] = Field(default_factory=dict)

class RuntimeCapabilitiesResponse(BaseModel):
    capabilities: list[dict[str, Any]]
    total: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_provider: dict[str, int] = Field(default_factory=dict)



# Node


class NodeResources(BaseModel):
    cpu_cores: int | None = None
    cpu_percent: float | None = None
    memory_mb: int | None = None
    memory_percent: float | None = None
    gpu_name: str | None = None
    gpu_memory_mb: int | None = None
    disk_total_mb: int | None = None
    disk_percent: float | None = None
    network_status: str | None = None

class NodeResponse(BaseModel):
    node_id: str
    node_name: str
    node_role: str
    platform_os: str
    platform_arch: str
    platform_hostname: str
    runtime_tier: str
    word_size_bits: int
    online: bool = False
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)
    resources: NodeResources | None = None
    current_tasks: int = 0
    max_concurrent_tasks: int = 1
    resource_reservation_pct: float = 0.0
    accept_tasks: bool = True
    tags: list[str] = Field(default_factory=list)
    is_master: bool = False
    last_heartbeat: str | None = None
    registered_at: str | None = None
    runtime_version: str | None = None
    credential_id: str | None = None

    @field_validator("credential_id")
    @classmethod
    def mask_credential(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v[:4] + "****" if len(v) > 4 else "****"

class NodeListResponse(BaseModel):
    nodes: list[NodeResponse]
    pagination: PaginationMeta
    online_count: int
    total_count: int

class NodeEnableRequest(BaseModel):
    enabled: bool
    request_id: str | None = None

class NodeTestRequest(BaseModel):
    request_id: str | None = None



# Model


class ModelResponse(BaseModel):
    model_id: str
    display_name: str
    provider_id: str
    endpoint_type: str
    modalities: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    context_length: int
    tool_calling: bool = False
    structured_output: bool = False
    reasoning_level: str = "NONE"
    coding_level: str = "NONE"
    vision_level: str = "NONE"
    latency_level: str = "NONE"
    cost_level: str = "NONE"
    privacy_class: str = "STANDARD"
    is_local: bool = False
    availability: bool = True
    health_status: str = "unknown"
    concurrency_limit: int | None = None
    rate_limit_per_minute: int | None = None
    cost_per_1k_tokens: float | None = None
    node_id: str | None = None
    license_info: dict[str, Any] = Field(default_factory=dict)
    manifest_version: str | None = None

class ModelListResponse(BaseModel):
    models: list[ModelResponse]
    pagination: PaginationMeta
    total_count: int
    available_count: int

class ModelTestRequest(BaseModel):
    prompt: str | None = None
    request_id: str | None = None



# Provider


class ProviderResponse(BaseModel):
    provider_id: str
    name: str
    api_base_url: str | None = None
    credential_ref: str | None = None  # masked reference only
    capabilities: list[str] = Field(default_factory=list)
    models_count: int = 0
    health_status: str = "unknown"
    last_health_check: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("credential_ref")
    @classmethod
    def mask_credential(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v.startswith("env:"):
            return v[:4] + "****"
        if v.startswith("secret:"):
            return v[:7] + "****"
        return "****"

class ProviderListResponse(BaseModel):
    providers: list[ProviderResponse]
    pagination: PaginationMeta

class ProviderCreateRequest(BaseModel):
    provider_id: str = Field(..., pattern=r"^[a-z0-9_]+$")
    name: str
    api_base_url: str | None = None
    credential_ref: str | None = Field(default=None, description="Credential reference (env:VAR or secret:svc/acct)")
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    idempotency_key: str | None = None

class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    api_base_url: str | None = None
    credential_ref: str | None = None
    enabled: bool | None = None
    capabilities: list[str] | None = None
    metadata: dict[str, Any] | None = None
    request_id: str | None = None

class ProviderTestRequest(BaseModel):
    model_id: str | None = None
    request_id: str | None = None



# Task


class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_RESOURCE = "WAITING_FOR_RESOURCE"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"

class TaskResponse(BaseModel):
    task_id: str
    title: str
    description: str | None = None
    status: TaskStatus
    priority: str = "NORMAL"
    created_at: str
    updated_at: str | None = None
    model_id: str | None = None
    node_id: str | None = None
    execution_route: str | None = None
    progress_pct: float = 0.0
    current_step: str | None = None
    step_index: int = 0
    total_steps: int = 0
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    correlation_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    pagination: PaginationMeta
    status_counts: dict[str, int] = Field(default_factory=dict)

class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    model_id: str | None = None
    model_group: str | None = None
    model_preference: str | None = Field(
        default=None,
        description="auto | specific | local_only | local_first | cloud_first | high_quality | low_cost | low_latency"
    )
    node_id: str | None = None
    node_preference: str | None = Field(
        default=None,
        description="auto | current_device | master | specific | local_first | server_first | edge_first"
    )
    execution_route: str | None = Field(
        default=None,
        description="standard | local_first | privacy_first | high_quality | low_latency | low_cost | deep_research | code_task | long_running"
    )
    priority: str = "NORMAL"
    tags: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    idempotency_key: str | None = None

class TaskAnalyzeRequest(BaseModel):
    input_text: str = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None

class TaskAnalyzeResponse(BaseModel):
    analysis_id: str
    intent: str
    complexity: str
    required_capabilities: list[str] = Field(default_factory=list)
    suggested_models: list[str] = Field(default_factory=list)
    suggested_nodes: list[str] = Field(default_factory=list)
    suggested_route: str | None = None
    estimated_steps: int = 0
    risks: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    raw_analysis: dict[str, Any] = Field(default_factory=dict)

class TaskPlanResponse(BaseModel):
    plan_id: str
    task_title: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    selected_model: str | None = None
    selected_node: str | None = None
    selected_route: str | None = None
    excluded_models: list[dict[str, Any]] = Field(default_factory=list)
    excluded_nodes: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    estimated_time_seconds: float | None = None
    estimated_cost_usd: float | None = None
    estimated_resources: dict[str, Any] = Field(default_factory=dict)

class TaskPlanRequest(BaseModel):
    analysis_id: str
    model_id: str | None = None
    node_id: str | None = None
    execution_route: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None

class TaskApproveRequest(BaseModel):
    approved: bool
    modifications: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None

class TaskEventResponse(BaseModel):
    events: list[dict[str, Any]]
    pagination: PaginationMeta
    latest_sequence: int = 0

class TaskArtifactResponse(BaseModel):
    artifacts: list[dict[str, Any]]
    total: int

class TaskReportResponse(BaseModel):
    task_id: str
    status: TaskStatus
    summary: str
    steps_completed: int
    total_steps: int
    duration_seconds: float
    model_used: str | None = None
    node_used: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    cost_usd: float | None = None
    tokens_used: int = 0
    errors: list[str] = Field(default_factory=list)
    created_at: str
    completed_at: str | None = None



# Conversation


class ConversationResponse(BaseModel):
    conversation_id: str
    title: str | None = None
    created_at: str
    updated_at: str | None = None
    message_count: int = 0
    task_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
    pagination: PaginationMeta

class ConversationCreateRequest(BaseModel):
    title: str | None = None
    task_id: str | None = None
    request_id: str | None = None

class MessageCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    role: str = Field(default="user", pattern=r"^(user|system)$")
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str | None = None



# Inspector


class InspectorRuntimeSnapshot(BaseModel):
    version: str
    running: bool
    demo_mode: bool
    uptime_seconds: float
    providers_count: int
    capabilities_count: int
    nodes_count: int
    tasks_pending: int
    tasks_running: int
    workspace_path: str
    errors: list[str] = Field(default_factory=list)

class InspectorProviderSnapshot(BaseModel):
    provider_id: str
    name: str
    status: str
    capabilities: list[str] = Field(default_factory=list)
    models: int = 0
    error: str | None = None

class InspectorTaskSnapshot(BaseModel):
    task_id: str
    title: str
    status: str
    priority: str
    node_id: str | None = None
    model_id: str | None = None
    progress_pct: float = 0.0
    error: str | None = None

class InspectorNodeSnapshot(BaseModel):
    node_id: str
    node_name: str
    online: bool = False
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)
    current_tasks: int = 0
    last_heartbeat: str | None = None

class InspectorMetricSnapshot(BaseModel):
    memory_mb: float | None = None
    cpu_percent: float | None = None
    disk_percent: float | None = None
    uptime_seconds: float | None = None

class InspectorSnapshotResponse(BaseModel):
    timestamp: str
    runtime: InspectorRuntimeSnapshot
    providers: list[InspectorProviderSnapshot] = Field(default_factory=list)
    tasks: list[InspectorTaskSnapshot] = Field(default_factory=list)
    nodes: list[InspectorNodeSnapshot] = Field(default_factory=list)
    metrics: InspectorMetricSnapshot | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)



# Decision


class DecisionResponse(BaseModel):
    decision_id: str
    task_id: str | None = None
    decision_type: str
    status: str
    selected: dict[str, Any] | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    resolved_at: str | None = None
    confidence: float | None = None

class DecisionListResponse(BaseModel):
    decisions: list[DecisionResponse]
    pagination: PaginationMeta



# Log


class LogEntryResponse(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str
    correlation_id: str | None = None
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class LogListResponse(BaseModel):
    entries: list[LogEntryResponse]
    pagination: PaginationMeta
    levels: dict[str, int] = Field(default_factory=dict)



# WebSocket Events


class WsEventEnvelope(BaseModel):
    event_id: str
    event_type: str
    domain: str
    source: str
    timestamp: str
    sequence: int
    payload: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    node_id: str | None = None

class WsSubscribeRequest(BaseModel):
    """Client → Server subscription request."""
    action: str = Field(..., pattern=r"^(subscribe|unsubscribe)$")
    patterns: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    since_sequence: int = 0



# Helper: generate IDs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"

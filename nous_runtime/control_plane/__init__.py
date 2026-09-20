# -*- coding: utf-8 -*-
"""
Nous Desktop Control Plane — unified v1 API, WebSocket, auth, and sidecar lifecycle.

This module is the single entry point for all desktop interactions.
No desktop surface has its own state — the Control Plane is the canonical source.
"""

from __future__ import annotations

from nous_runtime.control_plane.schemas import (
    # Envelope
    ApiResponse,
    ApiError,
    ErrorCode,
    # Pagination
    PaginationParams,
    PaginationMeta,
    # Runtime
    RuntimeStatusResponse,
    RuntimeHealthResponse,
    RuntimeCapabilitiesResponse,
    # Node
    NodeResponse,
    NodeListResponse,
    NodeEnableRequest,
    NodeTestRequest,
    # Model
    ModelResponse,
    ModelListResponse,
    ModelTestRequest,
    # Provider
    ProviderResponse,
    ProviderListResponse,
    ProviderCreateRequest,
    ProviderUpdateRequest,
    ProviderTestRequest,
    # Task
    TaskResponse,
    TaskListResponse,
    TaskCreateRequest,
    TaskAnalyzeRequest,
    TaskPlanRequest,
    TaskApproveRequest,
    TaskEventResponse,
    TaskArtifactResponse,
    TaskReportResponse,
    # Conversation
    ConversationResponse,
    ConversationListResponse,
    ConversationCreateRequest,
    MessageCreateRequest,
    # Inspector
    InspectorSnapshotResponse,
    # Decision
    DecisionResponse,
    DecisionListResponse,
    # Log
    LogEntryResponse,
    LogListResponse,
    # WebSocket
    WsEventEnvelope,
    WsSubscribeRequest,
)

__all__ = [
    "ApiResponse",
    "ApiError",
    "ErrorCode",
    "PaginationParams",
    "PaginationMeta",
    "RuntimeStatusResponse",
    "RuntimeHealthResponse",
    "RuntimeCapabilitiesResponse",
    "NodeResponse",
    "NodeListResponse",
    "NodeEnableRequest",
    "NodeTestRequest",
    "ModelResponse",
    "ModelListResponse",
    "ModelTestRequest",
    "ProviderResponse",
    "ProviderListResponse",
    "ProviderCreateRequest",
    "ProviderUpdateRequest",
    "ProviderTestRequest",
    "TaskResponse",
    "TaskListResponse",
    "TaskCreateRequest",
    "TaskAnalyzeRequest",
    "TaskPlanRequest",
    "TaskApproveRequest",
    "TaskEventResponse",
    "TaskArtifactResponse",
    "TaskReportResponse",
    "ConversationResponse",
    "ConversationListResponse",
    "ConversationCreateRequest",
    "MessageCreateRequest",
    "InspectorSnapshotResponse",
    "DecisionResponse",
    "DecisionListResponse",
    "LogEntryResponse",
    "LogListResponse",
    "WsEventEnvelope",
    "WsSubscribeRequest",
]

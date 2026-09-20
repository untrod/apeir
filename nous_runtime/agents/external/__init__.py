# -*- coding: utf-8 -*-
"""
Vendor-neutral external agent execution contract.

Public symbols:
    AgentDescriptor
    AgentCapability
    AgentRunRequest
    AgentRunContext
    AgentRunResult
    AgentArtifact
    AgentCommandProposal
    AgentProcessState
    AgentResourceUsage
    AgentApprovalPolicy
"""

from nous_runtime.agents.external.models import (
    AgentDescriptor,
    AgentCapability,
    AgentRunRequest,
    AgentRunContext,
    AgentRunResult,
    AgentArtifact,
    AgentCommandProposal,
    AgentProcessState,
    AgentResourceUsage,
    ApprovalPolicy,
    AgentApprovalRecord,
)

__all__ = [
    "AgentDescriptor",
    "AgentCapability",
    "AgentRunRequest",
    "AgentRunContext",
    "AgentRunResult",
    "AgentArtifact",
    "AgentCommandProposal",
    "AgentProcessState",
    "AgentResourceUsage",
    "ApprovalPolicy",
    "AgentApprovalRecord",
]

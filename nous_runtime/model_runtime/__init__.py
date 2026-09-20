"""Nous Unified Model Runtime public API."""

from nous_runtime.model_runtime.adapters import (
    AdapterProbe,
    LegacyProviderAdapter,
    LlamaCppServerAdapter,
    LocalImportedModelAdapter,
    MockModelAdapter,
    ModelAdapterRegistry,
    ModelBackendAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    VLLMAdapter,
)
from nous_runtime.model_runtime.bridges import (
    GatewayChatHandler,
    GatewayPlanningService,
    GatewayReviewHandler,
    GatewayVerificationHandler,
)
from nous_runtime.model_runtime.capability_graph import (
    ModelCapabilityGraph,
    ModelCapabilityPlan,
    ModelRoleAssignment,
    ModelRoleRequirement,
)
from nous_runtime.model_runtime.evaluation import (
    ModelEvaluation,
    ModelEvaluationStore,
    ModelEvaluationSummary,
)
from nous_runtime.model_runtime.errors import (
    ModelAdapterError,
    ModelInvocationError,
    ModelProviderResponseError,
    ModelRegistryError,
    ModelResolutionError,
    ModelResourceError,
    ModelRoutingError,
    ModelRuntimeError,
)
from nous_runtime.model_runtime.facade import (
    GatewayBudget,
    GatewayExecutionContext,
    GatewayFallbackPolicy,
    GatewayOperation,
    GatewayRequest,
    GatewayResponse,
    GatewayTraceContext,
    GatewayVerificationRequirements,
    ModelGatewayFacade,
    get_gateway_facade,
)
from nous_runtime.model_runtime.factory import (
    ModelGatewayService,
    build_gateway_from_providers,
    gateway_service,
)
from nous_runtime.model_runtime.gateway import (
    ModelGateway,
    ParallelInvocationPolicy,
    ParallelInvocationResult,
)
from nous_runtime.model_runtime.inspector import (
    ModelRuntimeSnapshot,
    capture_model_runtime,
)
from nous_runtime.model_runtime.integration import (
    GatewayAgentModelHandler,
    ModelRoleBinding,
    ModelRoleBindings,
    model_request_from_task,
)
from nous_runtime.model_runtime.models import (
    CapabilityLevel,
    CapabilityResolution,
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelLifecycleState,
    ModelModality,
    ModelPackage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PrivacyClass,
    RejectedModel,
    ResourceRequirements,
    RouteDecision,
    RoutingMode,
)
from nous_runtime.model_runtime.registry import (
    ModelRecord,
    ModelRuntimeRegistry,
    descriptor_from_profile,
)
from nous_runtime.model_runtime.resolver import (
    HardwareBudget,
    ModelCapabilityResolver,
    detect_hardware_budget,
)
from nous_runtime.model_runtime.resources import (
    ModelLease,
    ModelResourceScheduler,
)
from nous_runtime.model_runtime.router import ModelRouter, RoutingWeights
from nous_runtime.model_runtime.scheduling import (
    CostScheduler,
    HardwareScheduler,
    HardwareSnapshot,
    ResourceSchedulingDecision,
    detect_hardware_snapshot,
)

__all__ = [
    "AdapterProbe",
    "CapabilityLevel",
    "CapabilityResolution",
    "CostScheduler",
    "GatewayAgentModelHandler",
    "GatewayBudget",
    "GatewayChatHandler",
    "GatewayExecutionContext",
    "GatewayFallbackPolicy",
    "GatewayOperation",
    "GatewayPlanningService",
    "GatewayRequest",
    "GatewayResponse",
    "GatewayReviewHandler",
    "GatewayTraceContext",
    "GatewayVerificationHandler",
    "GatewayVerificationRequirements",
    "HardwareBudget",
    "HardwareScheduler",
    "HardwareSnapshot",
    "LegacyProviderAdapter",
    "LlamaCppServerAdapter",
    "LocalImportedModelAdapter",
    "MockModelAdapter",
    "ModelAdapterError",
    "ModelAdapterRegistry",
    "ModelBackendAdapter",
    "ModelCapabilityGraph",
    "ModelCapabilityPlan",
    "ModelCapabilityResolver",
    "ModelCenterModel",
    "ModelCenterService",
    "ModelDescriptor",
    "ModelEndpointType",
    "ModelEvaluation",
    "ModelEvaluationStore",
    "ModelEvaluationSummary",
    "ModelGateway",
    "ModelGatewayFacade",
    "ModelGatewayService",
    "ModelInstance",
    "ModelInstanceState",
    "ModelInvocationError",
    "ModelProviderResponseError",
    "ModelLease",
    "ModelLifecycleState",
    "ModelModality",
    "ModelPackage",
    "ModelRecord",
    "ModelRegistryError",
    "ModelRequest",
    "ModelResolutionError",
    "ModelResourceError",
    "ModelResourceScheduler",
    "ModelResponse",
    "ModelRole",
    "ModelRoleAssignment",
    "ModelRoleBinding",
    "ModelRoleBindings",
    "ModelRoleRequirement",
    "ModelRouter",
    "ModelRoutingError",
    "ModelRuntimeError",
    "ModelRuntimeRegistry",
    "ModelRuntimeSnapshot",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "ParallelInvocationPolicy",
    "ParallelInvocationResult",
    "PrivacyClass",
    "RejectedModel",
    "ResourceRequirements",
    "ResourceSchedulingDecision",
    "RouteDecision",
    "RoutingMode",
    "RoutingWeights",
    "VLLMAdapter",
    "build_gateway_from_providers",
    "capture_model_runtime",
    "descriptor_from_profile",
    "detect_hardware_budget",
    "detect_hardware_snapshot",
    "gateway_service",
    "get_gateway_facade",
    "model_request_from_task",
]


def __getattr__(name: str):
    """Load Model Center lazily to keep distribution imports acyclic.

    ``model_distribution.catalog`` depends on the model Runtime's contracts.
    Importing Model Center eagerly from this package would immediately import
    that catalog again, making the public API depend on whichever module was
    imported first. Lazy loading preserves the existing public symbols while
    making standalone imports deterministic.
    """
    if name in {"ModelCenterModel", "ModelCenterService"}:
        from nous_runtime.model_runtime.center import (
            ModelCenterModel,
            ModelCenterService,
        )

        return {
            "ModelCenterModel": ModelCenterModel,
            "ModelCenterService": ModelCenterService,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

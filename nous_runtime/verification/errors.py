"""Verification and repair runtime errors."""

from nous_runtime.core.errors import NousError


class VerificationRuntimeError(NousError):
    error_code = "verification_runtime_error"


class VerificationConfigurationError(VerificationRuntimeError):
    error_code = "verification_configuration_error"


class HumanApprovalError(VerificationRuntimeError):
    error_code = "human_approval_error"


__all__ = [
    "HumanApprovalError",
    "VerificationConfigurationError",
    "VerificationRuntimeError",
]

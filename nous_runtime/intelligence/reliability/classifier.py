"""Deterministic failure classifier. No LLM required.

Maps provider error codes, HTTP statuses, exception types, and timeout phases
to FailureCategory with provider/model attribution and retryability.
"""

from __future__ import annotations

from typing import Any

from nous_runtime.intelligence.reliability.models import (
    NON_RETRYABLE_CATEGORIES,
    FailureCategory,
    FailureSignal,
    snapshot_hash,
)


def classify_failure(
    *,
    http_status: int | None = None,
    provider_error_code: str = "",
    exception_type: str = "",
    timeout_phase: str = "",
    response_validation_result: bool | None = None,
    operation_type: str = "",
    retry_header: str = "",
    provider_id: str = "",
    model_id: str = "",
    capability_id: str = "",
    raw_error: str = "",
) -> FailureSignal:
    """Classify a failure into a FailureSignal with category, attribution, and retryability.

    Deterministic. No LLM. Conservative defaults for unknown failures.
    """
    category = FailureCategory.UNKNOWN
    provider_attributable = True
    model_attributable = False
    evidence: dict[str, Any] = {}

    # HTTP status based
    if http_status is not None:
        evidence["http_status"] = http_status
        if http_status in (401,):
            category = FailureCategory.AUTHENTICATION
            provider_attributable = True
        elif http_status in (402,):
            category = FailureCategory.BUDGET_EXCEEDED
            provider_attributable = True
        elif http_status in (403,):
            category = FailureCategory.AUTHORIZATION
            provider_attributable = True
        elif http_status in (429,):
            category = FailureCategory.RATE_LIMIT
            provider_attributable = True
        elif http_status in (408,):
            category = FailureCategory.TIMEOUT
            provider_attributable = True
        elif http_status in (500, 502, 503, 504):
            category = FailureCategory.SERVER_ERROR
            provider_attributable = True
        elif http_status in (400,):
            category = FailureCategory.USER_INPUT
            provider_attributable = False
        elif http_status in (404,):
            category = FailureCategory.CAPABILITY_UNSUPPORTED
            model_attributable = True
        elif http_status in (422,):
            category = FailureCategory.OUTPUT_VALIDATION
            model_attributable = True

    # timeout
    if timeout_phase:
        evidence["timeout_phase"] = timeout_phase
        category = FailureCategory.TIMEOUT
        provider_attributable = True

    # provider error code
    if provider_error_code:
        evidence["provider_error_code"] = provider_error_code
        code_lower = provider_error_code.lower()
        if any(
            marker in code_lower
            for marker in ("balance", "billing", "budget", "credit", "payment")
        ):
            category = FailureCategory.BUDGET_EXCEEDED
        elif "auth" in code_lower or "unauthorized" in code_lower or "key" in code_lower:
            category = FailureCategory.AUTHENTICATION
        elif "rate" in code_lower or "quota" in code_lower or "limit" in code_lower:
            category = FailureCategory.RATE_LIMIT
        elif "timeout" in code_lower:
            category = FailureCategory.TIMEOUT
        elif "server" in code_lower or "internal" in code_lower:
            category = FailureCategory.SERVER_ERROR

    # exception type
    if exception_type:
        evidence["exception_type"] = exception_type
        ex_lower = exception_type.lower()
        if "timeout" in ex_lower:
            if category == FailureCategory.UNKNOWN:
                category = FailureCategory.TIMEOUT
        elif "connection" in ex_lower or "dns" in ex_lower or "socket" in ex_lower:
            if category == FailureCategory.UNKNOWN:
                category = FailureCategory.CONNECTION
        elif "value" in ex_lower or "type" in ex_lower or "key" in ex_lower:
            if category == FailureCategory.UNKNOWN:
                category = FailureCategory.USER_INPUT
                provider_attributable = False

    # validation
    if response_validation_result is False:
        evidence["validation_failed"] = True
        if category == FailureCategory.UNKNOWN:
            category = FailureCategory.OUTPUT_VALIDATION
            model_attributable = True

    # operation type
    if operation_type == "cancellation":
        category = FailureCategory.CANCELLED
        provider_attributable = False

    # retryable
    retryable = category not in NON_RETRYABLE_CATEGORIES

    # Retry-After header
    if retry_header:
        evidence["retry_after"] = retry_header

    return FailureSignal(
        signal_id=snapshot_hash({
            "category": category.value,
            "provider": provider_id,
            "model": model_id,
            "status": http_status,
            "error_code": provider_error_code,
        }),
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        category=category,
        provider_attributable=provider_attributable,
        model_attributable=model_attributable,
        retryable=retryable,
        circuit_relevant=category not in (FailureCategory.USER_INPUT, FailureCategory.CANCELLED, FailureCategory.POLICY_REJECTION),
        confidence=0.9 if http_status is not None else 0.6,
        explanation=_build_explanation(category, http_status, provider_error_code, exception_type, raw_error),
        evidence=evidence,
    )


def _build_explanation(
    category: FailureCategory,
    http_status: int | None,
    provider_error_code: str,
    exception_type: str,
    raw_error: str,
) -> str:
    parts = [f"Classified as {category.value}"]
    if http_status:
        parts.append(f"HTTP {http_status}")
    if provider_error_code:
        parts.append(f"code={provider_error_code}")
    if exception_type:
        parts.append(f"exception={exception_type}")
    if raw_error:
        # Sanitize — truncate to 200 chars
        sanitized = str(raw_error)[:200]
        parts.append(sanitized)
    return "; ".join(parts)

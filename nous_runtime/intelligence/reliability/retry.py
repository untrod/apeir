"""Bounded retry control with exponential backoff, jitter, Retry-After, and budget enforcement.

Never retries: auth, authorization, user input, policy, unsupported, budget, cancellation.
Never retries non-idempotent side effects without idempotency key.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from nous_runtime.intelligence.reliability.models import (
    DEFAULT_RETRY_POLICY,
    NON_RETRYABLE_CATEGORIES,
    FailureCategory,
    FailureSignal,
    RetryAttempt,
    RetryPolicy,
    snapshot_hash,
)


@dataclass
class RetryBudget:
    max_attempts: int = 3
    max_cumulative_delay_ms: float = 60000.0
    max_additional_cost: float = 0.0
    max_additional_tokens: int = 0

    spent_attempts: int = 0
    spent_delay_ms: float = 0.0
    spent_cost: float = 0.0
    spent_tokens: int = 0

    @property
    def exhausted(self) -> bool:
        if self.spent_attempts >= self.max_attempts:
            return True
        if self.spent_delay_ms >= self.max_cumulative_delay_ms:
            return True
        if self.max_additional_cost > 0 and self.spent_cost >= self.max_additional_cost:
            return True
        if self.max_additional_tokens > 0 and self.spent_tokens >= self.max_additional_tokens:
            return True
        return False


class RetryController:
    """Controls bounded retry execution with backoff and safety checks."""

    def __init__(
        self,
        policy: RetryPolicy | None = None,
        *,
        _rng: random.Random | None = None,
        _clock: Any = None,
    ) -> None:
        self.policy = policy or DEFAULT_RETRY_POLICY
        self._rng = _rng or random.Random()
        self._clock = _clock or time

    def should_retry(
        self,
        signal: FailureSignal,
        budget: RetryBudget,
        *,
        is_idempotent: bool = False,
        has_idempotency_key: bool = False,
    ) -> bool:
        """Determine whether a retry should be attempted."""
        if budget.exhausted:
            return False
        if signal.category in NON_RETRYABLE_CATEGORIES:
            return False
        if self.policy.allowed_categories and signal.category not in self.policy.allowed_categories:
            return False
        if not signal.retryable:
            return False
        # Non-idempotent side effects require explicit idempotency key
        if not is_idempotent and not has_idempotency_key:
            # Safe to retry if the request likely never reached the server or wasn't processed
            if signal.category not in (FailureCategory.TIMEOUT, FailureCategory.CONNECTION, FailureCategory.SERVER_ERROR, FailureCategory.RATE_LIMIT):
                return False
        return True

    def compute_delay(
        self,
        attempt_number: int,
        *,
        retry_after_seconds: float | None = None,
    ) -> float:
        """Compute backoff delay for the next retry attempt.

        Uses exponential backoff with bounded jitter.
        Respects Retry-After header if present.
        """
        if retry_after_seconds is not None and self.policy.respect_retry_after:
            return retry_after_seconds

        base = self.policy.base_backoff_ms * (self.policy.backoff_multiplier ** (attempt_number - 1))
        delay_ms = min(base, self.policy.max_backoff_ms)

        # Bounded jitter: ±jitter_ratio
        jitter_range = delay_ms * self.policy.jitter_ratio
        jitter = self._rng.uniform(-jitter_range, jitter_range)
        delay_ms = max(0.0, delay_ms + jitter)

        return delay_ms / 1000.0  # convert to seconds

    def execute_with_retry(
        self,
        fn: Callable[[], Any],
        *,
        provider_id: str = "",
        model_id: str = "",
        capability_id: str = "",
        is_idempotent: bool = False,
        has_idempotency_key: bool = False,
        budget: RetryBudget | None = None,
        on_attempt: Callable[[RetryAttempt], None] | None = None,
    ) -> tuple[Any, list[RetryAttempt]]:
        """Execute a function with retry logic.

        Returns (result, attempts). The result is the raw return from fn().
        On failure, the last failure signal is in attempts[-1].failure.
        """
        if budget is None:
            budget = RetryBudget(
                max_attempts=self.policy.max_attempts,
                max_cumulative_delay_ms=self.policy.max_cumulative_delay_ms,
                max_additional_cost=self.policy.max_additional_cost,
                max_additional_tokens=self.policy.max_additional_tokens,
            )

        attempts: list[RetryAttempt] = []
        last_result = None

        for attempt_num in range(1, self.policy.max_attempts + 1):
            if budget.exhausted:
                break

            try:
                result = fn()
            except Exception as e:
                from nous_runtime.intelligence.reliability.classifier import classify_failure
                signal = classify_failure(
                    exception_type=type(e).__name__,
                    provider_id=provider_id,
                    model_id=model_id,
                    capability_id=capability_id,
                    raw_error=str(e),
                )
            else:
                # Check if result indicates failure
                if isinstance(result, dict) and not result.get("ok", True):
                    from nous_runtime.intelligence.reliability.classifier import classify_failure
                    signal = classify_failure(
                        provider_error_code=result.get("error", ""),
                        provider_id=provider_id,
                        model_id=model_id,
                        capability_id=capability_id,
                        raw_error=result.get("error", ""),
                    )
                else:
                    # Success
                    attempt = RetryAttempt(
                        attempt_id=snapshot_hash({"exec": provider_id, "attempt": attempt_num, "ts": datetime.now(timezone.utc).isoformat()}),
                        policy_id=self.policy.policy_id,
                        attempt_number=attempt_num,
                        success=True,
                    )
                    attempts.append(attempt)
                    if on_attempt:
                        on_attempt(attempt)
                    return result, attempts

            # Failure path
            delay_ms = self.compute_delay(attempt_num) * 1000
            attempt = RetryAttempt(
                attempt_id=snapshot_hash({"exec": provider_id, "attempt": attempt_num, "ts": datetime.now(timezone.utc).isoformat()}),
                policy_id=self.policy.policy_id,
                attempt_number=attempt_num,
                delay_ms=delay_ms,
                success=False,
                failure=signal,
            )
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)

            budget.spent_attempts += 1
            budget.spent_delay_ms += delay_ms
            last_result = {"ok": False, "error": signal.explanation}

            if not self.should_retry(signal, budget, is_idempotent=is_idempotent, has_idempotency_key=has_idempotency_key):
                break

            # Wait before retry
            if delay_ms > 0:
                self._clock.sleep(delay_ms / 1000.0)

        return last_result, attempts

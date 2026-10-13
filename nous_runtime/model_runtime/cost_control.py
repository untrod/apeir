"""Provider-neutral request budgets and durable usage receipts.

This module owns product cost policy. It does not mint Kernel permits and it
never stores credential values; API-key accounting uses a hash of the stable
credential reference supplied by configuration.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

from nous_runtime.model_runtime.errors import ModelRuntimeError
from nous_runtime.core.redaction import redact_sensitive_data, redact_sensitive_text

if TYPE_CHECKING:
    from nous_runtime.model_runtime.models import ModelRequest, ModelResponse


class CostLimitExceeded(ModelRuntimeError):
    """A model request or response could not satisfy accounting limits."""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _positive_int(name: str, value: Any, default: int) -> int:
    parsed = _token_count(name, value)
    if parsed is None or parsed <= 0:
        raise CostLimitExceeded(f"{name} must be positive")
    return parsed


def _token_count(name: str, value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError
        if isinstance(value, float) and (
            not math.isfinite(value) or not value.is_integer()
        ):
            raise ValueError
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise CostLimitExceeded(f"{name} must be a non-negative integer") from None
    if parsed < 0:
        raise CostLimitExceeded(f"{name} must be a non-negative integer")
    return parsed


def _money(name: str, value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        raise CostLimitExceeded(f"{name} must be finite and non-negative") from None
    if not math.isfinite(parsed) or parsed < 0:
        raise CostLimitExceeded(f"{name} must be finite and non-negative")
    return parsed


_COUNTERS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_miss_input_tokens",
    "reasoning_tokens",
    "total_tokens",
    "cache_creation_input_tokens",
)


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_miss_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    counter_measurements: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "Usage":
        if value is not None and not isinstance(value, Mapping):
            raise CostLimitExceeded("provider usage must be a mapping")
        raw = dict(value or {})
        labels = raw.get("counter_measurements")
        if labels is not None and not isinstance(labels, Mapping):
            raise CostLimitExceeded("provider usage measurements must be a mapping")
        measurements: dict[str, str] = {}

        def read(name: str, *paths: tuple[str, ...]) -> int | None:
            for path in paths:
                current: Any = raw
                for part in path:
                    if current is None:
                        break
                    if not isinstance(current, Mapping):
                        raise CostLimitExceeded(
                            "provider token details must be a mapping"
                        )
                    if part not in current:
                        current = None
                        break
                    current = current[part]
                else:
                    parsed = _token_count(name, current)
                    label = str((labels or {}).get(name) or "reported")
                    if parsed is None or label == "unknown":
                        measurements[name] = "unknown"
                        return None
                    if label not in {"reported", "derived", "estimated"}:
                        raise CostLimitExceeded("provider usage measurement is unknown")
                    measurements[name] = label
                    return parsed
            measurements[name] = "unknown"
            return None

        input_tokens = read("input_tokens", ("input_tokens",), ("prompt_tokens",))
        output_tokens = read(
            "output_tokens", ("output_tokens",), ("completion_tokens",)
        )
        cached = read(
            "cached_input_tokens",
            ("cached_input_tokens",),
            ("cache_read_input_tokens",),
            ("prompt_cache_hit_tokens",),
            ("prompt_tokens_details", "cached_tokens"),
        )
        cache_write = read(
            "cache_creation_input_tokens", ("cache_creation_input_tokens",)
        )
        # The raw Anthropic input counter excludes both cache classes. The
        # normalized contract includes them and must remain idempotent.
        if labels is None and (
            "cache_read_input_tokens" in raw
            or (
                "cache_creation_input_tokens" in raw
                and "cached_input_tokens" not in raw
            )
        ):
            if (
                input_tokens is not None
                and cached is not None
                and cache_write is not None
            ):
                input_tokens += cached + cache_write
                measurements["input_tokens"] = "derived"
            else:
                input_tokens = None
                measurements["input_tokens"] = "unknown"
        cache_miss = read(
            "cache_miss_input_tokens",
            ("cache_miss_input_tokens",),
            ("prompt_cache_miss_tokens",),
        )
        if cache_miss is None and input_tokens is not None and cached is not None:
            cache_miss = input_tokens - cached
            measurements["cache_miss_input_tokens"] = (
                "estimated"
                if "estimated"
                in (measurements["input_tokens"], measurements["cached_input_tokens"])
                else "derived"
            )
        reasoning = read(
            "reasoning_tokens",
            ("reasoning_tokens",),
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
        )
        total = read("total_tokens", ("total_tokens",), ("tokens",))
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
            measurements["total_tokens"] = (
                "estimated"
                if "estimated"
                in (measurements["input_tokens"], measurements["output_tokens"])
                else "derived"
            )
        if (
            (input_tokens is not None and cached is not None and cached > input_tokens)
            or (
                input_tokens is not None
                and cached is not None
                and cache_miss is not None
                and cached + cache_miss != input_tokens
            )
            or (
                input_tokens is not None
                and cached is not None
                and cache_write is not None
                and cached + cache_write > input_tokens
            )
            or (
                output_tokens is not None
                and reasoning is not None
                and reasoning > output_tokens
            )
            or (
                total is not None
                and input_tokens is not None
                and output_tokens is not None
                and total < input_tokens + output_tokens
            )
        ):
            raise CostLimitExceeded("provider token counters are contradictory")
        return cls(
            input_tokens,
            output_tokens,
            cached,
            cache_miss,
            reasoning,
            total,
            cache_write,
            measurements,
        )

    def to_dict(self) -> dict[str, Any]:
        values = {name: getattr(self, name) for name in _COUNTERS}
        return {
            **values,
            "counter_measurements": {
                name: self.counter_measurements.get(
                    name, "unknown" if value is None else "estimated"
                )
                for name, value in values.items()
            },
        }


@dataclass(frozen=True)
class Pricing:
    input_per_million_usd: float | None = None
    output_per_million_usd: float | None = None
    cached_input_per_million_usd: float | None = None
    cache_creation_input_per_million_usd: float | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _money(name, getattr(self, name)))

    def estimate(self, usage: Usage) -> float | None:
        if usage.input_tokens is None or usage.output_tokens is None:
            return None
        if not any(
            getattr(self, name) is not None for name in self.__dataclass_fields__
        ):
            return None
        cached = usage.cached_input_tokens or 0
        created = usage.cache_creation_input_tokens or 0
        uncached = usage.input_tokens - cached - created
        charges = (
            (uncached, self.input_per_million_usd),
            (cached, self.cached_input_per_million_usd),
            (created, self.cache_creation_input_per_million_usd),
            (usage.output_tokens, self.output_per_million_usd),
        )
        if uncached < 0 or any(tokens and rate is None for tokens, rate in charges):
            return None
        value = sum(tokens * (rate or 0.0) for tokens, rate in charges) / 1_000_000
        return round(_money("model price estimate", value), 12)

    def has_unpriced_usage(self, usage: Usage) -> bool:
        cached = usage.cached_input_tokens or 0
        created = usage.cache_creation_input_tokens or 0
        uncached = (
            usage.input_tokens - cached - created
            if usage.input_tokens is not None
            else None
        )
        return any(
            tokens is not None and tokens > 0 and rate is None
            for tokens, rate in (
                (uncached, self.input_per_million_usd),
                (cached, self.cached_input_per_million_usd),
                (created, self.cache_creation_input_per_million_usd),
                (usage.output_tokens, self.output_per_million_usd),
            )
        )


class PricingCatalog:
    def __init__(self, entries: Mapping[str, Pricing] | None = None) -> None:
        if entries is not None and (
            not isinstance(entries, Mapping)
            or any(not isinstance(rate, Pricing) for rate in entries.values())
        ):
            raise CostLimitExceeded("pricing catalog requires validated price entries")
        self._entries = dict(entries or {})
        self._source = "host" if entries is not None else "unconfigured"
        self._configured = self._loaded = entries is not None

    @classmethod
    def from_file(cls, path: Path | None) -> "PricingCatalog":
        if path is None:
            return cls()
        if not path.exists():
            catalog = cls()
            catalog._source, catalog._configured = "file", True
            return catalog
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise CostLimitExceeded(
                "pricing configuration is unavailable or invalid"
            ) from None
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("models", {}), Mapping
        ):
            raise CostLimitExceeded(
                "pricing configuration must declare a model mapping"
            )
        entries: dict[str, Pricing] = {}
        for key, value in dict(payload.get("models") or {}).items():
            if not isinstance(value, Mapping):
                raise CostLimitExceeded("model pricing entry must be a mapping")
            entries[str(key)] = Pricing(
                value.get("input_per_million_usd"),
                value.get("output_per_million_usd"),
                value.get("cached_input_per_million_usd"),
                value.get("cache_creation_input_per_million_usd"),
            )
        catalog = cls(entries)
        catalog._source = "file"
        return catalog

    def get(self, provider_id: str, model_id: str) -> Pricing | None:
        return self._entries.get(f"{provider_id}/{model_id}") or self._entries.get(
            model_id
        )

    def readiness(self) -> dict[str, Any]:
        priced = sum(
            rate.input_per_million_usd is not None
            and rate.output_per_million_usd is not None
            for rate in self._entries.values()
        )
        return {
            "configured": self._configured,
            "loaded": self._loaded,
            "status": "unconfigured"
            if not self._configured
            else "missing"
            if not self._loaded
            else "configured"
            if priced
            else "unpriced",
            "model_entries": len(self._entries),
            "priced_models": priced,
            "source": self._source,
            "environment_variable": "APEIR_MODEL_PRICING_FILE",
        }


@dataclass(frozen=True)
class CostPolicy:
    max_input_tokens: int = 65_536
    max_output_tokens: int = 4_096
    max_request_tokens: int = 69_632
    max_daily_tokens: int = 1_000_000
    max_daily_cost_usd: float | None = 5.0
    max_attempts: int = 3
    max_retry_tokens: int = 32_768
    max_retry_cost_usd: float | None = 1.0

    def __post_init__(self) -> None:
        for name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_request_tokens",
            "max_daily_tokens",
            "max_attempts",
            "max_retry_tokens",
        ):
            object.__setattr__(self, name, _positive_int(name, getattr(self, name), 1))
        for name in ("max_daily_cost_usd", "max_retry_cost_usd"):
            limit = _money(name, getattr(self, name))
            if limit is not None and limit <= 0:
                raise CostLimitExceeded(
                    "cost-policy monetary limits must be positive or disabled"
                )
            object.__setattr__(self, name, limit)

    @classmethod
    def from_environment(cls) -> "CostPolicy":
        defaults = cls()
        values = {}
        for name in cls.__dataclass_fields__:
            variable = (
                "APEIR_MAX_MODEL_ATTEMPTS"
                if name == "max_attempts"
                else f"APEIR_{name.upper()}"
            )
            value = os.environ.get(variable, str(getattr(defaults, name)))
            values[name] = (
                (None if value.strip().lower() == "none" else _money(variable, value))
                if name.endswith("_usd")
                else _positive_int(variable, value, 1)
            )
        return cls(**values)


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    request: "ModelRequest"
    provider_id: str
    model_id: str
    credential_ref_hash: str
    attempt: int
    estimated_usage: Usage
    estimated_cost_usd: float | None
    day: str = field(default_factory=_utc_day)
    execution_key: str = ""
    request_binding_sha256: str = ""
    replayed: bool = False


class CostController:
    """Authorize estimated spend, then commit normalized provider usage."""

    def __init__(
        self,
        database: Path,
        *,
        policy: CostPolicy | None = None,
        pricing: PricingCatalog | None = None,
    ) -> None:
        self.database = database
        self.policy = policy or CostPolicy()
        self.pricing = pricing or PricingCatalog()
        self._lock = threading.RLock()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_environment(cls) -> "CostController":
        state_root = Path(
            os.environ.get("APEIR_STATE_DIR") or os.environ.get("NOUS_HOME") or ".apeir"
        ).expanduser()
        pricing_path = os.environ.get("APEIR_MODEL_PRICING_FILE", "").strip()
        return cls(
            state_root / "usage.sqlite3",
            policy=CostPolicy.from_environment(),
            pricing=PricingCatalog.from_file(
                Path(pricing_path) if pricing_path else None
            ),
        )

    @staticmethod
    def estimate_input_tokens(request: "ModelRequest") -> int:
        explicit = request.metadata.get("estimated_input_tokens")
        try:
            payload = {
                "messages": [dict(item) for item in request.messages],
                "attachments": [dict(item) for item in request.attachments],
                "input": request.metadata.get("input"),
                "tools": list(request.metadata.get("tools") or ()),
                **{
                    name: request.metadata[name]
                    for name in (
                        "response_schema",
                        "response_format",
                        "tool_choice",
                        "legacy_params",
                    )
                    if name in request.metadata
                },
            }
            encoded = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            raise CostLimitExceeded("model input cannot be estimated") from None
        # This is a byte-based estimate, not provider token telemetry. A caller
        # may increase it for a tokenizer/modality, but cannot lower the floor.
        floor = max(1, math.ceil(len(encoded) / 3))
        return (
            max(floor, _positive_int("estimated_input_tokens", explicit, 1))
            if explicit is not None
            else floor
        )

    def authorize(
        self,
        request: "ModelRequest",
        *,
        provider_id: str,
        model_id: str,
        credential_ref: str = "",
        attempt: int = 1,
        context_window: int | None = None,
        output_window: int | None = None,
        kernel_binding: Mapping[str, Any] | None = None,
    ) -> Reservation:
        policy = self.policy
        identity = {
            "request_id": request.request_id,
            "task_id": request.task_id,
            "provider_id": provider_id,
            "model_id": model_id,
        }
        if redact_sensitive_data(identity) != identity:
            raise CostLimitExceeded(
                "model accounting identity contains sensitive material"
            )
        credential_hash = hashlib.sha256(
            (credential_ref or f"provider:{provider_id}").encode("utf-8")
        ).hexdigest()
        execution_key = (
            f"nki:{request.request_id}" if kernel_binding is not None else ""
        )
        binding_sha256 = ""
        if execution_key:
            try:
                binding_sha256 = hashlib.sha256(
                    json.dumps(
                        {
                            "request": request.to_dict(),
                            "provider_id": provider_id,
                            "model_id": model_id,
                            "credential_ref_hash": credential_hash,
                            "kernel_binding": dict(kernel_binding),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
            except (TypeError, ValueError, OverflowError):
                raise CostLimitExceeded("model execution cannot be bound") from None
            with self._lock, self._session(immediate=True) as connection:
                original = self._original_execution(
                    connection, request, execution_key, binding_sha256
                )
                if original is not None:
                    return original
        attempt = _positive_int("model retry attempt", attempt, 1)
        if attempt > policy.max_attempts:
            raise CostLimitExceeded("model retry attempt budget exceeded")
        input_tokens = self.estimate_input_tokens(request)
        output_limits = [policy.max_output_tokens]
        for name in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
            if name in request.metadata:
                output_limits.append(_positive_int(name, request.metadata[name], 1))
        for name, limit in (
            ("context_window", context_window),
            ("output_window", output_window),
        ):
            # Existing descriptors use zero for an unspecified model window.
            parsed = _token_count(name, limit)
            if parsed:
                available = (
                    parsed - input_tokens if name == "context_window" else parsed
                )
                if available <= 0:
                    raise CostLimitExceeded("model input exceeds its context window")
                output_limits.append(available)
        if input_tokens > policy.max_input_tokens:
            raise CostLimitExceeded("model input token limit exceeded")
        output_tokens = min(output_limits)
        estimate = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=0,
            cache_creation_input_tokens=0,
            total_tokens=input_tokens + output_tokens,
        )
        if estimate.total_tokens > policy.max_request_tokens:
            raise CostLimitExceeded("model request token budget exceeded")
        rate = self.pricing.get(provider_id, model_id)
        estimated_cost = rate.estimate(estimate) if rate else None
        request_cost_limit = _money("model request cost limit", request.max_cost_usd)
        monetary_enforced = (
            request_cost_limit is not None
            or policy.max_daily_cost_usd is not None
            or (attempt > 1 and policy.max_retry_cost_usd is not None)
        )
        if monetary_enforced and estimated_cost is None:
            raise CostLimitExceeded(
                "known model pricing is required for the enforced monetary budget; "
                "configure APEIR_MODEL_PRICING_FILE or explicitly select token-only policy"
            )
        if (
            request_cost_limit is not None
            and estimated_cost is not None
            and estimated_cost > request_cost_limit
        ):
            raise CostLimitExceeded("model request cost budget exceeded")
        reservation_id = f"usage-reservation-{uuid.uuid4().hex}"
        day = _utc_day()
        guarded = self._guard_request(request, output_tokens)
        reservation = Reservation(
            reservation_id,
            guarded,
            provider_id,
            model_id,
            credential_hash,
            attempt,
            estimate,
            estimated_cost,
            day,
            execution_key,
            binding_sha256,
        )
        with self._lock, self._session(immediate=True) as connection:
            if execution_key:
                original = self._original_execution(
                    connection, request, execution_key, binding_sha256
                )
                if original is not None:
                    return original
            blocked = connection.execute(
                "SELECT reason FROM provider_blocks WHERE day=? AND scope_hash=?",
                (day, credential_hash),
            ).fetchone()
            if blocked:
                raise CostLimitExceeded("provider spending is blocked")
            if (
                policy.max_daily_cost_usd is not None
                and self._unbounded_cost(connection, day)
            ) or (
                attempt > 1
                and policy.max_retry_cost_usd is not None
                and self._unbounded_cost(connection, day, retry_only=True)
            ):
                raise CostLimitExceeded(
                    "previous model billing is unknown without a priced reservation"
                )
            daily_tokens, daily_cost, retry_tokens, retry_cost = self._budget_totals(
                connection, day
            )
            if int(daily_tokens) + estimate.total_tokens > policy.max_daily_tokens:
                raise CostLimitExceeded("daily model token budget exceeded")
            if (
                policy.max_daily_cost_usd is not None
                and float(daily_cost) + (estimated_cost or 0)
                > policy.max_daily_cost_usd
            ):
                raise CostLimitExceeded("daily model cost budget exceeded")
            if (
                attempt > 1
                and int(retry_tokens) + estimate.total_tokens > policy.max_retry_tokens
            ):
                raise CostLimitExceeded("model retry token budget exceeded")
            if (
                attempt > 1
                and policy.max_retry_cost_usd is not None
                and float(retry_cost) + (estimated_cost or 0)
                > policy.max_retry_cost_usd
            ):
                raise CostLimitExceeded("model retry cost budget exceeded")
            connection.execute(
                """INSERT INTO usage_reservations
                   (reservation_id, day, request_id, task_id, provider_id, model_id,
                    credential_ref_hash, estimated_tokens, estimated_cost_usd, attempt,
                    cost_measurement, execution_key, reservation_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    reservation_id,
                    day,
                    request.request_id,
                    request.task_id,
                    provider_id,
                    model_id,
                    credential_hash,
                    estimate.total_tokens,
                    estimated_cost or 0.0,
                    attempt,
                    "estimated" if estimated_cost is not None else "unknown",
                    execution_key,
                    json.dumps(self._reservation_evidence(reservation), sort_keys=True)
                    if execution_key
                    else "",
                ),
            )
        return reservation

    @staticmethod
    def _guard_request(request: "ModelRequest", output_tokens: int) -> "ModelRequest":
        legacy_params = request.metadata.get("legacy_params") or {}
        if not isinstance(legacy_params, Mapping):
            raise CostLimitExceeded("model legacy parameters must be a mapping")
        metadata = {
            **dict(request.metadata),
            "max_tokens": output_tokens,
            "max_output_tokens": output_tokens,
        }
        if "max_completion_tokens" in metadata:
            metadata["max_completion_tokens"] = output_tokens
        if "legacy_params" in metadata:
            metadata["legacy_params"] = {
                **dict(legacy_params),
                **{
                    name: output_tokens
                    for name in (
                        "max_tokens",
                        "max_output_tokens",
                        "max_completion_tokens",
                    )
                    if name in legacy_params
                },
            }
        return replace(request, metadata=metadata)

    @staticmethod
    def _reservation_evidence(reservation: Reservation) -> dict[str, Any]:
        return {
            "reservation_id": reservation.reservation_id,
            "day": reservation.day,
            "request_id": reservation.request.request_id,
            "task_id": reservation.request.task_id,
            "provider_id": reservation.provider_id,
            "model_id": reservation.model_id,
            "credential_ref_hash": reservation.credential_ref_hash,
            "attempt": reservation.attempt,
            "estimated_usage": reservation.estimated_usage.to_dict(),
            "estimated_cost_usd": reservation.estimated_cost_usd,
            "execution_key": reservation.execution_key,
            "request_binding_sha256": reservation.request_binding_sha256,
        }

    def _original_execution(
        self,
        connection: sqlite3.Connection,
        request: "ModelRequest",
        execution_key: str,
        binding_sha256: str,
    ) -> Reservation | None:
        row = connection.execute(
            "SELECT reservation_json FROM usage_reservations WHERE execution_key=?",
            (execution_key,),
        ).fetchone()
        if row is not None:
            evidence = json.loads(row[0])
        else:
            row = connection.execute(
                "SELECT receipt_json FROM usage_receipts WHERE execution_key=?",
                (execution_key,),
            ).fetchone()
            evidence = json.loads(row[0])["reservation"] if row is not None else None
        if evidence is None:
            legacy = connection.execute(
                """SELECT EXISTS(SELECT 1 FROM usage_reservations WHERE request_id=?)
                   OR EXISTS(SELECT 1 FROM usage_receipts
                       WHERE request_id=? AND status<>'not_dispatched')""",
                (request.request_id, request.request_id),
            ).fetchone()[0]
            if legacy:
                raise CostLimitExceeded(
                    "original model attempt has no execution binding"
                )
            return None
        if evidence["request_binding_sha256"] != binding_sha256:
            raise CostLimitExceeded("original model execution bindings cannot change")
        estimate = evidence["estimated_usage"]
        usage = Usage(
            **{name: estimate[name] for name in _COUNTERS},
            counter_measurements=estimate["counter_measurements"],
        )
        return Reservation(
            evidence["reservation_id"],
            self._guard_request(request, usage.output_tokens),
            evidence["provider_id"],
            evidence["model_id"],
            evidence["credential_ref_hash"],
            evidence["attempt"],
            usage,
            evidence["estimated_cost_usd"],
            evidence["day"],
            execution_key,
            binding_sha256,
            True,
        )

    def mark_dispatched(self, reservation: Reservation) -> None:
        """Fence the first Kernel submission before an acknowledgement can be lost."""
        if not reservation.execution_key or reservation.replayed:
            raise CostLimitExceeded("only a new bound model attempt can dispatch")
        with self._lock, self._session(immediate=True) as connection:
            row = connection.execute(
                "SELECT status, reservation_json FROM usage_reservations WHERE reservation_id=?",
                (reservation.reservation_id,),
            ).fetchone()
            if (
                row is None
                or row[0] != "reserved"
                or json.loads(row[1]) != self._reservation_evidence(reservation)
            ):
                raise CostLimitExceeded(
                    "original model attempt requires reconciliation"
                )
            connection.execute(
                "UPDATE usage_reservations SET status='dispatched' WHERE reservation_id=?",
                (reservation.reservation_id,),
            )

    def commit(
        self, reservation: Reservation, response: "ModelResponse"
    ) -> tuple["ModelResponse", dict[str, Any]]:
        if response.request_id != reservation.request.request_id:
            self.fail(reservation, reason="provider response binding mismatch")
            raise CostLimitExceeded("provider response does not match its reservation")
        try:
            usage = Usage.from_mapping(response.usage)
            cost, measurement = self._response_cost(reservation, response, usage)
        except (CostLimitExceeded, TypeError, ValueError):
            self.fail(reservation, reason="invalid provider usage")
            raise CostLimitExceeded(
                "provider usage or pricing is invalid; billing remains uncertain"
            ) from None
        measured_tokens = (
            usage.total_tokens is not None
            and usage.counter_measurements.get("total_tokens")
            in {"reported", "derived"}
        )
        rate = self.pricing.get(reservation.provider_id, reservation.model_id)
        quote_invalidated = cost is None and (rate or Pricing()).has_unpriced_usage(
            usage
        )
        violations: list[str] = []
        if (
            usage.input_tokens is not None
            and usage.input_tokens > self.policy.max_input_tokens
        ):
            violations.append("provider input exceeded the authorized token limit")
        if (
            usage.output_tokens is not None
            and usage.output_tokens > reservation.estimated_usage.output_tokens
        ):
            violations.append("provider output exceeded the authorized token limit")
        if (
            usage.total_tokens is not None
            and usage.total_tokens > self.policy.max_request_tokens
        ):
            violations.append("provider usage exceeded the request token limit")
        if (
            cost is not None
            and reservation.request.max_cost_usd is not None
            and cost > reservation.request.max_cost_usd
        ):
            violations.append("provider cost exceeded the request cost limit")
        with self._lock, self._session(immediate=True) as connection:
            previous = self._find_receipt(connection, reservation.reservation_id)
            if reservation.execution_key:
                row = connection.execute(
                    "SELECT reservation_json FROM usage_reservations WHERE reservation_id=?",
                    (reservation.reservation_id,),
                ).fetchone()
                evidence = (
                    json.loads(row[0])
                    if row is not None
                    else (previous or {}).get("reservation")
                )
                if evidence != self._reservation_evidence(reservation):
                    raise CostLimitExceeded(
                        "original model reservation bindings cannot change"
                    )
            if previous is not None:
                current_usage = usage.to_dict()
                for name in _COUNTERS:
                    prior_value = previous["usage"][name]
                    prior_marker = previous["usage"]["counter_measurements"][name]
                    current_marker = current_usage["counter_measurements"][name]
                    if (
                        prior_marker in {"reported", "derived"}
                        and (
                            current_usage[name] != prior_value
                            or current_marker not in {"reported", "derived"}
                        )
                    ) or (
                        prior_marker == "estimated"
                        and current_marker not in {"reported", "derived"}
                        and (
                            current_usage[name] != prior_value
                            or current_marker != prior_marker
                        )
                    ):
                        raise CostLimitExceeded(
                            "original usage evidence cannot change or lose certainty"
                        )
                if previous["cost_measurement"] == "reported" and (
                    previous["cost_usd"] != cost or measurement != "reported"
                ):
                    raise CostLimitExceeded("original reported cost cannot change")
            if previous is not None and previous["status"] in {
                "completed",
                "policy_violation",
            }:
                if (
                    previous["usage"] != usage.to_dict()
                    or previous["cost_usd"] != cost
                    or previous["cost_measurement"] != measurement
                ):
                    raise CostLimitExceeded(
                        "completed usage receipt cannot change its original bindings"
                    )
                receipt = previous
            else:
                active = connection.execute(
                    "SELECT request_id FROM usage_reservations WHERE reservation_id=?",
                    (reservation.reservation_id,),
                ).fetchone()
                if active is None or active[0] != reservation.request.request_id:
                    raise CostLimitExceeded("model usage reservation is unavailable")
                receipt = self._receipt(
                    reservation,
                    usage,
                    cost,
                    measurement,
                    "completed"
                    if measured_tokens and cost is not None
                    else "usage_unknown",
                )
                if previous is not None:
                    receipt["receipt_id"] = previous["receipt_id"]
                    receipt["created_at"] = previous["created_at"]
                    receipt["reconciled_at"] = _utc_now()
                self._write_receipt(connection, reservation, receipt)
                if measured_tokens and cost is not None:
                    connection.execute(
                        "DELETE FROM usage_reservations WHERE reservation_id=?",
                        (reservation.reservation_id,),
                    )
                else:
                    connection.execute(
                        """UPDATE usage_reservations
                           SET estimated_tokens=?, estimated_cost_usd=?,
                               cost_measurement=CASE WHEN ? IS NOT NULL THEN 'estimated'
                                   WHEN ? THEN 'unknown' ELSE cost_measurement END,
                               status='uncertain'
                           WHERE reservation_id=?""",
                        (
                            0
                            if measured_tokens
                            else max(
                                reservation.estimated_usage.total_tokens,
                                usage.total_tokens or 0,
                            ),
                            0.0
                            if cost is not None
                            else (reservation.estimated_cost_usd or 0.0),
                            cost,
                            quote_invalidated,
                            reservation.reservation_id,
                        ),
                    )
                daily_tokens, daily_cost, retry_tokens, retry_cost = (
                    self._budget_totals(connection, reservation.day)
                )
                if daily_tokens > self.policy.max_daily_tokens:
                    violations.append("provider usage exceeded the daily token limit")
                if (
                    self.policy.max_daily_cost_usd is not None
                    and daily_cost > self.policy.max_daily_cost_usd
                ):
                    violations.append("provider usage exceeded the daily cost limit")
                if (
                    reservation.attempt > 1
                    and retry_tokens > self.policy.max_retry_tokens
                ):
                    violations.append("provider usage exceeded the retry token limit")
                if (
                    reservation.attempt > 1
                    and self.policy.max_retry_cost_usd is not None
                    and retry_cost > self.policy.max_retry_cost_usd
                ):
                    violations.append("provider usage exceeded the retry cost limit")
                if violations:
                    receipt["status"] = "policy_violation"
                    self._write_receipt(connection, reservation, receipt)
                    connection.execute(
                        """INSERT OR REPLACE INTO provider_blocks
                           (day, scope_hash, reason, created_at) VALUES (?, ?, ?, ?)""",
                        (
                            reservation.day,
                            reservation.credential_ref_hash,
                            "provider usage policy violation",
                            _utc_now(),
                        ),
                    )
        normalized = replace(
            response,
            usage=usage.to_dict(),
            cost_usd=cost if cost is not None else 0.0,
            metadata={
                **redact_sensitive_data(dict(response.metadata)),
                "cost_measurement": measurement,
                "usage_receipt": receipt,
            },
        )
        if violations or receipt["status"] == "policy_violation":
            raise CostLimitExceeded(
                "provider response violated the authorized usage budget: "
                + "; ".join(violations or ["original usage policy violation"])
            )
        return normalized, receipt

    def _response_cost(
        self, reservation: Reservation, response: "ModelResponse", usage: Usage
    ) -> tuple[float | None, str]:
        marker = response.metadata.get("cost_measurement")
        if marker not in {None, "reported", "estimated", "unknown"}:
            raise CostLimitExceeded("provider cost measurement is invalid")
        if marker == "reported" or (marker is None and response.cost_usd > 0):
            return _money("provider cost", response.cost_usd), marker or "reported"
        if any(
            usage.counter_measurements.get(name) == "estimated"
            for name in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "cache_creation_input_tokens",
            )
        ):
            return None, "unknown"
        rate = self.pricing.get(reservation.provider_id, reservation.model_id)
        estimated = rate.estimate(usage) if rate is not None else None
        return estimated, "estimated" if estimated is not None else "unknown"

    @staticmethod
    def _receipt(
        reservation: Reservation,
        usage: Usage,
        cost: float | None,
        measurement: str,
        status: str,
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": 1,
            "receipt_id": f"usage-{uuid.uuid4().hex}",
            "created_at": _utc_now(),
            "day": reservation.day,
            "reservation_id": reservation.reservation_id,
            "request_id": reservation.request.request_id,
            "task_id": reservation.request.task_id,
            "provider_id": reservation.provider_id,
            "model_id": reservation.model_id,
            "credential_ref_hash": reservation.credential_ref_hash,
            "attempt": reservation.attempt,
            "usage": usage.to_dict(),
            "cost_usd": cost,
            "cost_measurement": measurement,
            "estimated_tokens": reservation.estimated_usage.total_tokens,
            "estimated_cost_usd": reservation.estimated_cost_usd,
            "status": status,
        }
        if reservation.execution_key:
            receipt["execution_key"] = reservation.execution_key
            receipt["reservation"] = CostController._reservation_evidence(reservation)
        for name in (
            "request_id",
            "task_id",
            "provider_id",
            "model_id",
            "credential_ref_hash",
        ):
            receipt[name] = redact_sensitive_text(receipt[name])
        return receipt

    @staticmethod
    def _write_receipt(
        connection: sqlite3.Connection,
        reservation: Reservation,
        receipt: Mapping[str, Any],
    ) -> None:
        usage = receipt["usage"]
        # Original NOT NULL columns remain compatibility accounting columns.
        # The additive receipt JSON retains authoritative nulls and provenance.
        values = {
            name: receipt[name]
            for name in (
                "receipt_id",
                "created_at",
                "day",
                "request_id",
                "task_id",
                "provider_id",
                "model_id",
                "credential_ref_hash",
                "attempt",
                "status",
                "reservation_id",
                "cost_measurement",
            )
        }
        values.update(
            {
                name: usage[name] or 0
                for name in (
                    "input_tokens",
                    "output_tokens",
                    "cached_input_tokens",
                    "total_tokens",
                )
            }
        )
        if usage["counter_measurements"]["total_tokens"] == "estimated":
            values["total_tokens"] = 0
        values["cost_usd"] = receipt["cost_usd"] or 0.0
        values["execution_key"] = receipt.get("execution_key", "")
        values["receipt_json"] = json.dumps(dict(receipt), sort_keys=True)
        connection.execute(
            f"INSERT OR REPLACE INTO usage_receipts ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )

    @staticmethod
    def _find_receipt(
        connection: sqlite3.Connection, reservation_id: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT receipt_json FROM usage_receipts WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        return json.loads(row[0]) if row is not None and row[0] else None

    @staticmethod
    def _budget_totals(
        connection: sqlite3.Connection, day: str
    ) -> tuple[int, float, int, float]:
        values = connection.execute(
            """SELECT
               COALESCE((SELECT SUM(total_tokens) FROM usage_receipts WHERE day=?),0)
               + COALESCE((SELECT SUM(estimated_tokens) FROM usage_reservations WHERE day=?),0),
               COALESCE((SELECT SUM(cost_usd) FROM usage_receipts WHERE day=?),0)
               + COALESCE((SELECT SUM(estimated_cost_usd) FROM usage_reservations WHERE day=?),0),
               COALESCE((SELECT SUM(total_tokens) FROM usage_receipts WHERE day=? AND attempt>1),0)
               + COALESCE((SELECT SUM(estimated_tokens) FROM usage_reservations WHERE day=? AND attempt>1),0),
               COALESCE((SELECT SUM(cost_usd) FROM usage_receipts WHERE day=? AND attempt>1),0)
               + COALESCE((SELECT SUM(estimated_cost_usd) FROM usage_reservations WHERE day=? AND attempt>1),0)""",
            (day,) * 8,
        ).fetchone()
        return int(values[0]), float(values[1]), int(values[2]), float(values[3])

    @staticmethod
    def _unbounded_cost(
        connection: sqlite3.Connection, day: str, *, retry_only: bool = False
    ) -> bool:
        # A former token-only call or a legacy zero price cannot become known
        # spend merely because an operator enables monetary policy after restart.
        retry_filter = "AND attempt>1" if retry_only else ""
        return bool(
            connection.execute(
                f"""SELECT EXISTS(SELECT 1 FROM usage_reservations
                    WHERE day=? AND cost_measurement<>'estimated' {retry_filter})
                OR EXISTS(SELECT 1 FROM usage_receipts u
                    WHERE day=? AND cost_measurement IN ('unknown', 'legacy_unknown') {retry_filter}
                    AND NOT EXISTS(SELECT 1 FROM usage_reservations r
                        WHERE r.reservation_id=u.reservation_id AND r.cost_measurement='estimated'))""",
                (day, day),
            ).fetchone()[0]
        )

    def fail(
        self,
        reservation: Reservation,
        *,
        reason: str,
        balance_exhausted: bool = False,
        dispatched: bool = True,
    ) -> None:
        if not isinstance(dispatched, bool):
            raise CostLimitExceeded("provider dispatch state must be explicit")
        if reservation.replayed and not dispatched:
            # A read-only reconciliation failure cannot release the original.
            return
        with self._lock, self._session(immediate=True) as connection:
            active = connection.execute(
                "SELECT status FROM usage_reservations WHERE reservation_id=?",
                (reservation.reservation_id,),
            ).fetchone()
            if active is None:
                return
            previous = self._find_receipt(connection, reservation.reservation_id)
            if not dispatched and active[0] in {"uncertain", "dispatched"}:
                raise CostLimitExceeded(
                    "uncertain provider billing requires original usage reconciliation"
                )
            if previous is not None and previous["status"] == "policy_violation":
                return
            if previous is not None:
                receipt = {
                    **previous,
                    "status": "uncertain" if dispatched else "not_dispatched",
                }
            else:
                usage = (
                    Usage()
                    if dispatched
                    else Usage(
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        {name: "derived" for name in _COUNTERS},
                    )
                )
                receipt = self._receipt(
                    reservation,
                    usage,
                    None if dispatched else 0.0,
                    "unknown" if dispatched else "derived",
                    "uncertain" if dispatched else "not_dispatched",
                )
            receipt["failure_reason_sha256"] = hashlib.sha256(
                redact_sensitive_text(reason).encode("utf-8")
            ).hexdigest()
            receipt["dispatch_uncertain"] = dispatched
            if not dispatched:
                # No effect can own this Kernel key; a newly admitted attempt
                # may claim it while the zero-effect failure stays auditable.
                receipt["execution_key"] = ""
            self._write_receipt(connection, reservation, receipt)
            if dispatched:
                connection.execute(
                    "UPDATE usage_reservations SET status='uncertain' WHERE reservation_id=?",
                    (reservation.reservation_id,),
                )
            else:
                connection.execute(
                    "DELETE FROM usage_reservations WHERE reservation_id=?",
                    (reservation.reservation_id,),
                )
            if balance_exhausted:
                connection.execute(
                    """INSERT OR REPLACE INTO provider_blocks
                       (day, scope_hash, reason, created_at) VALUES (?, ?, ?, ?)""",
                    (
                        reservation.day,
                        reservation.credential_ref_hash,
                        "provider balance exhausted",
                        _utc_now(),
                    ),
                )

    def summary(self, *, day: str | None = None) -> dict[str, Any]:
        selected_day = day or _utc_day()
        groups: dict[tuple[str, ...], dict[str, Any]] = {}
        totals = {name: 0 for name in _COUNTERS}
        estimates = {name: 0 for name in _COUNTERS}
        unknown = {name: 0 for name in _COUNTERS}
        reported_cost = estimated_cost = derived_cost = 0.0
        reported_cost_requests = estimated_cost_requests = derived_cost_requests = 0
        unknown_cost = uncertain_calls = request_count = 0
        receipts: list[dict[str, Any]] = []
        with self._lock, self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM usage_receipts WHERE day=? ORDER BY created_at, receipt_id",
                (selected_day,),
            )
            for row in rows:
                request_count += 1
                receipt = (
                    json.loads(row["receipt_json"])
                    if row["receipt_json"]
                    else {
                        "receipt_id": row["receipt_id"],
                        "status": row["status"],
                        "usage": Usage().to_dict(),
                        "cost_usd": None,
                        "cost_measurement": "legacy_unknown",
                    }
                )
                usage = receipt["usage"]
                key = tuple(
                    redact_sensitive_text(row[name])
                    for name in (
                        "provider_id",
                        "model_id",
                        "task_id",
                        "credential_ref_hash",
                    )
                )
                group = groups.setdefault(
                    key,
                    {
                        "provider_id": key[0],
                        "model_id": key[1],
                        "task_id": key[2],
                        "credential_ref_hash": key[3],
                        "requests": 0,
                        "known_totals": {name: 0 for name in _COUNTERS},
                        "estimated_totals": {name: 0 for name in _COUNTERS},
                        "unknown_counters": {name: 0 for name in _COUNTERS},
                        "known_cost_usd": 0.0,
                        "unknown_cost_requests": 0,
                    },
                )
                group["requests"] += 1
                for name in _COUNTERS:
                    value = usage.get(name)
                    if (
                        value is None
                        or usage["counter_measurements"][name] == "estimated"
                    ):
                        unknown[name] += 1
                        group["unknown_counters"][name] += 1
                        if value is not None:
                            estimates[name] += value
                            group["estimated_totals"][name] += value
                    else:
                        totals[name] += value
                        group["known_totals"][name] += value
                cost = receipt["cost_usd"]
                if cost is None:
                    unknown_cost += 1
                    group["unknown_cost_requests"] += 1
                else:
                    group["known_cost_usd"] += cost
                    if receipt["cost_measurement"] == "estimated":
                        estimated_cost += cost
                        estimated_cost_requests += 1
                    elif receipt["cost_measurement"] == "derived":
                        derived_cost += cost
                        derived_cost_requests += 1
                    else:
                        reported_cost += cost
                        reported_cost_requests += 1
                uncertain_calls += int(
                    receipt["status"] in {"uncertain", "usage_unknown"}
                )
                receipts.append(receipt)
                if len(receipts) > 256:
                    del receipts[0]
            reservations = [
                redact_sensitive_data(
                    {
                        "reservation_id": row["reservation_id"],
                        "request_id": row["request_id"],
                        "task_id": row["task_id"],
                        "provider_id": row["provider_id"],
                        "model_id": row["model_id"],
                        "attempt": row["attempt"],
                        "status": row["status"],
                        "receipt_recorded": bool(row["has_receipt"]),
                        "estimated_tokens": row["estimated_tokens"],
                        "estimated_cost_usd": row["estimated_cost_usd"]
                        if row["cost_measurement"] == "estimated"
                        else None,
                    }
                )
                for row in connection.execute(
                    """SELECT r.*, EXISTS(SELECT 1 FROM usage_receipts u
                       WHERE u.reservation_id=r.reservation_id) AS has_receipt
                       FROM usage_reservations r WHERE day=?""",
                    (selected_day,),
                )
            ]
            budget_tokens, budget_cost, _, _ = self._budget_totals(
                connection, selected_day
            )
            cost_unbounded = self._unbounded_cost(connection, selected_day)
        items = []
        pending = sum(not item["receipt_recorded"] for item in reservations)
        for group in groups.values():
            items.append(
                {
                    **group,
                    **{
                        name: None
                        if group["unknown_counters"][name]
                        else group["known_totals"][name]
                        for name in _COUNTERS
                    },
                    "cost_usd": None
                    if group["unknown_cost_requests"]
                    else group["known_cost_usd"],
                }
            )
        return {
            "schema_version": 1,
            "day": selected_day,
            "requests": request_count,
            **{
                name: None if unknown[name] or pending else totals[name]
                for name in _COUNTERS
            },
            "known_totals": totals,
            "estimated_totals": estimates,
            "unknown_counters": unknown,
            "total_cost_usd": None
            if unknown_cost or pending
            else reported_cost + estimated_cost + derived_cost,
            "reported_cost_usd": reported_cost,
            "estimated_cost_usd": estimated_cost,
            "derived_cost_usd": derived_cost,
            "reported_cost_requests": reported_cost_requests,
            "estimated_cost_requests": estimated_cost_requests,
            "derived_cost_requests": derived_cost_requests,
            "unknown_cost_requests": unknown_cost,
            "cost_measurement": "unknown"
            if unknown_cost or pending
            else "estimated"
            if estimated_cost_requests
            else "reported"
            if reported_cost_requests
            else "derived"
            if derived_cost_requests
            else "no_receipts",
            "uncertain_calls": uncertain_calls,
            "pending_requests": pending,
            "reserved_tokens": sum(item["estimated_tokens"] for item in reservations),
            "reserved_cost_usd": None
            if any(item["estimated_cost_usd"] is None for item in reservations)
            else sum(item["estimated_cost_usd"] for item in reservations),
            "reservations": reservations,
            "remaining": {
                "tokens": max(0, self.policy.max_daily_tokens - budget_tokens),
                "cost_usd": None
                if self.policy.max_daily_cost_usd is None or cost_unbounded
                else max(0.0, self.policy.max_daily_cost_usd - budget_cost),
            },
            "policy": {
                **{
                    name: getattr(self.policy, name)
                    for name in self.policy.__dataclass_fields__
                },
                "budget_mode": "token_only"
                if self.policy.max_daily_cost_usd is None
                and self.policy.max_retry_cost_usd is None
                else "usd",
                "pricing": self.pricing.readiness(),
                "daily_usd_environment_variable": "APEIR_MAX_DAILY_COST_USD",
                "retry_usd_environment_variable": "APEIR_MAX_RETRY_COST_USD",
            },
            "items": items,
            "receipts": receipts,
            "receipts_truncated": request_count > len(receipts),
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _session(self, *, immediate: bool = False):
        connection = self._connect()
        try:
            with connection:
                if immediate:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS usage_receipts (
                    receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    day TEXT NOT NULL, request_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
                    credential_ref_hash TEXT NOT NULL, input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL, cached_input_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL,
                    attempt INTEGER NOT NULL, status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS usage_receipts_day_idx
                    ON usage_receipts(day);
                CREATE TABLE IF NOT EXISTS usage_reservations (
                    reservation_id TEXT PRIMARY KEY, day TEXT NOT NULL,
                    request_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
                    credential_ref_hash TEXT NOT NULL, estimated_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL, attempt INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_blocks (
                    day TEXT NOT NULL, scope_hash TEXT NOT NULL, reason TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(day, scope_hash)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            additions = {
                "usage_receipts": {
                    "reservation_id": "TEXT NOT NULL DEFAULT ''",
                    "cost_measurement": "TEXT NOT NULL DEFAULT 'legacy_unknown'",
                    "receipt_json": "TEXT NOT NULL DEFAULT ''",
                    "execution_key": "TEXT NOT NULL DEFAULT ''",
                },
                "usage_reservations": {
                    "status": "TEXT NOT NULL DEFAULT 'reserved'",
                    "cost_measurement": "TEXT NOT NULL DEFAULT 'legacy_unknown'",
                    "execution_key": "TEXT NOT NULL DEFAULT ''",
                    "reservation_json": "TEXT NOT NULL DEFAULT ''",
                },
            }
            for table, fields in additions.items():
                present = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                for name, definition in fields.items():
                    if name not in present:
                        connection.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                        )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS usage_receipts_reservation_idx
                   ON usage_receipts(reservation_id) WHERE reservation_id<>''"""
            )
            for table in ("usage_reservations", "usage_receipts"):
                connection.execute(
                    f"""CREATE UNIQUE INDEX IF NOT EXISTS {table}_execution_idx
                       ON {table}(execution_key) WHERE execution_key<>''"""
                )


__all__ = [
    "CostController",
    "CostLimitExceeded",
    "CostPolicy",
    "Pricing",
    "PricingCatalog",
    "Reservation",
    "Usage",
]

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
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

from nous_runtime.model_runtime.errors import ModelRuntimeError

if TYPE_CHECKING:
    from nous_runtime.model_runtime.models import ModelRequest, ModelResponse


class CostLimitExceeded(ModelRuntimeError):
    """A model request was rejected before provider execution."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _positive_int(name: str, value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CostLimitExceeded(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise CostLimitExceeded(f"{name} must be positive")
    return parsed


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "Usage":
        raw = dict(value or {})
        input_tokens = int(
            raw.get("input_tokens") or raw.get("prompt_tokens") or 0
        )
        output_tokens = int(
            raw.get("output_tokens") or raw.get("completion_tokens") or 0
        )
        cached = int(
            raw.get("cached_input_tokens")
            or raw.get("cache_read_input_tokens")
            or (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
            or 0
        )
        total = int(raw.get("total_tokens") or input_tokens + output_tokens)
        values = (input_tokens, output_tokens, cached, total)
        if any(item < 0 for item in values):
            raise CostLimitExceeded("provider usage values must be non-negative")
        if total < input_tokens + output_tokens:
            total = input_tokens + output_tokens
        return cls(input_tokens, output_tokens, cached, total)

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class Pricing:
    input_per_million_usd: float = 0.0
    output_per_million_usd: float = 0.0
    cached_input_per_million_usd: float = 0.0

    def estimate(self, usage: Usage) -> float:
        uncached = max(0, usage.input_tokens - usage.cached_input_tokens)
        value = (
            uncached * self.input_per_million_usd
            + usage.cached_input_tokens * self.cached_input_per_million_usd
            + usage.output_tokens * self.output_per_million_usd
        ) / 1_000_000
        return round(value, 12)


class PricingCatalog:
    def __init__(self, entries: Mapping[str, Pricing] | None = None) -> None:
        self._entries = dict(entries or {})

    @classmethod
    def from_file(cls, path: Path | None) -> "PricingCatalog":
        if path is None or not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries: dict[str, Pricing] = {}
        for key, value in dict(payload.get("models") or {}).items():
            entries[str(key)] = Pricing(
                float(value.get("input_per_million_usd") or 0),
                float(value.get("output_per_million_usd") or 0),
                float(value.get("cached_input_per_million_usd") or 0),
            )
        return cls(entries)

    def get(self, provider_id: str, model_id: str) -> Pricing | None:
        return self._entries.get(f"{provider_id}/{model_id}") or self._entries.get(
            model_id
        )


@dataclass(frozen=True)
class CostPolicy:
    max_input_tokens: int = 65_536
    max_output_tokens: int = 4_096
    max_request_tokens: int = 69_632
    max_daily_tokens: int = 1_000_000
    max_daily_cost_usd: float = 5.0
    max_attempts: int = 3
    max_retry_tokens: int = 32_768
    max_retry_cost_usd: float = 1.0

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_input_tokens,
            self.max_output_tokens,
            self.max_request_tokens,
            self.max_daily_tokens,
            self.max_attempts,
            self.max_retry_tokens,
        )
        if any(int(value) <= 0 for value in integer_limits):
            raise CostLimitExceeded("cost-policy token limits must be positive")
        if self.max_daily_cost_usd <= 0 or self.max_retry_cost_usd <= 0:
            raise CostLimitExceeded("cost-policy monetary limits must be positive")

    @classmethod
    def from_environment(cls) -> "CostPolicy":
        env = os.environ
        return cls(
            max_input_tokens=_positive_int(
                "APEIR_MAX_INPUT_TOKENS",
                env.get("APEIR_MAX_INPUT_TOKENS", 65_536),
                65_536,
            ),
            max_output_tokens=_positive_int(
                "APEIR_MAX_OUTPUT_TOKENS",
                env.get("APEIR_MAX_OUTPUT_TOKENS", 4_096),
                4_096,
            ),
            max_request_tokens=_positive_int(
                "APEIR_MAX_REQUEST_TOKENS",
                env.get("APEIR_MAX_REQUEST_TOKENS", 69_632),
                69_632,
            ),
            max_daily_tokens=_positive_int(
                "APEIR_MAX_DAILY_TOKENS",
                env.get("APEIR_MAX_DAILY_TOKENS", 1_000_000),
                1_000_000,
            ),
            max_daily_cost_usd=float(env.get("APEIR_MAX_DAILY_COST_USD", 5.0)),
            max_attempts=_positive_int(
                "APEIR_MAX_MODEL_ATTEMPTS",
                env.get("APEIR_MAX_MODEL_ATTEMPTS", 3),
                3,
            ),
            max_retry_tokens=_positive_int(
                "APEIR_MAX_RETRY_TOKENS",
                env.get("APEIR_MAX_RETRY_TOKENS", 32_768),
                32_768,
            ),
            max_retry_cost_usd=float(
                env.get("APEIR_MAX_RETRY_COST_USD", 1.0)
            ),
        )


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    request: "ModelRequest"
    provider_id: str
    model_id: str
    credential_ref_hash: str
    attempt: int
    estimated_usage: Usage
    estimated_cost_usd: float


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
            os.environ.get("APEIR_STATE_DIR")
            or os.environ.get("NOUS_HOME")
            or ".apeir"
        ).expanduser()
        pricing_path = os.environ.get("APEIR_MODEL_PRICING_FILE", "").strip()
        return cls(
            state_root / "usage.sqlite3",
            policy=CostPolicy.from_environment(),
            pricing=PricingCatalog.from_file(Path(pricing_path) if pricing_path else None),
        )

    @staticmethod
    def estimate_input_tokens(request: "ModelRequest") -> int:
        explicit = request.metadata.get("estimated_input_tokens")
        if explicit is not None:
            return _positive_int("estimated_input_tokens", explicit, 1)
        encoded = json.dumps(
            {
                "messages": [dict(item) for item in request.messages],
                "attachments": [dict(item) for item in request.attachments],
                "input": request.metadata.get("input"),
                "tools": list(request.metadata.get("tools") or ()),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return max(1, math.ceil(len(encoded) / 3))

    def authorize(
        self,
        request: "ModelRequest",
        *,
        provider_id: str,
        model_id: str,
        credential_ref: str = "",
        attempt: int = 1,
    ) -> Reservation:
        policy = self.policy
        if attempt < 1 or attempt > policy.max_attempts:
            raise CostLimitExceeded("model retry attempt budget exceeded")
        input_tokens = self.estimate_input_tokens(request)
        requested_output = int(
            request.metadata.get("max_output_tokens")
            or request.metadata.get("max_tokens")
            or policy.max_output_tokens
        )
        if input_tokens > policy.max_input_tokens:
            raise CostLimitExceeded("model input token limit exceeded")
        if requested_output <= 0:
            raise CostLimitExceeded("model output token limit must be positive")
        output_tokens = min(requested_output, policy.max_output_tokens)
        estimate = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
        if estimate.total_tokens > policy.max_request_tokens:
            raise CostLimitExceeded("model request token budget exceeded")
        rate = self.pricing.get(provider_id, model_id)
        estimated_cost = rate.estimate(estimate) if rate else 0.0
        if request.max_cost_usd is not None and estimated_cost > request.max_cost_usd:
            raise CostLimitExceeded("model request cost budget exceeded")
        credential_hash = hashlib.sha256(
            (credential_ref or f"provider:{provider_id}").encode("utf-8")
        ).hexdigest()
        reservation_id = f"usage-reservation-{uuid.uuid4().hex}"
        guarded = replace(
            request,
            metadata={
                **dict(request.metadata),
                "max_tokens": output_tokens,
                "max_output_tokens": output_tokens,
            },
        )
        with self._lock, self._session() as connection:
            blocked = connection.execute(
                "SELECT reason FROM provider_blocks WHERE day=? AND scope_hash=?",
                (_utc_day(), credential_hash),
            ).fetchone()
            if blocked:
                raise CostLimitExceeded(f"provider spending is blocked: {blocked[0]}")
            totals = connection.execute(
                """SELECT
                     COALESCE((SELECT SUM(total_tokens) FROM usage_receipts WHERE day=?), 0)
                     + COALESCE((SELECT SUM(estimated_tokens) FROM usage_reservations WHERE day=?), 0),
                     COALESCE((SELECT SUM(cost_usd) FROM usage_receipts WHERE day=?), 0)
                     + COALESCE((SELECT SUM(estimated_cost_usd) FROM usage_reservations WHERE day=?), 0),
                     COALESCE((SELECT SUM(total_tokens) FROM usage_receipts WHERE day=? AND attempt>1), 0)
                     + COALESCE((SELECT SUM(estimated_tokens) FROM usage_reservations WHERE day=? AND attempt>1), 0),
                     COALESCE((SELECT SUM(cost_usd) FROM usage_receipts WHERE day=? AND attempt>1), 0)
                     + COALESCE((SELECT SUM(estimated_cost_usd) FROM usage_reservations WHERE day=? AND attempt>1), 0)
                """,
                (_utc_day(),) * 8,
            ).fetchone()
            daily_tokens, daily_cost, retry_tokens, retry_cost = totals
            if int(daily_tokens) + estimate.total_tokens > policy.max_daily_tokens:
                raise CostLimitExceeded("daily model token budget exceeded")
            if float(daily_cost) + estimated_cost > policy.max_daily_cost_usd:
                raise CostLimitExceeded("daily model cost budget exceeded")
            if attempt > 1 and int(retry_tokens) + estimate.total_tokens > policy.max_retry_tokens:
                raise CostLimitExceeded("model retry token budget exceeded")
            if attempt > 1 and float(retry_cost) + estimated_cost > policy.max_retry_cost_usd:
                raise CostLimitExceeded("model retry cost budget exceeded")
            connection.execute(
                """INSERT INTO usage_reservations
                   (reservation_id, day, request_id, task_id, provider_id, model_id,
                    credential_ref_hash, estimated_tokens, estimated_cost_usd, attempt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    reservation_id, _utc_day(), request.request_id, request.task_id,
                    provider_id, model_id, credential_hash, estimate.total_tokens,
                    estimated_cost, attempt,
                ),
            )
        return Reservation(
            reservation_id, guarded, provider_id, model_id, credential_hash,
            attempt, estimate, estimated_cost,
        )

    def commit(
        self, reservation: Reservation, response: "ModelResponse"
    ) -> tuple["ModelResponse", dict[str, Any]]:
        usage = Usage.from_mapping(response.usage)
        rate = self.pricing.get(reservation.provider_id, reservation.model_id)
        cost = float(response.cost_usd)
        if cost <= 0 and rate is not None:
            cost = rate.estimate(usage)
        receipt_id = f"usage-{uuid.uuid4().hex}"
        created_at = _utc_now()
        receipt = {
            "schema_version": 1,
            "receipt_id": receipt_id,
            "created_at": created_at,
            "request_id": reservation.request.request_id,
            "task_id": reservation.request.task_id,
            "provider_id": reservation.provider_id,
            "model_id": reservation.model_id,
            "credential_ref_hash": reservation.credential_ref_hash,
            "attempt": reservation.attempt,
            "usage": usage.to_dict(),
            "cost_usd": cost,
            "status": "completed",
        }
        violations: list[str] = []
        if usage.output_tokens > reservation.estimated_usage.output_tokens:
            violations.append("provider output exceeded the authorized token limit")
        if usage.total_tokens > self.policy.max_request_tokens:
            violations.append("provider usage exceeded the request token limit")
        with self._lock, self._session() as connection:
            connection.execute(
                "DELETE FROM usage_reservations WHERE reservation_id=?",
                (reservation.reservation_id,),
            )
            connection.execute(
                """INSERT INTO usage_receipts
                   (receipt_id, created_at, day, request_id, task_id, provider_id,
                    model_id, credential_ref_hash, input_tokens, output_tokens,
                    cached_input_tokens, total_tokens, cost_usd, attempt, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt_id, created_at, _utc_day(), reservation.request.request_id,
                    reservation.request.task_id, reservation.provider_id,
                    reservation.model_id, reservation.credential_ref_hash,
                    usage.input_tokens, usage.output_tokens, usage.cached_input_tokens,
                    usage.total_tokens, cost, reservation.attempt, "completed",
                ),
            )
            totals = connection.execute(
                """SELECT COALESCE(SUM(total_tokens), 0), COALESCE(SUM(cost_usd), 0)
                   FROM usage_receipts WHERE day=?""",
                (_utc_day(),),
            ).fetchone()
            if int(totals[0]) > self.policy.max_daily_tokens:
                violations.append("provider usage exceeded the daily token limit")
            if float(totals[1]) > self.policy.max_daily_cost_usd:
                violations.append("provider usage exceeded the daily cost limit")
            if violations:
                reason = "; ".join(violations)
                connection.execute(
                    """UPDATE usage_receipts SET status='policy_violation'
                       WHERE receipt_id=?""",
                    (receipt_id,),
                )
                connection.execute(
                    """INSERT OR REPLACE INTO provider_blocks
                       (day, scope_hash, reason, created_at) VALUES (?, ?, ?, ?)""",
                    (_utc_day(), reservation.credential_ref_hash, reason, _utc_now()),
                )
                receipt["status"] = "policy_violation"
        normalized = replace(
            response,
            usage=usage.to_dict(),
            cost_usd=cost,
            metadata={**dict(response.metadata), "usage_receipt": receipt},
        )
        if violations:
            raise CostLimitExceeded(
                "provider response violated the authorized usage budget: "
                + "; ".join(violations)
            )
        return normalized, receipt

    def fail(
        self,
        reservation: Reservation,
        *,
        reason: str,
        balance_exhausted: bool = False,
    ) -> None:
        with self._lock, self._session() as connection:
            connection.execute(
                "DELETE FROM usage_reservations WHERE reservation_id=?",
                (reservation.reservation_id,),
            )
            if balance_exhausted:
                connection.execute(
                    """INSERT OR REPLACE INTO provider_blocks
                       (day, scope_hash, reason, created_at) VALUES (?, ?, ?, ?)""",
                    (_utc_day(), reservation.credential_ref_hash, reason, _utc_now()),
                )

    def summary(self, *, day: str | None = None) -> dict[str, Any]:
        selected_day = day or _utc_day()
        with self._lock, self._session() as connection:
            rows = connection.execute(
                """SELECT provider_id, model_id, task_id, credential_ref_hash,
                          SUM(input_tokens), SUM(output_tokens), SUM(cached_input_tokens),
                          SUM(total_tokens), SUM(cost_usd), COUNT(*)
                   FROM usage_receipts WHERE day=?
                   GROUP BY provider_id, model_id, task_id, credential_ref_hash""",
                (selected_day,),
            ).fetchall()
        items = [
            {
                "provider_id": row[0], "model_id": row[1], "task_id": row[2],
                "credential_ref_hash": row[3], "input_tokens": row[4],
                "output_tokens": row[5], "cached_input_tokens": row[6],
                "total_tokens": row[7], "cost_usd": row[8], "requests": row[9],
            }
            for row in rows
        ]
        return {
            "schema_version": 1,
            "day": selected_day,
            "total_tokens": sum(int(item["total_tokens"]) for item in items),
            "total_cost_usd": sum(float(item["cost_usd"]) for item in items),
            "cached_input_tokens": sum(
                int(item["cached_input_tokens"]) for item in items
            ),
            "remaining": {
                "tokens": max(
                    0,
                    self.policy.max_daily_tokens
                    - sum(int(item["total_tokens"]) for item in items),
                ),
                "cost_usd": max(
                    0.0,
                    self.policy.max_daily_cost_usd
                    - sum(float(item["cost_usd"]) for item in items),
                ),
            },
            "policy": {
                "max_input_tokens": self.policy.max_input_tokens,
                "max_output_tokens": self.policy.max_output_tokens,
                "max_request_tokens": self.policy.max_request_tokens,
                "max_daily_tokens": self.policy.max_daily_tokens,
                "max_daily_cost_usd": self.policy.max_daily_cost_usd,
                "max_attempts": self.policy.max_attempts,
                "max_retry_tokens": self.policy.max_retry_tokens,
                "max_retry_cost_usd": self.policy.max_retry_cost_usd,
            },
            "items": items,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            with connection:
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


__all__ = [
    "CostController", "CostLimitExceeded", "CostPolicy", "Pricing",
    "PricingCatalog", "Reservation", "Usage",
]

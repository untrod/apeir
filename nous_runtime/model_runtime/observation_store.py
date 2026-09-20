# -*- coding: utf-8 -*-
"""ModelObservationStore — structured recording of model execution observations.

Provides the data foundation for:
- Model capability evaluation (which model is best for which task)
- Dynamic model scheduling (route to best model based on real performance)
- Cost optimization (identify cheaper models that perform equally well)
- Drift detection (detect when a model's performance degrades)

Each observation records:
- Exact model identity (model_id, provider_id, version, quantization)
- Task context (task_type, capability_id, input_modality)
- Performance metrics (latency, tokens, cost, success, quality signals)
- Environmental factors (time of day, load, hardware)
"""

from __future__ import annotations

import atexit
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from nous_runtime.schema_registry import MODEL_OBSERVATION_SCHEMA_VERSION as SCHEMA_VERSION

_log = logging.getLogger("nous.model_obs")



# Data models


class ObservationOutcome(str, Enum):
    """Outcome of a model invocation."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    REJECTED = "rejected"
    FALLBACK = "fallback"


class TaskCategory(str, Enum):
    """Category of the task the model performed."""
    CHAT = "chat"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    EMBEDDING = "embedding"
    VISION = "vision"
    REASONING = "reasoning"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    RETRIEVAL = "retrieval"
    OTHER = "other"


@dataclass
class ModelObservation:
    """A single model execution observation."""

    observation_id: str = ""
    timestamp: str = ""

    # Model identity
    model_id: str = ""
    provider_id: str = ""
    model_version: str = ""
    quantization: str = ""  # e.g., "fp16", "int8", "int4"

    # Task context
    task_type: TaskCategory = TaskCategory.CHAT
    capability_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    session_id: str = ""

    # Performance
    outcome: ObservationOutcome = ObservationOutcome.SUCCESS
    latency_ms: float = 0.0
    time_to_first_token_ms: float = 0.0
    tokens_per_second: float = 0.0

    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Cost
    cost_usd: float = 0.0
    cost_per_1k_tokens: float = 0.0

    # Quality signals (0.0 - 1.0, or -1 for N/A)
    tool_call_valid_rate: float = -1.0
    output_valid: float = -1.0
    user_accepted: float = -1.0
    test_pass_rate: float = -1.0
    verification_passed: float = -1.0

    # Environmental
    node_id: str = ""
    hardware: str = ""  # e.g., "RTX3070", "A100", "cpu"
    runtime_load: float = 0.0  # 0.0 - 1.0
    time_of_day_hour: int = 0

    # Reliability
    retry_count: int = 0
    fallback_used: bool = False
    fallback_model_id: str = ""
    error_category: str = ""
    error_message: str = ""

    # Metadata
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "timestamp": self.timestamp,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "model_version": self.model_version,
            "quantization": self.quantization,
            "task_type": self.task_type.value,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "outcome": self.outcome.value,
            "latency_ms": self.latency_ms,
            "time_to_first_token_ms": self.time_to_first_token_ms,
            "tokens_per_second": self.tokens_per_second,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "tool_call_valid_rate": self.tool_call_valid_rate,
            "output_valid": self.output_valid,
            "user_accepted": self.user_accepted,
            "test_pass_rate": self.test_pass_rate,
            "verification_passed": self.verification_passed,
            "node_id": self.node_id,
            "hardware": self.hardware,
            "runtime_load": self.runtime_load,
            "time_of_day_hour": self.time_of_day_hour,
            "retry_count": self.retry_count,
            "fallback_used": self.fallback_used,
            "fallback_model_id": self.fallback_model_id,
            "error_category": self.error_category,
            "error_message": self.error_message,
            "tags": self.tags,
            "metadata": self.metadata,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelObservation":
        return cls(
            observation_id=str(data.get("observation_id", "")),
            timestamp=str(data.get("timestamp", "")),
            model_id=str(data.get("model_id", "")),
            provider_id=str(data.get("provider_id", "")),
            model_version=str(data.get("model_version", "")),
            quantization=str(data.get("quantization", "")),
            task_type=TaskCategory(str(data.get("task_type", "chat"))),
            capability_id=str(data.get("capability_id", "")),
            task_id=str(data.get("task_id", "")),
            trace_id=str(data.get("trace_id", "")),
            session_id=str(data.get("session_id", "")),
            outcome=ObservationOutcome(str(data.get("outcome", "success"))),
            latency_ms=float(data.get("latency_ms", 0)),
            time_to_first_token_ms=float(data.get("time_to_first_token_ms", 0)),
            tokens_per_second=float(data.get("tokens_per_second", 0)),
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            cost_usd=float(data.get("cost_usd", 0)),
            cost_per_1k_tokens=float(data.get("cost_per_1k_tokens", 0)),
            tool_call_valid_rate=float(data.get("tool_call_valid_rate", -1)),
            output_valid=float(data.get("output_valid", -1)),
            user_accepted=float(data.get("user_accepted", -1)),
            test_pass_rate=float(data.get("test_pass_rate", -1)),
            verification_passed=float(data.get("verification_passed", -1)),
            node_id=str(data.get("node_id", "")),
            hardware=str(data.get("hardware", "")),
            runtime_load=float(data.get("runtime_load", 0)),
            time_of_day_hour=int(data.get("time_of_day_hour", 0)),
            retry_count=int(data.get("retry_count", 0)),
            fallback_used=bool(data.get("fallback_used", False)),
            fallback_model_id=str(data.get("fallback_model_id", "")),
            error_category=str(data.get("error_category", "")),
            error_message=str(data.get("error_message", "")),
            tags=dict(data.get("tags", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ModelPerformanceSummary:
    """Aggregated performance summary for a model/provider/capability combination."""

    model_id: str = ""
    provider_id: str = ""
    capability_id: str = ""
    task_type: TaskCategory = TaskCategory.CHAT

    sample_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    fallback_count: int = 0

    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    avg_tokens_per_request: float = 0.0
    avg_cost_per_request_usd: float = 0.0
    total_cost_usd: float = 0.0

    avg_tool_call_valid_rate: float = -1.0
    avg_output_valid: float = -1.0

    last_observed_at: str = ""
    first_observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "task_type": self.task_type.value,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "fallback_count": self.fallback_count,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "avg_tokens_per_request": self.avg_tokens_per_request,
            "avg_cost_per_request_usd": self.avg_cost_per_request_usd,
            "total_cost_usd": self.total_cost_usd,
            "avg_tool_call_valid_rate": self.avg_tool_call_valid_rate,
            "avg_output_valid": self.avg_output_valid,
            "last_observed_at": self.last_observed_at,
            "first_observed_at": self.first_observed_at,
        }



# ModelObservationStore


class ModelObservationStore:
    """SQLite-backed store for model execution observations.

    Supports:
    - Recording individual observations
    - Querying by model, provider, capability, task type
    - Computing aggregate performance summaries
    - Time-windowed queries for trend analysis
    - Export for external analysis
    """

    def __init__(self, workspace_root: str = ""):
        self._workspace = workspace_root or "."
        self._db_path = Path(self._workspace) / ".nous" / "model_observations.db"
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._ensure_db()

    # Recording

    def record(
        self,
        *,
        model_id: str,
        provider_id: str,
        task_type: TaskCategory = TaskCategory.CHAT,
        capability_id: str = "",
        task_id: str = "",
        trace_id: str = "",
        session_id: str = "",
        outcome: ObservationOutcome = ObservationOutcome.SUCCESS,
        latency_ms: float = 0.0,
        time_to_first_token_ms: float = 0.0,
        tokens_per_second: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        tool_call_valid_rate: float = -1.0,
        output_valid: float = -1.0,
        user_accepted: float = -1.0,
        test_pass_rate: float = -1.0,
        verification_passed: float = -1.0,
        node_id: str = "",
        hardware: str = "",
        retry_count: int = 0,
        fallback_used: bool = False,
        fallback_model_id: str = "",
        error_category: str = "",
        error_message: str = "",
        tags: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelObservation:
        """Record a model observation."""
        obs = ModelObservation(
            observation_id=f"obs_{uuid.uuid4().hex[:16]}",
            timestamp=_utc_now(),
            model_id=model_id,
            provider_id=provider_id,
            task_type=task_type,
            capability_id=capability_id,
            task_id=task_id,
            trace_id=trace_id,
            session_id=session_id,
            outcome=outcome,
            latency_ms=latency_ms,
            time_to_first_token_ms=time_to_first_token_ms,
            tokens_per_second=tokens_per_second,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost_usd,
            cost_per_1k_tokens=(
                (cost_usd / (prompt_tokens + completion_tokens) * 1000)
                if (prompt_tokens + completion_tokens) > 0 else 0.0
            ),
            tool_call_valid_rate=tool_call_valid_rate,
            output_valid=output_valid,
            user_accepted=user_accepted,
            test_pass_rate=test_pass_rate,
            verification_passed=verification_passed,
            node_id=node_id,
            hardware=hardware,
            time_of_day_hour=int(time.strftime("%H")),
            retry_count=retry_count,
            fallback_used=fallback_used,
            fallback_model_id=fallback_model_id,
            error_category=error_category,
            error_message=error_message,
            tags=dict(tags or {}),
            metadata=dict(metadata or {}),
        )
        self._persist(obs)
        return obs

    # Query

    def query(
        self,
        *,
        model_id: str = "",
        provider_id: str = "",
        capability_id: str = "",
        task_type: str = "",
        outcome: str = "",
        since: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query observations with filters."""
        self._ensure_db()
        if self._db is None:
            return []

        conditions = []
        params: list[Any] = []

        for col, val in [
            ("model_id", model_id), ("provider_id", provider_id),
            ("capability_id", capability_id), ("task_type", task_type),
            ("outcome", outcome),
        ]:
            if val:
                conditions.append(f"{col} = ?")
                params.append(val)

        if since:
            conditions.append("timestamp > ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = self._db.execute(
                f"SELECT payload FROM model_observations{where} "
                f"ORDER BY rowid DESC LIMIT ? OFFSET ?",
                params + [max(1, min(int(limit), 1000)), max(0, int(offset))],
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
        except Exception as e:
            _log.warning("Observation query failed: %s", e)
            return []

    def query_recent(
        self,
        *,
        model_id: str = "",
        provider_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent observations."""
        return self.query(model_id=model_id, provider_id=provider_id, limit=limit)

    def count(
        self,
        *,
        model_id: str = "",
        provider_id: str = "",
        since: str = "",
    ) -> int:
        """Count observations matching filters."""
        self._ensure_db()
        if self._db is None:
            return 0

        conditions = []
        params: list[Any] = []
        if model_id:
            conditions.append("model_id = ?")
            params.append(model_id)
        if provider_id:
            conditions.append("provider_id = ?")
            params.append(provider_id)
        if since:
            conditions.append("timestamp > ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        try:
            row = self._db.execute(
                f"SELECT COUNT(*) FROM model_observations{where}", params
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    # Aggregation

    def get_performance_summary(
        self,
        *,
        model_id: str = "",
        provider_id: str = "",
        capability_id: str = "",
        task_type: str = "",
        since: str = "",
    ) -> ModelPerformanceSummary:
        """Compute an aggregated performance summary."""
        self._ensure_db()
        if self._db is None:
            return ModelPerformanceSummary()

        conditions = []
        params: list[Any] = []

        for col, val in [
            ("model_id", model_id), ("provider_id", provider_id),
            ("capability_id", capability_id), ("task_type", task_type),
        ]:
            if val:
                conditions.append(f"{col} = ?")
                params.append(val)
        if since:
            conditions.append("timestamp > ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = self._db.execute(
                f"SELECT outcome, latency_ms, prompt_tokens, completion_tokens, "
                f"cost_usd, tool_call_valid_rate, output_valid, timestamp "
                f"FROM model_observations{where} "
                f"ORDER BY rowid DESC LIMIT 10000",
                params,
            ).fetchall()

            if not rows:
                return ModelPerformanceSummary(
                    model_id=model_id, provider_id=provider_id,
                    capability_id=capability_id,
                    task_type=TaskCategory(task_type) if task_type else TaskCategory.CHAT,
                )

            summary = ModelPerformanceSummary(
                model_id=model_id, provider_id=provider_id,
                capability_id=capability_id,
                task_type=TaskCategory(task_type) if task_type else TaskCategory.CHAT,
                sample_count=len(rows),
                first_observed_at=rows[-1][7],
                last_observed_at=rows[0][7],
            )

            success = sum(1 for r in rows if r[0] == "success")
            failure = sum(1 for r in rows if r[0] == "failure")
            timeout = sum(1 for r in rows if r[0] == "timeout")
            fallback = sum(1 for r in rows if r[0] == "fallback")

            summary.success_count = success
            summary.failure_count = failure
            summary.timeout_count = timeout
            summary.fallback_count = fallback
            summary.success_rate = success / len(rows) if rows else 0.0

            latencies = sorted(r[1] for r in rows if r[1] > 0)
            if latencies:
                summary.avg_latency_ms = sum(latencies) / len(latencies)
                summary.p50_latency_ms = _percentile(latencies, 50)
                summary.p95_latency_ms = _percentile(latencies, 95)
                summary.p99_latency_ms = _percentile(latencies, 99)

            total_tokens = [r[2] + r[3] for r in rows if (r[2] + r[3]) > 0]
            if total_tokens:
                summary.avg_tokens_per_request = sum(total_tokens) / len(total_tokens)

            costs = [r[4] for r in rows if r[4] > 0]
            if costs:
                summary.avg_cost_per_request_usd = sum(costs) / len(costs)
                summary.total_cost_usd = sum(costs)

            valid_rates = [r[5] for r in rows if r[5] >= 0]
            if valid_rates:
                summary.avg_tool_call_valid_rate = sum(valid_rates) / len(valid_rates)

            output_valid_rates = [r[6] for r in rows if r[6] >= 0]
            if output_valid_rates:
                summary.avg_output_valid = sum(output_valid_rates) / len(output_valid_rates)

            return summary
        except Exception as e:
            _log.warning("Performance summary failed: %s", e)
            return ModelPerformanceSummary()

    def get_model_rankings(
        self,
        *,
        capability_id: str = "",
        task_type: str = "",
        metric: str = "success_rate",
        min_samples: int = 10,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Rank models by a given performance metric."""
        self._ensure_db()
        if self._db is None:
            return []

        conditions = []
        params: list[Any] = []
        if capability_id:
            conditions.append("capability_id = ?")
            params.append(capability_id)
        if task_type:
            conditions.append("task_type = ?")
            params.append(task_type)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = self._db.execute(
                f"SELECT model_id, provider_id, COUNT(*) as cnt, "
                f"SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as rate, "
                f"AVG(latency_ms) as avg_lat, "
                f"AVG(cost_usd) as avg_cost, "
                f"AVG(tool_call_valid_rate) as avg_tool_valid "
                f"FROM model_observations{where} "
                f"GROUP BY model_id, provider_id "
                f"HAVING cnt >= ? "
                f"ORDER BY rate DESC, avg_lat ASC "
                f"LIMIT ?",
                params + [max(1, int(min_samples)), max(1, min(int(limit), 100))],
            ).fetchall()

            return [
                {
                    "model_id": r[0],
                    "provider_id": r[1],
                    "sample_count": r[2],
                    "success_rate": round(r[3], 4),
                    "avg_latency_ms": round(r[4], 2) if r[4] else 0,
                    "avg_cost_usd": round(r[5], 6) if r[5] else 0,
                    "avg_tool_call_valid_rate": round(r[6], 4) if r[6] and r[6] >= 0 else -1,
                }
                for r in rows
            ]
        except Exception as e:
            _log.warning("Model ranking failed: %s", e)
            return []

    def get_cost_summary(
        self,
        *,
        since: str = "",
        group_by: str = "model_id",
    ) -> list[dict[str, Any]]:
        """Get cost summary grouped by model or provider."""
        self._ensure_db()
        if self._db is None:
            return []

        valid_groups = {"model_id", "provider_id", "capability_id", "task_type"}
        group = group_by if group_by in valid_groups else "model_id"

        conditions = []
        params: list[Any] = []
        if since:
            conditions.append("timestamp > ?")
            params.append(since)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = self._db.execute(
                f"SELECT {group}, COUNT(*) as cnt, "
                f"SUM(cost_usd) as total_cost, "
                f"AVG(cost_usd) as avg_cost, "
                f"SUM(prompt_tokens + completion_tokens) as total_tokens "
                f"FROM model_observations{where} "
                f"GROUP BY {group} "
                f"ORDER BY total_cost DESC "
                f"LIMIT 50",
                params,
            ).fetchall()

            return [
                {
                    group: r[0],
                    "request_count": r[1],
                    "total_cost_usd": round(r[2], 6),
                    "avg_cost_per_request_usd": round(r[3], 6),
                    "total_tokens": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            _log.warning("Cost summary failed: %s", e)
            return []

    # Export

    def export_observations(
        self,
        *,
        since: str = "",
        limit: int = 10000,
        format: str = "jsonl",
    ) -> str:
        """Export observations to a file for external analysis."""
        observations = self.query(since=since, limit=limit)
        export_dir = Path(self._workspace) / ".nous" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        filename = f"model_observations_{_utc_now().replace(':', '-')}.{format}"
        filepath = export_dir / filename

        if format == "jsonl":
            with open(filepath, "w", encoding="utf-8") as f:
                for obs in observations:
                    f.write(json.dumps(obs, ensure_ascii=False) + "\n")
        elif format == "json":
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(observations, f, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported export format: {format}")

        _log.info("Exported %d observations to %s", len(observations), filepath)
        return str(filepath)

    def get_statistics(self) -> dict[str, Any]:
        """Return aggregate statistics about the observation store."""
        self._ensure_db()
        if self._db is None:
            return {"total_observations": 0}

        try:
            total = self._db.execute(
                "SELECT COUNT(*) FROM model_observations"
            ).fetchone()

            by_model = self._db.execute(
                "SELECT model_id, COUNT(*) FROM model_observations "
                "GROUP BY model_id ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()

            by_outcome = self._db.execute(
                "SELECT outcome, COUNT(*) FROM model_observations "
                "GROUP BY outcome"
            ).fetchall()

            total_cost = self._db.execute(
                "SELECT SUM(cost_usd) FROM model_observations"
            ).fetchone()

            return {
                "total_observations": int(total[0]) if total else 0,
                "top_models": [{"model_id": r[0], "count": r[1]} for r in by_model],
                "by_outcome": {r[0]: r[1] for r in by_outcome},
                "total_cost_usd": round(float(total_cost[0] or 0), 6),
            }
        except Exception as e:
            _log.warning("Statistics query failed: %s", e)
            return {"total_observations": 0}

    def shutdown(self) -> None:
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    # Internal

    def _ensure_db(self) -> None:
        if self._db is not None:
            return
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=5.0)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS model_observations (
                    observation_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_version TEXT NOT NULL DEFAULT '',
                    quantization TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT 'chat',
                    capability_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT 'success',
                    latency_ms REAL NOT NULL DEFAULT 0,
                    time_to_first_token_ms REAL NOT NULL DEFAULT 0,
                    tokens_per_second REAL NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    cost_per_1k_tokens REAL NOT NULL DEFAULT 0,
                    tool_call_valid_rate REAL NOT NULL DEFAULT -1,
                    output_valid REAL NOT NULL DEFAULT -1,
                    user_accepted REAL NOT NULL DEFAULT -1,
                    test_pass_rate REAL NOT NULL DEFAULT -1,
                    verification_passed REAL NOT NULL DEFAULT -1,
                    node_id TEXT NOT NULL DEFAULT '',
                    hardware TEXT NOT NULL DEFAULT '',
                    runtime_load REAL NOT NULL DEFAULT 0,
                    time_of_day_hour INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    fallback_model_id TEXT NOT NULL DEFAULT '',
                    error_category TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    payload TEXT NOT NULL DEFAULT '{}',
                    schema_version TEXT NOT NULL DEFAULT '1.0.0'
                )
            """)
            for col in ("model_id", "provider_id", "capability_id", "task_type",
                         "outcome", "timestamp"):
                try:
                    self._db.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_mobs_{col} "
                        f"ON model_observations({col})"
                    )
                except Exception:
                    pass
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to init observation DB: %s", e)
            self._db = None

    def _persist(self, obs: ModelObservation) -> None:
        self._ensure_db()
        if self._db is None:
            return
        try:
            payload = json.dumps(obs.to_dict(), ensure_ascii=False)
            self._db.execute(
                """INSERT OR REPLACE INTO model_observations
                   (observation_id, timestamp, model_id, provider_id, model_version,
                    quantization, task_type, capability_id, task_id, trace_id,
                    session_id, outcome, latency_ms, time_to_first_token_ms,
                    tokens_per_second, prompt_tokens, completion_tokens, total_tokens,
                    cost_usd, cost_per_1k_tokens, tool_call_valid_rate, output_valid,
                    user_accepted, test_pass_rate, verification_passed, node_id,
                    hardware, runtime_load, time_of_day_hour, retry_count,
                    fallback_used, fallback_model_id, error_category, error_message,
                    tags, metadata, payload, schema_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obs.observation_id, obs.timestamp, obs.model_id, obs.provider_id,
                    obs.model_version, obs.quantization, obs.task_type.value,
                    obs.capability_id, obs.task_id, obs.trace_id, obs.session_id,
                    obs.outcome.value, obs.latency_ms, obs.time_to_first_token_ms,
                    obs.tokens_per_second, obs.prompt_tokens, obs.completion_tokens,
                    obs.total_tokens, obs.cost_usd, obs.cost_per_1k_tokens,
                    obs.tool_call_valid_rate, obs.output_valid, obs.user_accepted,
                    obs.test_pass_rate, obs.verification_passed, obs.node_id,
                    obs.hardware, obs.runtime_load, obs.time_of_day_hour,
                    obs.retry_count, int(obs.fallback_used), obs.fallback_model_id,
                    obs.error_category, obs.error_message,
                    json.dumps(obs.tags), json.dumps(obs.metadata),
                    payload, obs.schema_version,
                ),
            )
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to persist observation %s: %s", obs.observation_id, e)


# Singleton

_store_instance: ModelObservationStore | None = None
_store_lock = threading.Lock()


def get_observation_store(workspace_root: str = "") -> ModelObservationStore:
    global _store_instance
    if _store_instance is not None:
        return _store_instance
    with _store_lock:
        if _store_instance is not None:
            return _store_instance
        _store_instance = ModelObservationStore(workspace_root=workspace_root)
        return _store_instance


def reset_observation_store() -> None:
    global _store_instance
    with _store_lock:
        if _store_instance is not None:
            _store_instance.shutdown()
        _store_instance = None


atexit.register(reset_observation_store)


# Helpers

def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute a percentile from sorted values."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_values):
        return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
    return sorted_values[f]


__all__ = [
    "ModelObservation",
    "ModelObservationStore",
    "ModelPerformanceSummary",
    "ObservationOutcome",
    "TaskCategory",
    "get_observation_store",
    "reset_observation_store",
]

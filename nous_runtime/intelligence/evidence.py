# -*- coding: utf-8 -*-
"""
Model Evidence Ledger for Nous Runtime.

Implements §12 (Model Evidence Ledger) of the master plan.

Every model execution instance is tracked with:
- Provider, model ID, version, quantization, inference runtime, hardware
- Task type, input scale, node, latency, tokens, cost
- Tool call validity, execution success, test pass rate
- Reviewer results, user acceptance, modification rate
- Long-term drift detection

Four evidence levels (L1-L4):
    L1 — Vendor claims
    L2 — Nous standard calibration
    L3 — User real task results
    L4 — Long-term drift and version changes

No fake global score — capability profiles are conditional and contextual.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.intelligence.evidence")


# Execution Instance

@dataclass
class ExecutionInstance:
    """A single model execution record for evidence tracking.

    Captures the complete execution context: which exact model binary,
    on which hardware, with what config, doing what task, with what result.
    """

    instance_id: str = field(default_factory=lambda: make_id(prefix="exe"))

    # Model identity (exact — §12 principle)
    provider: str = ""                   # e.g., "openai", "ollama", "llama.cpp"
    model_id: str = ""                   # e.g., "gpt-4", "qwen2.5:14b"
    model_version: str = ""              # e.g., "gpt-4-0613"
    quantization: str = ""               # e.g., "Q4_K_M", "" for API models
    inference_runtime: str = ""          # e.g., "llama.cpp", "vLLM", "openai-api"
    hardware: str = ""                   # e.g., "RTX 3070 Laptop", "cloud"
    context_config: str = ""             # e.g., "8K", "32K"
    endpoint: str = ""                   # API endpoint or local address

    # Task context
    task_type: str = ""                  # code_fix, data_analysis, etc.
    task_fingerprint_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    node_id: str = ""

    # Performance
    latency_ms: int = 0
    first_token_ms: int = 0
    cost_cents: int = 0
    vram_mb_used: int = 0
    retry_count: int = 0

    # Quality signals
    tool_call_valid_rate: float = 0.0    # 0.0–1.0
    tool_execution_success_rate: float = 0.0
    test_pass_rate: float = 0.0
    reviewer_result: str = ""            # pass / fail / warn
    user_accepted: bool = False
    user_modification_ratio: float = 0.0
    completed: bool = False

    # Timestamps
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "model": {
                "provider": self.provider,
                "model_id": self.model_id,
                "version": self.model_version,
                "quantization": self.quantization,
                "inference_runtime": self.inference_runtime,
                "hardware": self.hardware,
                "context_config": self.context_config,
            },
            "task": {
                "type": self.task_type,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
            "performance": {
                "latency_ms": self.latency_ms,
                "first_token_ms": self.first_token_ms,
                "cost_cents": self.cost_cents,
                "vram_mb_used": self.vram_mb_used,
            },
            "quality": {
                "tool_call_valid_rate": self.tool_call_valid_rate,
                "tool_execution_success_rate": self.tool_execution_success_rate,
                "test_pass_rate": self.test_pass_rate,
                "reviewer_result": self.reviewer_result,
                "user_accepted": self.user_accepted,
                "user_modification_ratio": self.user_modification_ratio,
                "completed": self.completed,
            },
        }


# Capability Profile

@dataclass
class CapabilityProfile:
    """Evidence-derived capability profile for a model instance.

    Profiles are per exact instance (model + quantization + runtime + hardware).
    They show conditional capabilities, not a fake global score (§12.3).
    """

    profile_id: str = field(default_factory=lambda: make_id(prefix="profile"))
    instance_key: str = ""               # Unique key: provider/model/quant/runtime/hw

    sample_count: int = 0

    # Task-type-specific success rates
    python_fix_success_rate: float = 0.0
    cpp_ability_rate: float = 0.0
    tool_call_valid_rate: float = 0.0
    chinese_quality_score: float = 0.0
    long_context_retention: float = 0.0

    # Cost efficiency
    cost_per_successful_task_cents: float = 0.0
    first_token_latency_avg_ms: float = 0.0
    total_completion_time_avg_ms: float = 0.0

    # Reliability
    failure_recovery_rate: float = 0.0
    consistency_score: float = 0.0

    # Confidence
    confidence_interval: float = 0.0     # 95% CI width
    evidence_level: int = 0              # 0=no data, 1=declared, 2=calibrated, 3=empirical, 4=drift-aware

    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "instance_key": self.instance_key,
            "sample_count": self.sample_count,
            "capabilities": {
                "python_fix_success_rate": self.python_fix_success_rate,
                "cpp_ability_rate": self.cpp_ability_rate,
                "tool_call_valid_rate": self.tool_call_valid_rate,
                "chinese_quality_score": self.chinese_quality_score,
                "long_context_retention": self.long_context_retention,
            },
            "cost_efficiency": {
                "cost_per_successful_task_cents": self.cost_per_successful_task_cents,
                "first_token_latency_avg_ms": self.first_token_latency_avg_ms,
                "total_completion_time_avg_ms": self.total_completion_time_avg_ms,
            },
            "reliability": {
                "failure_recovery_rate": self.failure_recovery_rate,
                "consistency_score": self.consistency_score,
            },
            "confidence": {
                "interval": self.confidence_interval,
                "evidence_level": self.evidence_level,
            },
            "updated_at": self.updated_at,
        }


# Declared Capability (L1)

@dataclass
class DeclaredCapability:
    """Vendor-claimed model capability (L1 evidence)."""
    provider: str = ""
    model_id: str = ""
    context_length: int = 0
    modalities: list[str] = field(default_factory=list)  # text, image, audio
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_reasoning: bool = False
    price_per_1k_input: float = 0.0
    price_per_1k_output: float = 0.0
    rate_limit_per_minute: int = 0
    declared_at: str = ""


def _profile_from_json(raw: str) -> CapabilityProfile:
    """Load current flat storage and legacy nested profile snapshots."""
    data = json.loads(raw or "{}")
    if "capabilities" not in data:
        return CapabilityProfile(**data)
    confidence = dict(data.get("confidence") or {})
    flattened: dict[str, Any] = {
        "profile_id": data.get("profile_id", ""),
        "instance_key": data.get("instance_key", ""),
        "sample_count": data.get("sample_count", 0),
        "updated_at": data.get("updated_at", ""),
        "confidence_interval": confidence.get("interval", 0.0),
        "evidence_level": confidence.get("evidence_level", 0),
    }
    for section in ("capabilities", "cost_efficiency", "reliability"):
        flattened.update(dict(data.get(section) or {}))
    return CapabilityProfile(**flattened)

# Evidence Ledger

class EvidenceLedger:
    """Persistent evidence store for model execution tracking.

    Records L1 (declared), L2 (calibration), L3 (empirical), L4 (drift-aware)
    evidence for each exact model instance.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with closing(self._get_conn()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    instance_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL DEFAULT '',
                    quantization TEXT NOT NULL DEFAULT '',
                    inference_runtime TEXT NOT NULL DEFAULT '',
                    hardware TEXT NOT NULL DEFAULT '',
                    context_config TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    first_token_ms INTEGER NOT NULL DEFAULT 0,
                    cost_cents INTEGER NOT NULL DEFAULT 0,
                    vram_mb_used INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    tool_call_valid_rate REAL NOT NULL DEFAULT 0.0,
                    test_pass_rate REAL NOT NULL DEFAULT 0.0,
                    reviewer_result TEXT NOT NULL DEFAULT '',
                    user_accepted INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    profile_id TEXT PRIMARY KEY,
                    instance_key TEXT NOT NULL UNIQUE,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS declared (
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    context_length INTEGER NOT NULL DEFAULT 0,
                    modalities TEXT NOT NULL DEFAULT '[]',
                    supports_tools INTEGER NOT NULL DEFAULT 0,
                    price_per_1k_input REAL NOT NULL DEFAULT 0.0,
                    price_per_1k_output REAL NOT NULL DEFAULT 0.0,
                    declared_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (provider, model_id)
                )
            """)
            conn.commit()

    def _instance_key(self, instance: ExecutionInstance) -> str:
        return f"{instance.provider}/{instance.model_id}/{instance.quantization}/{instance.inference_runtime}/{instance.hardware}"

    # L1: Declared

    def record_declared(self, cap: DeclaredCapability) -> NousResult[None]:
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO declared
                           (provider, model_id, context_length, modalities,
                            supports_tools, price_per_1k_input, price_per_1k_output, declared_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (cap.provider, cap.model_id, cap.context_length,
                         json.dumps(cap.modalities),
                         1 if cap.supports_tools else 0,
                         cap.price_per_1k_input, cap.price_per_1k_output,
                         datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
                return NousResult.ok(None)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    # L3: Record execution

    def record_execution(self, instance: ExecutionInstance) -> NousResult[str]:
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    conn.execute(
                        """INSERT INTO executions VALUES
                           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (instance.instance_id, instance.provider, instance.model_id,
                         instance.model_version, instance.quantization,
                         instance.inference_runtime, instance.hardware,
                         instance.context_config, instance.task_type,
                         instance.input_tokens, instance.output_tokens,
                         instance.latency_ms, instance.first_token_ms,
                         instance.cost_cents, instance.vram_mb_used,
                         instance.retry_count,
                         instance.tool_call_valid_rate,
                         instance.test_pass_rate,
                         instance.reviewer_result,
                         1 if instance.user_accepted else 0,
                         1 if instance.completed else 0,
                         instance.started_at, instance.completed_at),
                    )
                    conn.commit()
                self._update_profile(instance)
                return NousResult.ok(instance.instance_id)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def _update_profile(self, instance: ExecutionInstance) -> None:
        """Update the capability profile for this exact instance."""
        key = self._instance_key(instance)

        with closing(self._get_conn()) as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE instance_key = ?", (key,)
            ).fetchone()

            if row:
                profile = _profile_from_json(row["profile_json"])
            else:
                profile = CapabilityProfile(instance_key=key)
                profile.profile_id = make_id(prefix="profile")

            profile.sample_count += 1
            # Update running averages
            n = profile.sample_count
            profile.tool_call_valid_rate = (
                (profile.tool_call_valid_rate * (n - 1) + instance.tool_call_valid_rate) / n
            )
            if instance.task_type in {"code_fix", "python", "python_fix"}:
                profile.python_fix_success_rate = (
                    (profile.python_fix_success_rate * (n - 1) + instance.test_pass_rate) / n
                )
            else:
                profile.consistency_score = (
                    (profile.consistency_score * (n - 1) + instance.test_pass_rate) / n
                )
            profile.first_token_latency_avg_ms = (
                (profile.first_token_latency_avg_ms * (n - 1) + instance.first_token_ms) / n
            )
            profile.cost_per_successful_task_cents = (
                (profile.cost_per_successful_task_cents * (n - 1) +
                 (instance.cost_cents if instance.completed else 0)) / n
            )
            if instance.completed:
                profile.failure_recovery_rate = (
                    (profile.failure_recovery_rate * (n - 1) + (1.0 if instance.retry_count == 0 else 0.0)) / n
                )
            profile.evidence_level = 3  # L3 empirical
            profile.updated_at = datetime.now(timezone.utc).isoformat()

            conn.execute(
                """INSERT OR REPLACE INTO profiles
                   (profile_id, instance_key, sample_count, profile_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (profile.profile_id, key, profile.sample_count,
                 json.dumps(asdict(profile)), profile.updated_at),
            )
            conn.commit()

    # Query

    def get_profile(self, instance_key: str) -> NousResult[CapabilityProfile]:
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    row = conn.execute(
                        "SELECT * FROM profiles WHERE instance_key = ?", (instance_key,)
                    ).fetchone()
                if row is None:
                    return NousResult.err(ErrorCode.NOT_FOUND,
                                          message=f"No profile for '{instance_key}'")
                profile = _profile_from_json(row["profile_json"])
                return NousResult.ok(profile)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def list_profiles(self, min_samples: int = 1) -> NousResult[list[CapabilityProfile]]:
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    rows = conn.execute(
                        "SELECT * FROM profiles WHERE sample_count >= ? ORDER BY sample_count DESC",
                        (min_samples,),
                    ).fetchall()
                return NousResult.ok([
                    _profile_from_json(r["profile_json"]) for r in rows
                ])
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def get_executions_for_model(self, provider: str, model_id: str,
                                  limit: int = 100) -> NousResult[list[dict]]:
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    rows = conn.execute(
                        """SELECT * FROM executions
                           WHERE provider = ? AND model_id = ?
                           ORDER BY started_at DESC LIMIT ?""",
                        (provider, model_id, limit),
                    ).fetchall()
                return NousResult.ok([dict(r) for r in rows])
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def count(self) -> int:
        with self._lock:
            with closing(self._get_conn()) as conn:
                return conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]

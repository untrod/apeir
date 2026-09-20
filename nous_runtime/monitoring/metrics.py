# -*- coding: utf-8 -*-
"""Metrics Collector — runtime telemetry."""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("nous.monitoring")

@dataclass
class RuntimeMetrics:
    timestamp: str = ""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    active_tasks: int = 0
    online_nodes: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_agents: int = 0
    total_experiences: int = 0
    uptime_seconds: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp, "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb, "active_tasks": self.active_tasks,
            "online_nodes": self.online_nodes, "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms, "total_agents": self.total_agents,
            "total_experiences": self.total_experiences, "uptime_seconds": self.uptime_seconds,
        }

class MetricsCollector:
    """Collects runtime metrics from all subsystems."""
    def __init__(self, workspace: str = ""):
        self._workspace = workspace
        self._start_time = time.time()

    def collect(self) -> RuntimeMetrics:
        from datetime import datetime, timezone
        m = RuntimeMetrics(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            uptime_seconds=int(time.time() - self._start_time),
        )
        # CPU/Memory
        try:
            import psutil
            m.cpu_percent = psutil.cpu_percent(interval=0.1)
            m.memory_mb = round(psutil.Process().memory_info().rss / (1024*1024), 1)
        except ImportError:
            pass
        # Network
        try:
            from nous_runtime.network.discovery import AgentDiscovery
            from nous_runtime.network.registry import NetworkRegistry
            summary = AgentDiscovery(NetworkRegistry(self._workspace)).network_summary()
            m.online_nodes = summary["online_nodes"]
            m.total_agents = summary["total_nodes"]
        except Exception:
            pass
        # Experience
        try:
            from nous_runtime.experience.store import ExperienceStore
            stats = ExperienceStore(self._workspace).stats()
            m.total_experiences = stats.get("total_experiences", 0)
            m.success_rate = stats.get("success_rate", 0.0)
        except Exception:
            pass
        return m

    def snapshot(self) -> dict[str, Any]:
        return self.collect().to_dict()

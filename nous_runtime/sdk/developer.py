"""Bounded developer tools over authoritative Runtime evidence."""

from __future__ import annotations

import hashlib
import json
import re
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from nous_runtime.events.stream import EventStream

_NAME = re.compile(r"[a-z][a-z0-9_]{1,62}")


@dataclass(frozen=True)
class ReplayReport:
    run_id: str
    event_count: int
    first_sequence: int
    last_sequence: int
    monotonic: bool
    terminal_events: tuple[str, ...]
    checksum: str
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeReplay:
    """Read and verify canonical EventStream evidence without re-executing work."""

    def __init__(self, root: str | Path = ".") -> None:
        self.events = EventStream(str(root))

    def inspect(self, run_id: str, *, after_sequence: int = 0, limit: int = 1000) -> ReplayReport:
        if not 1 <= limit <= 10_000:
            raise ValueError("replay limit must be between 1 and 10000")
        events = list(
            self.events.iter_persisted_events(run_id, after_sequence=after_sequence, limit=limit + 1)
        )
        truncated = len(events) > limit
        events = events[:limit]
        sequences = [event.sequence for event in events]
        terminal = tuple(
            event.event_type
            for event in events
            if event.event_type
            in {"run.completed", "run.failed", "run.cancelled", "runtime.response.ready"}
        )
        checksum = hashlib.sha256(
            "\n".join(
                json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
                for event in events
            ).encode("utf-8")
        ).hexdigest()
        return ReplayReport(
            run_id,
            len(events),
            sequences[0] if sequences else 0,
            sequences[-1] if sequences else 0,
            sequences == sorted(set(sequences)),
            terminal,
            checksum,
            truncated,
        )


@dataclass(frozen=True)
class ProfileReport:
    name: str
    iterations: int
    successes: int
    failures: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    peak_memory_bytes: int
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeProfiler:
    """Bounded local profiler suitable for subsystem smoke benchmarks."""

    def profile(
        self,
        name: str,
        operation: Callable[[], Any],
        *,
        iterations: int = 1,
        warmup: int = 0,
    ) -> ProfileReport:
        if not 1 <= iterations <= 1000:
            raise ValueError("iterations must be between 1 and 1000")
        if not 0 <= warmup <= 20:
            raise ValueError("warmup must be between 0 and 20")
        for _ in range(warmup):
            operation()
        latencies: list[float] = []
        errors: list[str] = []
        tracemalloc.start()
        try:
            for _ in range(iterations):
                started = time.perf_counter()
                try:
                    operation()
                except Exception as exc:
                    errors.append(str(exc)[:500])
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        ordered = sorted(latencies)
        return ProfileReport(
            name,
            iterations,
            iterations - len(errors),
            len(errors),
            self._percentile(ordered, 0.50),
            self._percentile(ordered, 0.95),
            self._percentile(ordered, 0.99),
            peak,
            tuple(errors[:20]),
        )

    @staticmethod
    def _percentile(values: list[float], quantile: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
        return round(values[index], 3)


def render_template(kind: str, name: str) -> dict[str, str]:
    """Return safe, reviewable files; callers explicitly decide whether to write."""
    if not _NAME.fullmatch(name):
        raise ValueError("template name must be lower snake_case")
    json_templates = {
        "workflow": {"workflow_id": name, "version": "0.1.0", "steps": [{"step_id": "start", "type": "transform", "action": "identity"}]},
        "agent": {"agent_id": name, "version": "0.1.0", "capabilities": [], "permissions": []},
        "plugin": {"plugin_id": name, "version": "0.1.0", "capabilities": [], "permissions": []},
        "connector": {"connector_id": name, "version": "0.1.0", "authentication_type": "none", "actions": [], "data_boundary": "workspace"},
        "provider": {"provider_id": name, "kind": "openai-compatible", "credential_ref": f"env:{name.upper()}_API_KEY", "capability_mapping": ["model.reason"]},
        "runtime": {"name": name, "version": "0.1.0", "workspace": ".", "providers": []},
    }
    if kind == "capability":
        return {
            f"{name}.py": f"from __future__ import annotations\n\ndef {name}(payload: dict) -> dict:\n    return dict(payload)\n",
            f"test_{name}.py": f"from {name} import {name}\n\ndef test_{name}():\n    assert {name}({{'ok': True}}) == {{'ok': True}}\n",
        }
    if kind not in json_templates:
        raise ValueError("template kind must be capability, workflow, agent, plugin, connector, provider, or runtime")
    return {f"{name}.json": json.dumps(json_templates[kind], indent=2) + "\n"}
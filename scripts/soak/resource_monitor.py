"""Resource sampling utilities for Nous Runtime soak tests."""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ResourceSample:
    timestamp: float
    rss_mb: float | None
    vms_mb: float | None
    cpu_percent: float | None
    disk_bytes: int
    sqlite_bytes: int

    def to_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _sqlite_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*.db*"):
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


class ResourceMonitor:
    """Collect process and workspace resource samples."""

    def __init__(self, workspace: str | Path, pid: int | None = None):
        self.workspace = Path(workspace)
        self.pid = pid or os.getpid()
        self._process = None
        try:
            import psutil  # type: ignore

            self._process = psutil.Process(self.pid)
            self._process.cpu_percent(interval=None)
        except Exception:
            self._process = None

    def sample(self) -> ResourceSample:
        rss_mb = vms_mb = cpu_percent = None
        if self._process is not None:
            try:
                info = self._process.memory_info()
                rss_mb = round(info.rss / 1024 / 1024, 3)
                vms_mb = round(info.vms / 1024 / 1024, 3)
                cpu_percent = round(float(self._process.cpu_percent(interval=None)), 3)
            except Exception:
                rss_mb = vms_mb = cpu_percent = None
        return ResourceSample(
            timestamp=time.time(),
            rss_mb=rss_mb,
            vms_mb=vms_mb,
            cpu_percent=cpu_percent,
            disk_bytes=_dir_size(self.workspace),
            sqlite_bytes=_sqlite_size(self.workspace),
        )


def summarize(samples: Iterable[ResourceSample]) -> dict[str, float | int | bool | None]:
    data = list(samples)
    if not data:
        return {"samples": 0}

    def values(name: str) -> list[float]:
        return [float(getattr(sample, name)) for sample in data if getattr(sample, name) is not None]

    rss = values("rss_mb")
    cpu = values("cpu_percent")
    disk = [sample.disk_bytes for sample in data]
    sqlite = [sample.sqlite_bytes for sample in data]
    return {
        "samples": len(data),
        "rss_start_mb": rss[0] if rss else None,
        "rss_end_mb": rss[-1] if rss else None,
        "rss_max_mb": max(rss) if rss else None,
        "rss_growth_mb": round(rss[-1] - rss[0], 3) if len(rss) >= 2 else None,
        "cpu_mean_percent": round(sum(cpu) / len(cpu), 3) if cpu else None,
        "cpu_max_percent": max(cpu) if cpu else None,
        "disk_start_bytes": disk[0],
        "disk_end_bytes": disk[-1],
        "sqlite_start_bytes": sqlite[0],
        "sqlite_end_bytes": sqlite[-1],
    }


def sqlite_integrity(workspace: str | Path) -> dict[str, object]:
    results = []
    for db_path in Path(workspace).rglob("*.db"):
        try:
            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
            ok = bool(row and row[0] == "ok")
            results.append({"path": db_path.name, "ok": ok, "result": row[0] if row else "missing"})
        except Exception as exc:
            results.append({"path": db_path.name, "ok": False, "error": str(exc)})
    return {"checked": len(results), "ok": all(item.get("ok") for item in results), "databases": results}
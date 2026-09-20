"""Measure Nous Runtime memory and idle CPU profiles."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

MODULE_SETS = {
    "kernel_only": ["nous_runtime.kernel.runtime"],
    "kernel_agent": ["nous_runtime.kernel.runtime", "nous_runtime.agent"],
    "kernel_context": ["nous_runtime.kernel.runtime", "nous_runtime.context"],
    "kernel_network": ["nous_runtime.kernel.runtime", "nous_runtime.network"],
    "kernel_experience": ["nous_runtime.kernel.runtime", "nous_runtime.experience"],
    "full_runtime": [
        "nous_runtime.kernel.runtime",
        "nous_runtime.agent",
        "nous_runtime.context",
        "nous_runtime.evaluation",
        "nous_runtime.experience",
        "nous_runtime.network",
        "nous_runtime.governance",
    ],
}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _child_profile(modules: list[str], idle_seconds: float) -> dict[str, Any]:
    import importlib

    try:
        import psutil  # type: ignore
    except Exception:
        psutil = None

    for module in modules:
        importlib.import_module(module)

    if psutil is None:
        return {"rss_mb": None, "vms_mb": None, "cpu_idle_percent": None, "psutil": False}

    proc = psutil.Process(os.getpid())
    proc.cpu_percent(interval=None)
    samples = []
    deadline = time.time() + idle_seconds
    while time.time() < deadline:
        samples.append(proc.cpu_percent(interval=0.25))
    info = proc.memory_info()
    return {
        "rss_mb": round(info.rss / 1024 / 1024, 2),
        "vms_mb": round(info.vms / 1024 / 1024, 2),
        "cpu_idle_percent": round(statistics.mean(samples), 3) if samples else 0.0,
        "cpu_max_percent": round(max(samples), 3) if samples else 0.0,
        "samples": len(samples),
        "psutil": True,
    }


def _run_child(name: str, modules: list[str], idle_seconds: float) -> dict[str, Any]:
    code = f"""
import json
from scripts.benchmark.resource_benchmark import _child_profile
print(json.dumps(_child_profile({modules!r}, {idle_seconds!r}), ensure_ascii=False))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=_env(),
        text=True,
        capture_output=True,
        timeout=max(20, int(idle_seconds) + 10),
    )
    if proc.returncode != 0:
        return {"name": name, "error": proc.stderr[-1000:]}
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    data["name"] = name
    data["modules"] = modules
    return data


def run(idle_seconds: float = 5.0) -> dict[str, Any]:
    profiles = [_run_child(name, modules, idle_seconds) for name, modules in MODULE_SETS.items()]
    return {
        "benchmark": "resource_footprint",
        "targets": {"base_rss_mb": 200, "ideal_rss_mb": 100, "idle_cpu_percent": 2.0},
        "idle_sample_seconds": idle_seconds,
        "profiles": profiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--idle-seconds", type=float, default=5.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run(max(1.0, args.idle_seconds))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
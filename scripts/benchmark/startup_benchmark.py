"""Benchmark Nous Runtime startup readiness.

Outputs JSON suitable for release reports and CI trend tracking.
"""

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


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_python(code: str) -> tuple[float, int, str, str]:
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    return time.perf_counter() - start, proc.returncode, proc.stdout, proc.stderr


def _run_cli(args: list[str]) -> tuple[float, int, str, str]:
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", *args],
        cwd=str(ROOT),
        env=_env(),
        text=True,
        capture_output=True,
        timeout=60,
    )
    return time.perf_counter() - start, proc.returncode, proc.stdout, proc.stderr


def _measure_code(name: str, code: str, rounds: int) -> dict[str, Any]:
    samples: list[float] = []
    errors: list[str] = []
    for _ in range(rounds):
        duration, rc, _out, err = _run_python(code)
        samples.append(duration)
        if rc != 0:
            errors.append(err[-500:])
    return _stats(name, samples, errors)


def _stats(name: str, samples: list[float], errors: list[str] | None = None) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "name": name,
        "rounds": len(samples),
        "min_s": round(min(samples), 4) if samples else 0.0,
        "median_s": round(statistics.median(samples), 4) if samples else 0.0,
        "mean_s": round(statistics.mean(samples), 4) if samples else 0.0,
        "max_s": round(max(samples), 4) if samples else 0.0,
        "p95_s": round(ordered[int(len(ordered) * 0.95) - 1], 4) if len(ordered) >= 20 else round(ordered[-1], 4) if ordered else 0.0,
        "errors": errors or [],
    }


def run(rounds: int = 3) -> dict[str, Any]:
    import_code = "import nous_runtime.cli.main; print('ok')"
    module_code = """
import importlib
modules = [
    'nous_runtime.kernel.runtime',
    'nous_runtime.agent',
    'nous_runtime.context',
    'nous_runtime.evaluation',
    'nous_runtime.experience',
    'nous_runtime.network',
    'nous_runtime.governance',
]
for module in modules:
    importlib.import_module(module)
print('ok')
"""
    db_code = """
import tempfile
from pathlib import Path
from nous_runtime.context.store import ContextStore
from nous_runtime.experience.store import ExperienceStore
with tempfile.TemporaryDirectory() as td:
    ws = Path(td) / '.nous'
    ContextStore(ws)
    ExperienceStore(ws)
print('ok')
"""
    daemon_code = """
import tempfile
from pathlib import Path
from nous_runtime.daemon.service import DaemonService
with tempfile.TemporaryDirectory() as td:
    svc = DaemonService(workspace=str(Path(td) / '.nous'))
    ok = svc.start()
    assert ok and svc.status()['running']
    svc.stop()
print('ok')
"""

    cli_samples: list[float] = []
    cli_errors: list[str] = []
    for _ in range(rounds + 1):
        duration, rc, _out, err = _run_cli(["runtime", "status", "--json"])
        cli_samples.append(duration)
        if rc != 0:
            cli_errors.append(err[-500:])

    cold_start = cli_samples[0]
    warm_samples = cli_samples[1:] or cli_samples

    return {
        "benchmark": "startup",
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "rounds": rounds,
        "targets": {"cold_start_s": 5.0, "warm_start_s": 2.0, "daemon_recovery_s": 5.0},
        "cold_start": round(cold_start, 4),
        "warm_start": round(statistics.median(warm_samples), 4),
        "cli_ready": _stats("cli_runtime_status", cli_samples, cli_errors),
        "import_time": _measure_code("import_cli_main", import_code, rounds),
        "module_loading": _measure_code("runtime_module_loading", module_code, rounds),
        "database_init": _measure_code("sqlite_store_init", db_code, rounds),
        "daemon_recovery": _measure_code("daemon_service_start", daemon_code, rounds),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run(rounds=max(1, args.rounds))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
"""Run the Phase 9.0 performance baseline benchmark set."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "release" / "performance"

COMMANDS = {
    "startup": [sys.executable, "scripts/benchmark/startup_benchmark.py", "--rounds", "3"],
    "resource": [sys.executable, "scripts/benchmark/resource_benchmark.py", "--idle-seconds", "3"],
    "database": [sys.executable, "scripts/benchmark/database_benchmark.py", "--records", "10000"],
    "scheduler": [sys.executable, "scripts/benchmark/scheduler_benchmark.py", "--tasks", "100", "--rounds", "100"],
    "model_runtime": [sys.executable, "scripts/benchmark/model_runtime_benchmark.py", "--rounds", "1000"],
    "test_suite": [sys.executable, "scripts/benchmark/test_suite_profile.py"],
}


def _run(name: str, command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=300)
    result: dict[str, Any] = {"name": name, "returncode": proc.returncode}
    if proc.returncode == 0:
        result["data"] = json.loads(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip().startswith("{") is False else proc.stdout)
    else:
        result["stderr"] = proc.stderr[-2000:]
        result["stdout"] = proc.stdout[-2000:]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Use smaller database benchmark for local iteration")
    parser.add_argument("--output", default=str(OUT / "phase9_baseline.json"))
    args = parser.parse_args()

    commands = dict(COMMANDS)
    if args.quick:
        commands["database"] = [sys.executable, "scripts/benchmark/database_benchmark.py", "--records", "1000"]

    results = [_run(name, command) for name, command in commands.items()]
    payload = {"benchmark": "phase9_performance_baseline", "quick": args.quick, "results": results}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
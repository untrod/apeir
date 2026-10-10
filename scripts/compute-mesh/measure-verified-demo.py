"""Measure the public, governed simulation CLI in fresh isolated workspaces."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


def quantiles(values):
    """Use empirical nearest-rank quantiles; small samples have coarse tails."""
    import math

    ordered = sorted(values)
    return {
        f"p{p}": ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)]
        for p in (50, 95, 99)
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("samples must be between 1 and 100")
    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    samples = []
    for index in range(args.samples):
        workspace = root / f"run-{index}"
        started = time.monotonic()
        with (
            (root / f"run-{index}.json").open("wb") as output,
            (root / f"run-{index}.stderr").open("wb") as errors,
        ):
            # Files avoid pipe backpressure from the complete evidence JSON.
            # Each invocation creates a distinct Work and approval; it never
            # retries a side effect in an existing workspace.
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "nous_runtime.cli.main",
                        "demo",
                        "--workspace",
                        str(workspace),
                        "--scenario",
                        "match",
                        "--approve-once",
                        "--json",
                    ],
                    stdout=output,
                    stderr=errors,
                    timeout=60,
                    check=False,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                exit_code = None
        elapsed = time.monotonic() - started
        try:
            evidence = json.loads((root / f"run-{index}.json").read_bytes())
        except (ValueError, OSError):
            evidence = {}
        work = evidence.get("work", {})
        verdict = evidence.get("effect_verification", {}).get("verdict", "UNKNOWN")
        passed = (
            exit_code == 0
            and work.get("state") == "COMMITTED"
            and verdict == "MATCH"
            and evidence.get("effect_count") == 1
        )
        samples.append(
            {
                "workspace": str(workspace),
                "work_id": work.get("work_id", ""),
                "exit_code": exit_code,
                "elapsed_seconds": elapsed,
                "state": work.get("state", "UNKNOWN"),
                "verdict": verdict,
                "effect_count": evidence.get("effect_count"),
                "passed": passed,
            }
        )
    report = {
        "scope": "Cloud/local loopback simulation; no hardware, NAT or native installation qualification",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clock": "observer-local-monotonic",
        "measurement": "complete CLI startup, governed execution and evidence output",
        "quantiles": "empirical nearest-rank; small samples do not establish production tail latency",
        "elapsed_seconds": quantiles([row["elapsed_seconds"] for row in samples]),
        "passed": sum(row["passed"] for row in samples),
        "samples": samples,
    }
    (root / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "evidence": str(root),
                "passed": report["passed"],
                "samples": len(samples),
                "elapsed_seconds": report["elapsed_seconds"],
            }
        )
    )
    return 0 if all(row["passed"] for row in samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())

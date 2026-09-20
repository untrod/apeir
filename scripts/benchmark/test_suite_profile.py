"""Audit current test-suite shape and proposed gate tiers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

TIER_RULES = {
    "unit": ["test_kernel", "test_capability", "test_provider", "test_planner", "test_learning"],
    "integration": ["test_integration", "test_connectivity", "context", "evaluation", "experience", "network"],
    "security": ["governance"],
    "runtime": ["test_cli", "test_architecture"],
    "release": ["release"],
}


def _tier_for(path: Path) -> str:
    rel = path.relative_to(TESTS)
    first = rel.parts[0] if rel.parts else path.name
    for tier, prefixes in TIER_RULES.items():
        if first in prefixes:
            return tier
    return "uncategorized"


def run() -> dict[str, Any]:
    files = sorted(TESTS.rglob("test_*.py"))
    tiers: dict[str, dict[str, Any]] = {}
    for file in files:
        tier = _tier_for(file)
        entry = tiers.setdefault(tier, {"files": 0, "examples": []})
        entry["files"] += 1
        if len(entry["examples"]) < 5:
            entry["examples"].append(str(file.relative_to(ROOT)))
    return {
        "benchmark": "test_suite_profile",
        "total_test_files": len(files),
        "tiers": tiers,
        "recommended_commands": {
            "fast_gate": "pytest tests/test_kernel tests/test_capability tests/test_provider tests/test_planner tests/test_learning",
            "ci_gate": "pytest tests/test_integration tests/test_connectivity tests/context tests/evaluation tests/experience tests/network tests/governance",
            "release_gate": "pytest -q && pytest -q -W error",
            "parallel_release_gate": "pytest -q -n auto",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    data = run()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
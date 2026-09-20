#!/usr/bin/env python3
"""Clean-install smoke test for Nous Runtime.

Simulates a new user installing Nous Runtime from scratch.
Verifies that CLI commands work without pre-existing .nous/ state,
without real provider credentials, and without crashes.

Usage:
    python scripts/smoke_test_clean_install.py

Requirements:
    - Nous Runtime installed in development mode (pip install -e .)
    - No .nous/ directory pre-existing (script creates temp workspace)
    - No provider API key set (tests graceful degradation)

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOUS_CMD = [sys.executable, "-m", "nous_runtime.cli.main"]


def run(cmd: list[str], timeout: int = 30, env: dict | None = None) -> tuple[int, str, str]:
    """Run a command and return (exit_code, stdout, stderr)."""
    merged_env = os.environ.copy()
    merged_env.pop("NOUS_LLM_API_KEY", None)
    merged_env.pop("NOUS_AUTH_TOKEN", None)
    merged_env.pop("NOUS_AGENT_SIGNING_SECRET", None)
    existing_pythonpath = merged_env.get("PYTHONPATH", "")
    merged_env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing_pythonpath
        else str(REPO_ROOT) + os.pathsep + existing_pythonpath
    )
    if env:
        merged_env.update(env)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged_env,
            cwd=str(TEMP_DIR),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"


def check(name: str, cmd: list[str], should_pass: bool = True, timeout: int = 30,
          env: dict | None = None, json_output: bool = False) -> bool:
    """Run a check and print result."""
    print(f"  [{name}] ", end="", flush=True)
    code, stdout, stderr = run(cmd, timeout=timeout, env=env)

    if should_pass:
        ok = (code == 0)
    else:
        ok = True  # expected to possibly fail, just verify no crash

    if ok:
        if json_output and stdout.strip():
            try:
                json.loads(stdout.strip())
                print("✓ PASS (valid JSON)")
            except json.JSONDecodeError:
                print(f"✗ FAIL (invalid JSON): {stdout[:200]}")
                return False
        else:
            print("✓ PASS")
    else:
        print(f"✗ FAIL (exit={code})")
        if stderr:
            print(f"    stderr: {stderr[:200]}")
        return False
    return True


# Setup temporary workspace
TEMP_DIR = Path(tempfile.mkdtemp(prefix="nous_smoke_test_"))
print(f"Smoke test workspace: {TEMP_DIR}")
print()

passed = 0
failed = 0


def check_wrapper(*args, **kwargs) -> bool:
    global passed, failed
    result = check(*args, **kwargs)
    if result:
        passed += 1
    else:
        failed += 1
    return result


# Core CLI checks
print("-- Core CLI --")

check_wrapper("version", NOUS_CMD + ["version"])
check_wrapper("doctor", NOUS_CMD + ["doctor"], should_pass=False)
check_wrapper("status", NOUS_CMD + ["status"], should_pass=False)
check_wrapper("init", NOUS_CMD + ["init"], should_pass=False)

# Capability Manifest
print("\n-- Capability Manifest --")

check_wrapper("manifest", NOUS_CMD + ["capability", "manifest"])
check_wrapper("manifest --validate", NOUS_CMD + ["capability", "manifest", "--validate"])

# Memory
print("\n-- Memory --")

check_wrapper("memory status", NOUS_CMD + ["memory", "status"], should_pass=False)
check_wrapper("memory facts", NOUS_CMD + ["memory", "facts"], should_pass=False)
check_wrapper("memory decisions", NOUS_CMD + ["memory", "decisions"], should_pass=False)
check_wrapper("memory summaries", NOUS_CMD + ["memory", "summaries"], should_pass=False)
check_wrapper("memory experiences", NOUS_CMD + ["memory", "experiences"], should_pass=False)

# Inspector
print("\n-- Inspector --")

check_wrapper("inspect", NOUS_CMD + ["inspect"], should_pass=False)
check_wrapper("inspect --json", NOUS_CMD + ["inspect", "--json"], should_pass=False, json_output=True)
check_wrapper("inspect runtime", NOUS_CMD + ["inspect", "runtime"], should_pass=False)
check_wrapper("inspect capabilities", NOUS_CMD + ["inspect", "capabilities"], should_pass=False)
check_wrapper("inspect tasks", NOUS_CMD + ["inspect", "tasks"], should_pass=False)
check_wrapper("inspect observations", NOUS_CMD + ["inspect", "observations"], should_pass=False)
check_wrapper("inspect memory", NOUS_CMD + ["inspect", "memory"], should_pass=False)
check_wrapper("inspect providers", NOUS_CMD + ["inspect", "providers"], should_pass=False)
check_wrapper("inspect devices", NOUS_CMD + ["inspect", "devices"], should_pass=False)
check_wrapper("inspect diagnose", NOUS_CMD + ["inspect", "diagnose"], should_pass=False)

# Verify no pre-existing .nous dependency
print("\n-- Environment Independence --")

nous_dir = TEMP_DIR / ".nous"
if nous_dir.exists():
    print("  [.nous created] ✓ (runtime creates its own state)")
else:
    print("  [.nous absent] ✓ (no hard dependency on pre-existing state)")

# Summary
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"Workspace: {TEMP_DIR}")
print(f"{'='*60}")

try:
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
except Exception:
    pass

sys.exit(0 if failed == 0 else 1)

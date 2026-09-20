from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _run_probe(
    source: str,
    tmp_path: Path,
    *,
    startup_timeout: float = 30.0,
    shutdown_timeout: float = 5.0,
) -> tuple[dict, float]:
    marker = tmp_path / "probe-ready.json"
    wrapped = (
        source
        + """
Path(sys.argv[1]).write_text(
    json.dumps(result),
    encoding="utf-8",
)
"""
    )
    process = subprocess.Popen(
        [sys.executable, "-c", wrapped, str(marker)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    startup_deadline = time.monotonic() + startup_timeout
    while not marker.is_file():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                f"probe exited before ready: {process.returncode}\n"
                f"stdout={stdout}\nstderr={stderr}"
            )
        if time.monotonic() >= startup_deadline:
            process.kill()
            stdout, stderr = process.communicate()
            pytest.fail(
                f"probe did not become ready in {startup_timeout}s\n"
                f"stdout={stdout}\nstderr={stderr}"
            )
        time.sleep(0.02)

    result = json.loads(marker.read_text(encoding="utf-8"))
    shutdown_started = time.monotonic()
    try:
        stdout, stderr = process.communicate(timeout=shutdown_timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        pytest.fail(
            f"probe did not exit in {shutdown_timeout}s after ready\n"
            f"stdout={stdout}\nstderr={stderr}"
        )
    shutdown_seconds = time.monotonic() - shutdown_started
    assert process.returncode == 0, stderr
    return result, shutdown_seconds


def test_context_build_process_exits_without_runtime_resources(
    tmp_path,
) -> None:
    result, shutdown_seconds = _run_probe(
        """
import asyncio
import json
import multiprocessing
import sys
import threading
from pathlib import Path

from nous_runtime.context import BuildRequest, build_context

snapshot = build_context(BuildRequest(intent="shutdown probe"), workspace="")
loop = asyncio.new_event_loop()
try:
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
finally:
    loop.close()
non_daemon = [
    thread.name
    for thread in threading.enumerate()
    if thread is not threading.main_thread()
    and thread.is_alive()
    and not thread.daemon
]
result = {
    "snapshot_id": snapshot.id,
    "non_daemon_threads": non_daemon,
    "pending_asyncio_tasks": len(pending),
    "child_processes": len(multiprocessing.active_children()),
}
""",
        tmp_path,
    )

    assert result["snapshot_id"]
    assert result["non_daemon_threads"] == []
    assert result["pending_asyncio_tasks"] == 0
    assert result["child_processes"] == 0
    assert shutdown_seconds < 5.0


def test_cli_help_process_exits_cleanly(tmp_path) -> None:
    result, shutdown_seconds = _run_probe(
        """
import json
import subprocess
import sys
from pathlib import Path

completed = subprocess.run(
    [sys.executable, "-m", "nous_runtime.cli.main", "--help"],
    capture_output=True,
    text=True,
    timeout=15,
)
result = {
    "returncode": completed.returncode,
    "has_usage": "Usage:" in completed.stdout,
    "stderr": completed.stderr,
}
""",
        tmp_path,
    )

    assert result["returncode"] == 0
    assert result["has_usage"]
    assert result["stderr"] == ""
    assert shutdown_seconds < 5.0

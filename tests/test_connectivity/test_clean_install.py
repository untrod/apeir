# -*- coding: utf-8 -*-
"""Clean-wheel install smoke test — runs CLI commands after pip install."""

import subprocess
import sys


def test_nous_help():
    """nous --help exits cleanly."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "nous" in result.stdout.lower() or "Usage" in result.stdout


def test_server_help():
    """nous server --help exits cleanly and shows commands."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "server", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "init" in result.stdout
    assert "start" in result.stdout
    assert "status" in result.stdout


def test_node_help():
    """nous node --help exits cleanly."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "node", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "pair" in result.stdout
    assert "list" in result.stdout
    assert "revoke" in result.stdout


def test_task_help():
    """nous task --help exits cleanly."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "task", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "submit" in result.stdout
    assert "list" in result.stdout


def test_server_status_empty():
    """nous server status shows empty state gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "server", "status"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "stopped" in result.stdout.lower() or "0" in result.stdout


def test_node_list_empty():
    """nous node list shows empty gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "node", "list"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # Either "No nodes" or empty output is acceptable


def test_task_list_empty():
    """nous task list shows empty gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "task", "list"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_server_init_status():
    """nous server init → status works."""
    # Init
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "server", "init",
         "--host", "127.0.0.1", "--port", "19999"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "initialized" in result.stdout.lower()

    # Status
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "server", "status"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0


def test_no_raw_tracebacks():
    """CLI errors don't produce raw tracebacks."""
    result = subprocess.run(
        [sys.executable, "-m", "nous_runtime.cli.main", "task", "show", "nonexistent"],
        capture_output=True, text=True, timeout=15,
    )
    assert "Traceback" not in result.stdout
    # Either clean error message or empty output
    if result.returncode != 0:
        assert "Traceback" not in result.stderr

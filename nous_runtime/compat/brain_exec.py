# -*- coding: utf-8 -*-
"""Compatibility shim for brain.py PC execution functions.

Provides _exec_raw and is_device_online without importing brain.py directly.
Once brain.py is fully decomposed, these can be replaced by native capability
implementations.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("nous.compat.brain_exec")


def _exec_raw(
    command: str, device_id: str = "", timeout: int = 30, cwd: str | None = None
) -> tuple[str, int]:
    """Execute a raw shell command on the given device.

    If device_id matches the local machine (or is empty), runs locally.
    Otherwise delegates to the remote agent.

    Returns (output, returncode).
    """
    # Try the compat path first
    try:
        from remote_terminal.brain import _exec_raw as _orig

        return _orig(command, device_id=device_id)
    except (ImportError, AttributeError):
        pass

    # Try device-specific execution
    if device_id:
        try:
            from remote_terminal import config
        except ImportError:
            config = None  # type: ignore[assignment]

        default_device = (
            getattr(config, "DEFAULT_DEVICE", "laptop") if config else "laptop"
        )
        if device_id != default_device:
            # Remote execution via agent
            try:
                from remote_terminal.agent import exec_remote

                return exec_remote(command, device_id=device_id, timeout=timeout)
            except (ImportError, AttributeError):
                log.warning("Remote agent not available, falling back to local exec")

    # Local execution is a compatibility-only escape hatch. Production paths
    # must use the signed Remote Agent or an NKI capability submission.
    if os.environ.get("NOUS_ALLOW_LEGACY_DIRECT_EXEC", "") != "1":
        return (
            "Local compatibility execution is disabled; use the governed "
            "Remote Agent path or set NOUS_ALLOW_LEGACY_DIRECT_EXEC=1 explicitly",
            -2,
        )
    try:
        from nous_runtime.capability.sandbox import run_shell_command_strict

        result = run_shell_command_strict(
            command, cwd=cwd or os.getcwd(), timeout_seconds=timeout
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return output.strip(), result.returncode
    except Exception as e:
        log.exception("Strict compatibility execution failed")
        return str(e), -1


def _is_device_online(device_id: str) -> bool:
    """Check if a device is online."""
    # Try compat path first
    try:
        from remote_terminal.brain_devices import is_device_online as _orig

        return _orig(device_id)
    except (ImportError, AttributeError):
        pass

    # Fallback: try to connect
    try:
        from remote_terminal.brain_devices import devices

        if device_id in devices:
            return devices[device_id].get("online", False)
    except (ImportError, AttributeError):
        pass

    return False

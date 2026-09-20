# -*- coding: utf-8 -*-
"""
Nous Daemon entry point for systemd.

Invoked by: python -m nous_runtime.daemon
Referenced in: deploy/nousd.service

Bootstraps the DaemonService with the new NousServer primary runtime.
"""

from __future__ import annotations

import logging
import os
import sys


def main() -> None:
    """Bootstrap the Nous daemon with systemd integration."""
    log_level = os.environ.get("NOUS_LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("nous.daemon")

    log.info("Nous Daemon starting (pid=%d)", os.getpid())

    # Notify systemd if applicable
    _notify_systemd("STATUS=Initializing...")
    _notify_systemd("READY=1")

    try:
        from nous_runtime.daemon.service import DaemonService

        host = os.environ.get("NOUS_BRAIN_HOST", "127.0.0.1")
        port = int(os.environ.get("NOUS_BRAIN_PORT", "9770"))
        workspace = os.environ.get("NOUS_DATA_DIR",
                                   os.path.join(os.environ.get("NOUS_HOME", "/opt/nous"), "data"))

        service = DaemonService(workspace=workspace, host=host, port=port)

        if not service.start():
            log.error("Failed to start daemon")
            sys.exit(1)

        log.info("Daemon running on %s:%d, workspace=%s", host, port, workspace)
        _notify_systemd("READY=1")
        _notify_systemd("STATUS=Running")

        # Keep alive with watchdog pings
        import time
        while service.is_running:
            time.sleep(5)
            _notify_systemd("WATCHDOG=1")

    except KeyboardInterrupt:
        log.info("Daemon interrupted")
    except Exception as e:
        log.error("Fatal: %s", e, exc_info=True)
        _notify_systemd(f"STATUS=Failed: {e}")
        sys.exit(1)
    finally:
        _notify_systemd("STATUS=Stopped")


def _notify_systemd(message: str) -> None:
    """Send a notification to systemd via NOTIFY_SOCKET."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    try:
        import socket
        addr = "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.sendto(message.encode("utf-8"), addr)
        finally:
            sock.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()

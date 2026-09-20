# -*- coding: utf-8 -*-
"""Windows Service wrapper for Nous Runtime daemon.

Install:  python -m nous_runtime.daemon.windows_service install
Start:    python -m nous_runtime.daemon.windows_service start
Stop:     python -m nous_runtime.daemon.windows_service stop
Remove:   python -m nous_runtime.daemon.windows_service remove
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

_log = logging.getLogger("nous.daemon.win32")


# Windows Service implementation using pywin32
try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False


class NousWindowsService(win32serviceutil.ServiceFramework if HAS_PYWIN32 else object):
    """Windows Service that manages the Nous Runtime daemon."""

    _svc_name_ = "NousRuntime"
    _svc_display_name_ = "Nous Runtime Service"
    _svc_description_ = (
        "Personal AI Operating Runtime — manages models, tasks, "
        "and intelligent execution in the background."
    )
    _svc_deps_ = ["Tcpip"]

    def __init__(self, args):
        if HAS_PYWIN32:
            win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = None
        self._daemon = None
        self._health_checker = None

    @classmethod
    def install_service(cls) -> None:
        """Install the Windows service."""
        if not HAS_PYWIN32:
            print("pywin32 is required: pip install pywin32")
            sys.exit(1)
        win32serviceutil.InstallService(
            None,
            cls._svc_name_,
            cls._svc_display_name_,
            description=cls._svc_description_,
            startType=win32service.SERVICE_AUTO_START,
        )
        print(f"Service '{cls._svc_display_name_}' installed.")
        print("Start it with: net start NousRuntime")

    @classmethod
    def remove_service(cls) -> None:
        """Remove the Windows service."""
        if not HAS_PYWIN32:
            print("pywin32 is required: pip install pywin32")
            sys.exit(1)
        win32serviceutil.RemoveService(cls._svc_name_)
        print(f"Service '{cls._svc_display_name_}' removed.")

    def SvcStop(self):
        """Called when the service is requested to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._stop_event:
            win32event.SetEvent(self._stop_event)
        if self._health_checker:
            self._health_checker.stop()
        if self._daemon:
            self._daemon.stop()
        _log.info("Nous Runtime service stopping")

    def SvcDoRun(self):
        """Main service entry point."""
        _log.info("Nous Runtime service starting")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )

        try:
            from nous_runtime.daemon.service import DaemonService
            from nous_runtime.daemon.health import create_default_checks

            workspace = os.environ.get(
                "NOUS_WORKSPACE",
                str(Path.home() / ".nous"),
            )

            self._daemon = DaemonService(workspace=workspace)
            self._daemon.start()

            # Start health checks
            self._health_checker = create_default_checks(workspace)
            self._health_checker.start()

            self._stop_event = win32event.CreateEvent(None, 0, 0, None)

            # Main loop — check stop signal periodically
            while self._daemon.is_running:
                rc = win32event.WaitForSingleObject(
                    self._stop_event, 5000
                )
                if rc == win32event.WAIT_OBJECT_0:
                    break

        except Exception as exc:
            _log.exception("Fatal error in Nous Runtime service: %s", exc)
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_ERROR_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, str(exc)),
            )


# Entry points (usable without pywin32 for CLI management)

def install() -> None:
    """Install Nous as a Windows service."""
    NousWindowsService.install_service()


def remove() -> None:
    """Remove the Nous Windows service."""
    NousWindowsService.remove_service()


def start_service() -> None:
    """Start the Nous Windows service."""
    if HAS_PYWIN32:
        win32serviceutil.StartService(NousWindowsService._svc_name_)
        print(f"Service '{NousWindowsService._svc_display_name_}' started.")
    else:
        print("pywin32 required. Run: pip install pywin32")


def stop_service() -> None:
    """Stop the Nous Windows service."""
    if HAS_PYWIN32:
        win32serviceutil.StopService(NousWindowsService._svc_name_)
        print(f"Service '{NousWindowsService._svc_display_name_}' stopped.")
    else:
        print("pywin32 required. Run: pip install pywin32")


def restart_service() -> None:
    """Restart the Nous Windows service."""
    stop_service()
    time.sleep(2)
    start_service()


def status() -> None:
    """Query Windows service status."""
    if HAS_PYWIN32:
        try:
            stat = win32serviceutil.QueryServiceStatus(
                NousWindowsService._svc_name_
            )
            states = {
                1: "STOPPED",
                2: "START_PENDING",
                3: "STOP_PENDING",
                4: "RUNNING",
                5: "CONTINUE_PENDING",
                6: "PAUSE_PENDING",
                7: "PAUSED",
            }
            state_name = states.get(stat[1], f"UNKNOWN({stat[1]})")
            print(f"Nous Runtime Service: {state_name}")
        except Exception as exc:
            print(f"Service not found or error: {exc}")
    else:
        print("pywin32 required. Run: pip install pywin32")


# CLI

def main() -> int:
    """CLI entry point for service management."""
    if len(sys.argv) < 2:
        print("Usage: python -m nous_runtime.daemon.windows_service <command>")
        print("Commands: install, remove, start, stop, restart, status, run")
        return 1

    cmd = sys.argv[1].lower()

    if cmd == "install":
        install()
    elif cmd == "remove":
        remove()
    elif cmd == "start":
        start_service()
    elif cmd == "stop":
        stop_service()
    elif cmd == "restart":
        restart_service()
    elif cmd == "status":
        status()
    elif cmd == "run":
        # Run directly (for debugging)
        if HAS_PYWIN32:
            win32serviceutil.HandleCommandLine(NousWindowsService)
        else:
            print("pywin32 required for service execution.")
            return 1
    else:
        print(f"Unknown command: {cmd}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "NousWindowsService",
    "install",
    "remove",
    "start_service",
    "stop_service",
    "restart_service",
    "status",
]

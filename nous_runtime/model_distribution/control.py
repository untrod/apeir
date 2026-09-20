"""Thread-safe controls for long-running model downloads."""

from __future__ import annotations

import threading

from nous_runtime.model_runtime.errors import ModelResolutionError


class DownloadCancelledError(ModelResolutionError):
    """Raised when a model download is cancelled by its owner."""


class DownloadControl:
    """Coordinate pause, resume, and cancellation across worker threads."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return not self._resumed.is_set() and not self.cancelled

    def pause(self) -> None:
        if not self.cancelled:
            self._resumed.clear()

    def resume(self) -> None:
        self._resumed.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._resumed.set()

    def checkpoint(self, *, interval_seconds: float = 0.1) -> None:
        """Block while paused and raise immediately after cancellation."""
        if interval_seconds <= 0:
            raise ModelResolutionError(
                "download control interval must be positive"
            )
        while not self._resumed.wait(timeout=interval_seconds):
            if self.cancelled:
                raise DownloadCancelledError("model download cancelled")
        if self.cancelled:
            raise DownloadCancelledError("model download cancelled")


__all__ = ["DownloadCancelledError", "DownloadControl"]

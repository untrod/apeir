# -*- coding: utf-8 -*-
"""OutputLimiter — enforces bounds on agent output."""

from __future__ import annotations

import io


class OutputLimitExceeded(Exception):
    """Raised when agent output exceeds the configured limit."""

    def __init__(self, limit_bytes: int, actual_bytes: int):
        self.limit_bytes = limit_bytes
        self.actual_bytes = actual_bytes
        super().__init__(
            f"Output limit exceeded: {actual_bytes} bytes (limit: {limit_bytes} bytes)"
        )


class OutputLimiter:
    """Wraps a byte stream and enforces a maximum output size.

    When the limit is exceeded, the stream is truncated and a warning
    is recorded. The process is NOT killed — that is the supervisor's job.
    """

    def __init__(self, limit_bytes: int = 1_048_576):
        if limit_bytes < 1024:
            raise ValueError("limit_bytes must be at least 1024")
        self._limit = limit_bytes
        self._buffer = io.BytesIO()
        self._bytes_written = 0
        self._truncated = False

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def truncated(self) -> bool:
        return self._truncated

    def write(self, data: bytes) -> int:
        remaining = self._limit - self._bytes_written
        if remaining <= 0:
            self._truncated = True
            return len(data)

        if len(data) > remaining:
            self._buffer.write(data[:remaining])
            self._bytes_written += remaining
            self._truncated = True
            return len(data)

        self._buffer.write(data)
        self._bytes_written += len(data)
        return len(data)

    def getvalue(self) -> bytes:
        return self._buffer.getvalue()

    def getvalue_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self._buffer.getvalue().decode(encoding, errors=errors)

    def reset(self) -> None:
        self._buffer = io.BytesIO()
        self._bytes_written = 0
        self._truncated = False

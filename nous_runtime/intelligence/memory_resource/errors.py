"""Memory and Resource Intelligence errors."""

from nous_runtime.core.errors import NousError


class MemoryResourceError(NousError):
    error_code = "memory_resource_error"


class InvalidMemorySignalError(MemoryResourceError):
    error_code = "invalid_memory_signal"


class InvalidResourceVectorError(MemoryResourceError):
    error_code = "invalid_resource_vector"


__all__ = [
    "InvalidMemorySignalError",
    "InvalidResourceVectorError",
    "MemoryResourceError",
]

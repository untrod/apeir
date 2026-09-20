"""Benchmark Runtime errors."""

from nous_runtime.core.errors import NousError


class BenchmarkRuntimeError(NousError):
    error_code = "benchmark_runtime_error"


class BenchmarkConfigurationError(BenchmarkRuntimeError, ValueError):
    error_code = "benchmark_configuration_error"


__all__ = ["BenchmarkConfigurationError", "BenchmarkRuntimeError"]

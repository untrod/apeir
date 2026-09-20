"""Deprecated import shim for the pre-separation Runtime namespace.

The APEIR Kernel is the Rust component reached through NKI. Distribution
lifecycle management moved to :mod:`nous_runtime.runtime.lifecycle`.
"""

from nous_runtime.runtime.lifecycle import DistributionRuntime, Runtime, RuntimeStatus

__all__ = ["DistributionRuntime", "Runtime", "RuntimeStatus"]

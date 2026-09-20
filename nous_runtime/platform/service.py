# -*- coding: utf-8 -*-
"""
PlatformService — Singleton that provides platform info to all modules.

Usage::

    from nous_runtime.platform import platform_service
    if platform_service.tier == RuntimeTier.LITE:
        print("Running in lite mode")

No other module should call ``detect_platform()`` directly or use
``platform.machine()``, ``sys.maxsize``, or ``os.uname()`` — they
must go through this service.
"""

from __future__ import annotations

import logging
from typing import Callable

from nous_runtime.platform.models import (
    Architecture,
    ABI,
    PlatformInfo,
    RuntimeTier,
    WordSize,
)
from nous_runtime.platform.detector import detect_platform

_log = logging.getLogger("nous.platform.service")


class PlatformService:
    """
    Singleton platform introspection service.

    On first access, detects the platform once and caches the result.
    The cache can be invalidated for testing or runtime re-detection.
    """

    _instance: PlatformService | None = None

    def __init__(self) -> None:
        self._info: PlatformInfo | None = None
        self._on_tier_change: list[Callable[[RuntimeTier], None]] = []

    @classmethod
    def instance(cls) -> PlatformService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # Platform info (lazy, cached)

    @property
    def info(self) -> PlatformInfo:
        """Return the detected platform info. Detects on first access."""
        if self._info is None:
            self._info = detect_platform()
            _log.info(
                "Platform detected: %s arch=%s tier=%s word=%s abi=%s",
                self._info.os_name,
                self._info.architecture.value,
                self._info.runtime_tier.value,
                self._info.word_size.value,
                self._info.abi.value,
            )
        return self._info

    def re_detect(self) -> PlatformInfo:
        """Force re-detection of the platform. Useful after environment changes."""
        self._info = detect_platform()
        return self._info

    def set_platform(self, info: PlatformInfo) -> None:
        """Override platform info (for testing or explicit mode)."""
        old_tier = self._info.runtime_tier if self._info else None
        self._info = info
        if old_tier is not None and old_tier != info.runtime_tier:
            for cb in self._on_tier_change:
                try:
                    cb(info.runtime_tier)
                except Exception as e:
                    _log.warning("Tier change callback failed: %s", e)

    def on_tier_change(self, cb: Callable[[RuntimeTier], None]) -> None:
        """Register a callback for when the runtime tier changes."""
        self._on_tier_change.append(cb)

    # Convenience properties

    @property
    def architecture(self) -> Architecture:
        return self.info.architecture

    @property
    def abi(self) -> ABI:
        return self.info.abi

    @property
    def word_size(self) -> WordSize:
        return self.info.word_size

    @property
    def tier(self) -> RuntimeTier:
        return self.info.runtime_tier

    @property
    def is_lite(self) -> bool:
        return self.tier == RuntimeTier.LITE

    @property
    def is_full(self) -> bool:
        return self.tier == RuntimeTier.FULL

    @property
    def is_arm(self) -> bool:
        return self.architecture.is_arm

    @property
    def is_64bit(self) -> bool:
        return self.architecture.is_64bit

    @property
    def is_jetson(self) -> bool:
        return self.info.gpu_model and "jetson" in self.info.gpu_model.lower()

    @property
    def platform_tag(self) -> str:
        return self.info.platform_tag

    # Capability check

    def can_execute(self, capability_id: str) -> bool:
        """Check if the current platform can execute a capability."""
        return self.info.is_compatible_with(capability_id)

    def filter_capabilities(self, capabilities: list[str]) -> list[str]:
        """Filter a list of capability IDs to those allowed on this platform."""
        if self.is_full:
            return capabilities
        return [c for c in capabilities if self.can_execute(c)]


# Module-level singleton

platform_service = PlatformService.instance()

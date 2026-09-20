"""
Feature flag system for RC10 adaptive intelligence.

ALL features DISABLED_BY_DEFAULT. Runtime-overridable but require explicit
enablement. When disabled, the deterministic baseline is used automatically.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ExperimentalConfig:
    """Serializable configuration for RC10 experimental features.

    Maps directly to the [experimental] section of nousd.toml.
    All fields default to False.
    """

    adaptive_routing: bool = False
    adaptive_scheduling: bool = False
    adaptive_context_paging: bool = False
    adaptive_recovery: bool = False
    adaptive_energy: bool = False
    adaptive_personalization: bool = False
    continual_learning: bool = False
    shadow_execution: bool = False
    canary_experiments: bool = False

    @classmethod
    def all_disabled(cls) -> "ExperimentalConfig":
        """Create a config with all features disabled (RC9-equivalent)."""
        return cls()

    def any_enabled(self) -> bool:
        """Check if ANY adaptive feature is enabled."""
        return any(
            [
                self.adaptive_routing,
                self.adaptive_scheduling,
                self.adaptive_context_paging,
                self.adaptive_recovery,
                self.adaptive_energy,
                self.adaptive_personalization,
                self.continual_learning,
                self.shadow_execution,
                self.canary_experiments,
            ]
        )


class AdaptiveFlags:
    """Thread-safe global feature flag registry for RC10 adaptive features.

    Usage:
        flags = AdaptiveFlags.global_flags()
        if flags.is_enabled("adaptive_routing"):
            route = adaptive_router.select(...)
        else:
            route = deterministic_router.select(...)
    """

    _global: ClassVar["AdaptiveFlags | None"] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._flags: dict[str, bool] = {
            "adaptive_routing": False,
            "adaptive_scheduling": False,
            "adaptive_context_paging": False,
            "adaptive_recovery": False,
            "adaptive_energy": False,
            "adaptive_personalization": False,
            "continual_learning": False,
            "shadow_execution": False,
            "canary_experiments": False,
        }
        self._lock = threading.Lock()

    @classmethod
    def global_flags(cls) -> "AdaptiveFlags":
        """Get or create the global AdaptiveFlags singleton."""
        if cls._global is None:
            with cls._lock:
                if cls._global is None:
                    cls._global = cls()
        return cls._global

    def is_enabled(self, flag_name: str) -> bool:
        """Check if a specific adaptive feature is enabled."""
        with self._lock:
            return self._flags.get(flag_name, False)

    def enable(self, flag_name: str) -> None:
        """Enable a specific adaptive feature."""
        valid_flags = self._flags.keys()
        if flag_name not in valid_flags:
            raise ValueError(
                f"Unknown feature flag: {flag_name}. Valid flags: {list(valid_flags)}"
            )
        with self._lock:
            self._flags[flag_name] = True

    def disable(self, flag_name: str) -> None:
        """Disable a specific adaptive feature."""
        with self._lock:
            if flag_name in self._flags:
                self._flags[flag_name] = False

    def apply_config(self, config: ExperimentalConfig) -> None:
        """Apply an ExperimentalConfig to these flags."""
        with self._lock:
            self._flags["adaptive_routing"] = config.adaptive_routing
            self._flags["adaptive_scheduling"] = config.adaptive_scheduling
            self._flags["adaptive_context_paging"] = config.adaptive_context_paging
            self._flags["adaptive_recovery"] = config.adaptive_recovery
            self._flags["adaptive_energy"] = config.adaptive_energy
            self._flags["adaptive_personalization"] = config.adaptive_personalization
            self._flags["continual_learning"] = config.continual_learning
            self._flags["shadow_execution"] = config.shadow_execution
            self._flags["canary_experiments"] = config.canary_experiments

    def any_enabled(self) -> bool:
        """Check if any adaptive feature is enabled."""
        with self._lock:
            return any(self._flags.values())

    def all_disabled(self) -> bool:
        """Check if all adaptive features are disabled (RC9-equivalent mode)."""
        return not self.any_enabled()

    def disable_all(self) -> None:
        """Disable all adaptive features — return to RC9-equivalent mode."""
        with self._lock:
            for key in self._flags:
                self._flags[key] = False

    def enabled_features(self) -> list[str]:
        """List all currently enabled features."""
        with self._lock:
            return [k for k, v in self._flags.items() if v]

    def snapshot(self) -> dict[str, bool]:
        """Get a snapshot of all feature flags."""
        with self._lock:
            return dict(self._flags)

# -*- coding: utf-8 -*-
"""SDK Capability — define and register capabilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

_log = logging.getLogger("nous.sdk.capability")


@dataclass
class Capability:
    """Define a capability that agents can provide.

    Usage:
        cap = Capability(
            name="yolo.detect",
            description="Detect objects using YOLO",
            handler=my_detect_function,
            requirements=["cuda", "opencv"],
        )
        cap.register()
    """

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    handler: Callable | None = None
    category: str = ""
    requirements: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    risk_level: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)
    _cap_id: str = ""

    def __post_init__(self):
        import uuid
        if not self._cap_id:
            self._cap_id = f"cap.sdk.{self.name}.{uuid.uuid4().hex[:8]}"

    @property
    def cap_id(self) -> str:
        return self._cap_id

    def register(self, workspace: str = "") -> bool:
        """Register this capability in the ecosystem."""
        try:
            from nous_runtime.ecosystem.manifest import CapabilityManifest
            from nous_runtime.ecosystem.registry import CapabilityRegistry

            manifest = CapabilityManifest(
                name=self.name, version=self.version, description=self.description,
                category=self.category, requirements=self.requirements,
                permissions=self.permissions, risk_level=self.risk_level,
                metadata=self.metadata,
            )
            reg = CapabilityRegistry(workspace)
            return reg.install(manifest)
        except Exception as exc:
            _log.error("Failed to register capability: %s", exc)
            return False

    def execute(self, params: dict[str, Any] | None = None) -> Any:
        """Execute the capability handler."""
        if self.handler is None:
            raise RuntimeError(f"Capability '{self.name}' has no handler.")
        return self.handler(**(params or {}))

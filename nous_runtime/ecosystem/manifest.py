# -*- coding: utf-8 -*-
"""Capability Manifest — declaration format for installable capabilities."""

from __future__ import annotations

import hashlib
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CapabilityManifest:
    """Declares a capability that can be installed and used.

    Example:
        {
            "name": "yolo.detect",
            "version": "1.0.0",
            "requirements": ["cuda", "opencv"],
            "risk_level": "medium",
            "trust": "verified"
        }
    """
    name: str = ""                # e.g. "yolo.detect", "ros.navigation"
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    category: str = ""            # vision, robotics, networking, coding, analysis, security
    requirements: tuple[str, ...] = ()   # system dependencies
    python_dependencies: tuple[str, ...] = ()  # pip packages
    permissions: tuple[str, ...] = ()   # required permissions
    risk_level: str = "low"       # low, medium, high, critical
    trust: str = "community"      # official, verified, community, unknown
    entry_point: str = ""         # Python import path
    signature: str = ""           # Author's signature
    metadata: dict[str, Any] = field(default_factory=dict)
    manifest_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.manifest_id:
            self.manifest_id = f"cap_{_uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version,
            "description": self.description, "author": self.author,
            "category": self.category,
            "requirements": list(self.requirements),
            "python_dependencies": list(self.python_dependencies),
            "permissions": list(self.permissions),
            "risk_level": self.risk_level, "trust": self.trust,
            "entry_point": self.entry_point, "signature": self.signature,
            "metadata": dict(self.metadata),
            "manifest_id": self.manifest_id, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityManifest":
        d = dict(data)
        d["requirements"] = tuple(d.pop("requirements", []))
        d["python_dependencies"] = tuple(d.pop("python_dependencies", []))
        d["permissions"] = tuple(d.pop("permissions", []))
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def checksum(self) -> str:
        h = hashlib.sha256()
        h.update(self.name.encode())
        h.update(self.version.encode())
        h.update(self.entry_point.encode())
        return h.hexdigest()

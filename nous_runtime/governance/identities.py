# -*- coding: utf-8 -*-
"""Unified Identity Model — User, Service Account, Agent, Node, Model, Tool, Plugin.

All entities in the system have a unified identity with typed permissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IdentityType(str, Enum):
    USER = "user"
    SERVICE_ACCOUNT = "service_account"
    AGENT = "agent"
    NODE = "node"
    MODEL = "model"
    TOOL = "tool"
    PLUGIN = "plugin"


@dataclass
class Identity:
    """Unified identity for any entity in the system."""
    identity_id: str = ""
    identity_type: IdentityType = IdentityType.AGENT
    name: str = ""
    permissions: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)  # ABAC attributes
    parent_identity: str = ""  # for delegation chains
    active: bool = True
    created_at: str = ""


class IdentityRegistry:
    """Registry of all system identities."""

    def __init__(self) -> None:
        self._identities: dict[str, Identity] = {}

    def register(self, identity: Identity) -> str:
        self._identities[identity.identity_id] = identity
        return identity.identity_id

    def get(self, identity_id: str) -> Identity | None:
        return self._identities.get(identity_id)

    def has_permission(self, identity_id: str, permission: str) -> bool:
        ident = self._identities.get(identity_id)
        if ident is None:
            return False
        return permission in ident.permissions or "admin" in ident.roles

    def revoke(self, identity_id: str) -> None:
        ident = self._identities.get(identity_id)
        if ident:
            ident.active = False

    def count(self) -> int:
        return len(self._identities)

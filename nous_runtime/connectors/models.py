"""Enterprise Connector Runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any


class AuthenticationType(str, Enum):
    NONE = "none"
    API_TOKEN = "api_token"
    OAUTH2 = "oauth2"
    WEBHOOK_SECRET = "webhook_secret"


class ConnectorRisk(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ConnectorAction:
    name: str
    risk: ConnectorRisk = ConnectorRisk.READ
    required_scopes: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    idempotent: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "risk": self.risk.value, "required_scopes": list(self.required_scopes), "input_schema": self.input_schema, "output_schema": self.output_schema, "idempotent": self.idempotent}


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    version: str
    actions: tuple[ConnectorAction, ...]
    authentication_type: AuthenticationType = AuthenticationType.NONE
    granted_scopes: tuple[str, ...] = ()
    rate_limit_per_minute: int = 60
    max_retries: int = 2
    data_boundary: str = "workspace"
    audit_behavior: str = "all"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*", self.connector_id):
            errors.append("invalid connector_id")
        if not self.version:
            errors.append("version is required")
        if self.rate_limit_per_minute < 1:
            errors.append("rate_limit_per_minute must be positive")
        names = [action.name for action in self.actions]
        if len(names) != len(set(names)):
            errors.append("duplicate connector action")
        if self.data_boundary not in {"workspace", "project", "user", "external"}:
            errors.append("invalid data_boundary")
        return errors

    def action(self, name: str) -> ConnectorAction | None:
        return next((item for item in self.actions if item.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {"connector_id": self.connector_id, "version": self.version, "authentication_type": self.authentication_type.value, "granted_scopes": list(self.granted_scopes), "actions": [item.to_dict() for item in self.actions], "rate_limit_per_minute": self.rate_limit_per_minute, "max_retries": self.max_retries, "data_boundary": self.data_boundary, "audit_behavior": self.audit_behavior}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConnectorManifest":
        return cls(
            connector_id=str(data.get("connector_id") or ""), version=str(data.get("version") or ""),
            authentication_type=AuthenticationType(str(data.get("authentication_type") or "none")),
            granted_scopes=tuple(str(item) for item in data.get("granted_scopes") or ()),
            actions=tuple(ConnectorAction(name=str(item.get("name") or ""), risk=ConnectorRisk(str(item.get("risk") or "read")), required_scopes=tuple(str(scope) for scope in item.get("required_scopes") or ()), input_schema=dict(item.get("input_schema") or {}), output_schema=dict(item.get("output_schema") or {}), idempotent=bool(item.get("idempotent", True))) for item in data.get("actions") or ()),
            rate_limit_per_minute=int(data.get("rate_limit_per_minute") or 60), max_retries=int(data.get("max_retries") or 2), data_boundary=str(data.get("data_boundary") or "workspace"), audit_behavior=str(data.get("audit_behavior") or "all"),
        )


@dataclass(frozen=True)
class ConnectorRequest:
    connector_id: str
    action: str
    workspace_id: str
    params: dict[str, Any] = field(default_factory=dict)
    cursor: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class ConnectorResult:
    ok: bool
    items: tuple[dict[str, Any], ...] = ()
    next_cursor: str = ""
    error_code: str = ""
    message: str = ""
    attempts: int = 1
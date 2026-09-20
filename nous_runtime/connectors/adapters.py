"""Generic deterministic Connector Runtime reference adapters."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Callable

from nous_runtime.connectors.base import ConnectorTemporaryError
from nous_runtime.connectors.models import ConnectorRequest, ConnectorResult
from nous_runtime.connectors.vault import ConnectorCredential


class MockEnterpriseConnector:
    def __init__(self, pages: dict[str, tuple[dict[str, Any], ...]] | None = None, *, fail_times: int = 0):
        self.pages = pages or {"": ({"id": "1"},)}
        self.fail_times = fail_times
        self.calls = 0

    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectorTemporaryError("temporary connector failure")
        items = self.pages.get(request.cursor, ())
        cursors = list(self.pages)
        try:
            index = cursors.index(request.cursor)
            next_cursor = cursors[index + 1] if index + 1 < len(cursors) else ""
        except ValueError:
            next_cursor = ""
        return ConnectorResult(True, tuple(items), next_cursor=next_cursor)

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "calls": self.calls}


class GenericRESTConnector:
    """Transport-injected REST adapter; network behavior is optional and testable."""

    def __init__(self, transport: Callable[[dict[str, Any]], dict[str, Any]]):
        self.transport = transport
        self.last_status = "unknown"

    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult:
        response = self.transport({"action": request.action, "params": dict(request.params), "cursor": request.cursor, "token": credential.value if credential else ""})
        self.last_status = "ok" if response.get("ok") else "error"
        return ConnectorResult(bool(response.get("ok")), tuple(response.get("items") or ()), str(response.get("next_cursor") or ""), str(response.get("error_code") or ""), str(response.get("message") or ""))

    def health(self) -> dict[str, Any]:
        return {"status": self.last_status}


class WebhookConnector:
    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult:
        if credential is None:
            return ConnectorResult(False, error_code="WEBHOOK_SECRET_REQUIRED")
        body = str(request.params.get("body") or "").encode()
        supplied = str(request.params.get("signature") or "")
        expected = hmac.new(credential.value.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            return ConnectorResult(False, error_code="INVALID_WEBHOOK_SIGNATURE")
        payload = json.loads(body.decode() or "{}")
        return ConnectorResult(True, (payload,))

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}


class LocalFileConnector:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()

    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult:
        relative = str(request.params.get("path") or "")
        target = (self.workspace_root / relative).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ConnectorResult(False, error_code="WORKSPACE_ESCAPE")
        if request.action == "read":
            if not target.is_file():
                return ConnectorResult(False, error_code="FILE_NOT_FOUND")
            return ConnectorResult(True, ({"path": relative, "content": target.read_text(encoding="utf-8")},))
        if request.action == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(request.params.get("content") or ""), encoding="utf-8")
            return ConnectorResult(True, ({"path": relative},))
        return ConnectorResult(False, error_code="ACTION_NOT_SUPPORTED")

    def health(self) -> dict[str, Any]:
        return {"status": "ok" if self.workspace_root.is_dir() else "unavailable"}
class GitConnector:
    """Read-only Git metadata adapter scoped to one Workspace."""
    def __init__(self, workspace_root: str | Path): self.workspace_root = Path(workspace_root).resolve()
    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult:
        import subprocess
        allowed = {"status": ("status", "--short"), "log": ("log", "-n", "20", "--oneline")}
        command = allowed.get(request.action)
        if command is None:
            return ConnectorResult(False, error_code="ACTION_NOT_SUPPORTED")
        result = subprocess.run(("git", "-C", str(self.workspace_root), *command), capture_output=True, text=True, timeout=10)
        return ConnectorResult(result.returncode == 0, ({"output": result.stdout},), error_code="" if result.returncode == 0 else "GIT_FAILED")
    def health(self) -> dict[str, Any]: return {"status": "ok" if (self.workspace_root / ".git").exists() else "unavailable"}


class SQLiteConnector:
    """Read-only parameterized SQLite adapter."""
    def __init__(self, database: str | Path): self.database = Path(database).resolve()
    def execute(self, request: ConnectorRequest, credential: ConnectorCredential | None) -> ConnectorResult:
        import sqlite3
        if request.action != "query":
            return ConnectorResult(False, error_code="ACTION_NOT_SUPPORTED")
        sql = str(request.params.get("sql") or "").strip()
        if not sql.lower().startswith(("select", "pragma", "with")):
            return ConnectorResult(False, error_code="READ_ONLY_REQUIRED")
        connection = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            rows = tuple(
                dict(row)
                for row in connection.execute(
                    sql,
                    tuple(request.params.get("parameters") or ()),
                ).fetchmany(1000)
            )
        finally:
            connection.close()
        return ConnectorResult(True, rows)
    def health(self) -> dict[str, Any]: return {"status": "ok" if self.database.is_file() else "unavailable"}


class HTTPConnector(GenericRESTConnector):
    """Named HTTP Connector using the existing transport-injection boundary."""
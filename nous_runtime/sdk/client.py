"""Synchronous Python client for the authoritative Nous Server Runtime."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class ClientConfig:
    """Connection settings for a Nous Server Runtime."""

    host: str = "localhost"
    port: int = 8770
    token: str = ""
    timeout: int = 30


@dataclass
class CapabilityResult:
    """Stable SDK representation of a capability or chat result."""

    ok: bool
    capability_id: str
    provider_id: str = ""
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class RuntimeInfo:
    """Server Runtime status summary."""

    version: str = ""
    running: bool = False
    providers: int = 0
    capabilities: int = 0
    packs: int = 0
    devices: int = 0
    demo_mode: bool = False


class NousClient:
    """HTTP client that never owns Runtime state or executes capabilities locally."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8770,
        token: str = "",
        *,
        timeout: int = 30,
    ) -> None:
        self.config = ClientConfig(host=host, port=port, token=token, timeout=timeout)
        self._base = f"http://{host}:{port}"

    def health(self) -> dict[str, Any]:
        """Return the Server Runtime health response."""
        return self._get("/api/v1/health")

    def status(self) -> RuntimeInfo:
        """Return the authoritative Server Runtime status."""
        data = self._data(self._get("/api/v1/status"), {})
        if not isinstance(data, dict):
            return RuntimeInfo()
        fields = RuntimeInfo.__dataclass_fields__
        return RuntimeInfo(**{name: data[name] for name in fields if name in data})

    def run(self, capability_id: str, **params: Any) -> CapabilityResult:
        """Execute a capability through the authenticated Server Runtime."""
        response = self._post(
            "/api/v1/capabilities/run",
            {"capability_id": capability_id, "params": params},
        )
        data = self._data(response, {})
        if response.get("ok") and isinstance(data, dict):
            return CapabilityResult(
                ok=bool(data.get("ok")),
                capability_id=str(data.get("capability_id") or capability_id),
                provider_id=str(data.get("provider_id") or ""),
                result=data.get("result"),
                error=str(data.get("error") or ""),
                duration_ms=float(data.get("duration_ms") or 0.0),
            )
        return CapabilityResult(False, capability_id, error=self._error_message(response))

    def list_capabilities(self) -> list[dict[str, Any]]:
        """List capabilities exposed by the Server Runtime."""
        data = self._data(self._get("/api/v1/capabilities"), [])
        return list(data) if isinstance(data, list) else []

    def chat(self, message: str, **params: Any) -> CapabilityResult:
        """Send a conversation request through the Server Runtime Chat path."""
        body = {"text": message, **params}
        response = self._post("/api/chat", body)
        data = self._data(response, {})
        if response.get("ok") and isinstance(data, dict):
            return CapabilityResult(True, "chat.runtime", result=data)
        return CapabilityResult(False, "chat.runtime", error=self._error_message(response))

    def run_capability(self, capability_id: str, **params: Any) -> CapabilityResult:
        """Alias for Server Runtime capability execution."""
        return self.run(capability_id, **params)

    def workflow(
        self,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
        *,
        version: str = "1.0.0",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Start a registered workflow through the governed Server Runtime route."""
        return self._post(
            "/api/workflow/run",
            {
                "workflow_id": workflow_id,
                "version": version,
                "inputs": dict(inputs or {}),
                "idempotency_key": idempotency_key,
            },
        )

    def list_runs(self, limit: int = 20) -> dict[str, Any]:
        """List canonical Runtime runs."""
        return self._get(f"/api/runtime/runs?limit={max(1, min(limit, 200))}")

    def run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Replay canonical events with a resumable sequence cursor."""
        run = urllib.parse.quote(run_id, safe="")
        query = urllib.parse.urlencode({
            "after_sequence": max(0, after_sequence),
            "limit": max(1, min(limit, 1000)),
        })
        return self._get(f"/api/runtime/runs/{run}/events?{query}")
    def list_providers(self) -> list[dict[str, Any]]:
        """List providers exposed by the Server Runtime."""
        data = self._data(self._get("/api/v1/providers"), [])
        return list(data) if isinstance(data, list) else []

    def provider_health(self) -> dict[str, Any]:
        """Return the Server Runtime provider-health summary."""
        data = self._data(self._get("/api/v1/providers/health"), {})
        return dict(data) if isinstance(data, dict) else {}

    def list_packs(self) -> list[dict[str, Any]]:
        """List packs exposed by the Server Runtime."""
        data = self._data(self._get("/api/v1/packs"), [])
        return list(data) if isinstance(data, list) else []

    def install_pack(self, path: str) -> dict[str, Any]:
        """Request governed pack installation on the Server Runtime."""
        return self._post("/api/v1/packs/install", {"path": path})

    def remove_pack(self, name: str) -> None:
        """Request governed pack removal on the Server Runtime."""
        self._request("DELETE", f"/api/v1/packs/{urllib.parse.quote(name, safe='')}")

    def trace(self, session_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
        """Return recent Server Runtime traces."""
        query = urllib.parse.urlencode({"limit": max(1, min(limit, 200)), "session_id": session_id})
        data = self._data(self._get(f"/api/v1/traces?{query}"), [])
        return list(data) if isinstance(data, list) else []

    def experience_stats(self, provider_id: str = "", capability_id: str = "") -> dict[str, Any]:
        """Return Server Runtime experience statistics."""
        query = urllib.parse.urlencode({"provider_id": provider_id, "capability_id": capability_id})
        data = self._data(self._get(f"/api/v1/experience/stats?{query}"), {})
        return dict(data) if isinstance(data, dict) else {}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        request = urllib.request.Request(
            f"{self._base}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                value = json.loads(response.read())
                return value if isinstance(value, dict) else {"ok": False, "error": "Invalid response"}
        except urllib.error.HTTPError as exc:
            try:
                value = json.loads(exc.read())
                if isinstance(value, dict):
                    return value
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            return {"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _data(response: dict[str, Any], default: Any) -> Any:
        return response.get("data", default) if response.get("ok") else default

    @staticmethod
    def _error_message(response: dict[str, Any]) -> str:
        error = response.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "Server Runtime request failed")
        return str(error or "Server Runtime request failed")
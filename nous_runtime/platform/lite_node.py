# -*- coding: utf-8 -*-
"""
ARMv7 Lite Node Daemon — Minimal runtime for Tier 2 edge devices.

Lite Node capabilities (ONLY):
  - Identity attestation and key rotation
  - Secure communication (TLS, WireGuard)
  - Heartbeat with Primary
  - Capability Executor (restricted allowlist)
  - Device adapters (sensors, GPIO, serial)
  - Offline buffer (store-and-forward when disconnected)
  - Audit logging
  - Update check, download, apply, rollback

Lite Node FORBIDDEN:
  - Desktop UI / GUI
  - Local LLM inference (llama.cpp, Ollama, vLLM)
  - Vector databases (ChromaDB, FAISS)
  - Heavy Agent Runtime (planner, evaluator, experience learning)
  - Training / fine-tuning
  - Context building (large)

This daemon is designed for:
  - Raspberry Pi 3/4 (ARMv7)
  - Raspberry Pi Zero (ARMv6)
  - Industrial ARM32 edge controllers
  - IoT gateways with constrained resources
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nous_runtime.platform import (
    LITE_NODE_ALWAYS_ALLOWED,
    RuntimeTier,
    platform_service,
)
from nous_runtime.project.workspace import default_workspace_path

_log = logging.getLogger("nous.platform.lite_node")

# Configuration

DEFAULT_HEARTBEAT_INTERVAL_SEC = 30
DEFAULT_OFFLINE_BUFFER_MAX_MB = 50
DEFAULT_OFFLINE_BUFFER_DIR = str(default_workspace_path("offline_buffer"))
DEFAULT_AUDIT_LOG_PATH = str(default_workspace_path("lite_audit.log"))


@dataclass
class LiteNodeConfig:
    """Configuration for a Lite Node daemon."""
    node_id: str = ""
    node_name: str = ""
    primary_url: str = "http://localhost:8770"
    primary_token: str = ""
    heartbeat_interval_sec: int = DEFAULT_HEARTBEAT_INTERVAL_SEC
    offline_buffer_max_mb: int = DEFAULT_OFFLINE_BUFFER_MAX_MB
    offline_buffer_dir: str = DEFAULT_OFFLINE_BUFFER_DIR
    audit_log_path: str = DEFAULT_AUDIT_LOG_PATH
    allowed_capabilities: list[str] = field(default_factory=list)
    device_adapters: list[str] = field(default_factory=list)  # "gpio", "serial", "i2c", etc.

    def __post_init__(self) -> None:
        if not self.node_id:
            self.node_id = f"lite-{uuid.uuid4().hex[:8]}"
        if not self.node_name:
            self.node_name = platform_service.info.hostname


# Lite Node Daemon

class LiteNodeDaemon:
    """
    Minimal daemon for Tier 2 (ARM32/ARMv7) Lite Nodes.

    Usage::

        daemon = LiteNodeDaemon(config)
        daemon.start()
        # Runs until SIGTERM/SIGINT
    """

    def __init__(self, config: LiteNodeConfig) -> None:
        self.config = config
        self._running = False
        self._offline_buffer: list[dict[str, Any]] = []
        self._last_heartbeat_ack: float = 0.0
        self._registered = False

        if not config.node_id:
            config.node_id = f"lite-{uuid.uuid4().hex[:8]}"
        if not config.node_name:
            config.node_name = platform_service.info.hostname

        # Ensure allowed capabilities are Lite-compatible
        self.config.allowed_capabilities = [
            c for c in config.allowed_capabilities
            if c in LITE_NODE_ALWAYS_ALLOWED
        ]
        if not self.config.allowed_capabilities:
            self.config.allowed_capabilities = sorted(LITE_NODE_ALWAYS_ALLOWED)

        # Create directories
        Path(self.config.offline_buffer_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.audit_log_path).parent.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Start the Lite Node daemon. Blocks until stopped."""
        platform_info = platform_service.info

        _log.info(
            "Lite Node starting: id=%s name=%s arch=%s tier=%s capabilities=%d",
            self.config.node_id,
            self.config.node_name,
            platform_info.architecture.value,
            platform_info.runtime_tier.value,
            len(self.config.allowed_capabilities),
        )

        if platform_info.runtime_tier != RuntimeTier.LITE:
            _log.warning(
                "LiteNodeDaemon running on Tier-1 platform (%s). "
                "Lite restrictions still apply.",
                platform_info.architecture.value,
            )

        self._running = True
        self._audit("daemon.start", {"node_id": self.config.node_id})

        # Register with Primary
        self._register()

        # Main loop
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        try:
            while self._running:
                try:
                    self._send_heartbeat()
                    self._flush_offline_buffer()
                    self._execute_pending_capabilities()
                except Exception as e:
                    _log.error("Lite Node loop error: %s", e)
                    self._buffer_event({
                        "type": "error",
                        "error": str(e),
                        "timestamp": time.time(),
                    })
                time.sleep(self.config.heartbeat_interval_sec)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Gracefully stop the daemon."""
        self._running = False

    # Internal methods

    def _register(self) -> None:
        """Register this Lite Node with the Primary."""
        platform_info = platform_service.info
        payload = {
            "node_id": self.config.node_id,
            "node_name": self.config.node_name,
            "platform": platform_info.to_dict(),
            "capabilities": self.config.allowed_capabilities,
            "role": "lite_worker",
        }
        try:
            resp = self._call_primary("POST", "/api/v1/nodes/register", payload)
            if resp.get("ok"):
                self._registered = True
                _log.info("Lite Node registered with Primary")
            else:
                _log.warning("Registration failed: %s", resp.get("error", "unknown"))
        except Exception as e:
            _log.warning("Cannot reach Primary, buffering registration: %s", e)
            self._buffer_event({"type": "register", "payload": payload})

    def _send_heartbeat(self) -> None:
        """Send heartbeat to Primary."""
        payload = {
            "node_id": self.config.node_id,
            "timestamp": time.time(),
            "offline_buffer_size": len(self._offline_buffer),
        }
        try:
            self._call_primary("POST", "/api/v1/nodes/heartbeat", payload)
            self._last_heartbeat_ack = time.time()
        except Exception:
            _log.debug("Heartbeat failed, buffering")
            self._buffer_event({"type": "heartbeat", "payload": payload})

    def _execute_pending_capabilities(self) -> None:
        """Check for and execute any pending capabilities."""
        try:
            resp = self._call_primary(
                "GET",
                f"/api/v1/nodes/{self.config.node_id}/pending_capabilities",
            )
            tasks = resp.get("tasks", [])
            for task in tasks:
                cap_id = task.get("capability_id", "")
                if cap_id not in LITE_NODE_ALWAYS_ALLOWED:
                    _log.warning("Rejected restricted capability: %s", cap_id)
                    self._report_capability_result(task.get("task_id", ""), False, "restricted")
                    continue

                try:
                    result = self._execute_capability(cap_id, task.get("params", {}))
                    self._report_capability_result(
                        task.get("task_id", ""), True, result=result,
                    )
                except Exception as e:
                    _log.error("Capability execution failed: %s", e)
                    self._report_capability_result(
                        task.get("task_id", ""), False, str(e),
                    )
        except Exception:
            pass  # Will retry on next cycle

    def _execute_capability(self, capability_id: str, params: dict) -> Any:
        """Execute a single capability. Override for device-specific logic."""
        # Device adapter dispatch
        if capability_id.startswith("device.adapter."):
            adapter_type = capability_id.replace("device.adapter.", "")
            if adapter_type in self.config.device_adapters:
                return {"adapter": adapter_type, "status": "executed", "params": params}
            return {"status": "no_adapter", "adapter_type": adapter_type}

        # Default: return identity/status info
        if capability_id == "identity.attest":
            return {
                "node_id": self.config.node_id,
                "platform": platform_service.info.to_dict(),
                "attested_at": time.time(),
            }
        if capability_id == "audit.log":
            return {"audit_entries": self._read_audit_log(params.get("limit", 100))}

        return {"status": "ok", "capability": capability_id}

    def _report_capability_result(self, task_id: str, success: bool, result: Any = None, error: str = "") -> None:
        """Report capability execution result to Primary."""
        payload = {"task_id": task_id, "success": success, "result": result, "error": error}
        try:
            self._call_primary("POST", "/api/v1/nodes/capability_result", payload)
        except Exception:
            self._buffer_event({"type": "capability_result", "payload": payload})

    def _call_primary(self, method: str, path: str, data: dict | None = None) -> dict:
        """Make an HTTP call to the Primary. Raises on failure."""
        import urllib.request

        url = f"{self.config.primary_url.rstrip('/')}{path}"
        body = json.dumps(data).encode("utf-8") if data else None
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.primary_token}",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _buffer_event(self, event: dict) -> None:
        """Buffer an event for offline store-and-forward."""
        max_events = int((self.config.offline_buffer_max_mb * 1024 * 1024) / 1024)  # ~1KB per event
        if len(self._offline_buffer) >= max_events:
            _log.warning("Offline buffer full (%d events), dropping oldest", len(self._offline_buffer))
            self._offline_buffer.pop(0)
        self._offline_buffer.append(event)
        # Persist to disk
        buffer_path = os.path.join(self.config.offline_buffer_dir, "buffer.jsonl")
        try:
            with open(buffer_path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            _log.error("Failed to persist offline buffer: %s", e)

    def _flush_offline_buffer(self) -> None:
        """Attempt to flush buffered events to Primary."""
        if not self._offline_buffer:
            return
        try:
            payload = {"node_id": self.config.node_id, "events": list(self._offline_buffer)}
            resp = self._call_primary("POST", "/api/v1/nodes/offline_buffer", payload)
            if resp.get("ok"):
                count = len(self._offline_buffer)
                self._offline_buffer.clear()
                # Clear persisted buffer
                buffer_path = os.path.join(self.config.offline_buffer_dir, "buffer.jsonl")
                if os.path.exists(buffer_path):
                    os.remove(buffer_path)
                _log.info("Flushed %d buffered events", count)
        except Exception:
            _log.debug("Cannot flush offline buffer (Primary unreachable)")

    def _audit(self, event_type: str, detail: dict) -> None:
        """Write an audit log entry."""
        entry = {
            "timestamp": time.time(),
            "node_id": self.config.node_id,
            "event_type": event_type,
            "detail": detail,
        }
        try:
            with open(self.config.audit_log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def _read_audit_log(self, limit: int = 100) -> list[dict]:
        """Read recent audit log entries."""
        try:
            with open(self.config.audit_log_path) as f:
                lines = f.readlines()
                return [json.loads(line) for line in lines[-limit:]]
        except Exception:
            return []

    def _shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        self._audit("daemon.stop", {"node_id": self.config.node_id})
        _log.info("Lite Node stopped")

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Signal handler for graceful shutdown."""
        _log.info("Received signal %d, shutting down", signum)
        self.stop()


# Entry point

def run_lite_node(config_path: str | None = None) -> None:
    """
    Entry point for running a Lite Node from CLI.

    Usage::

        nous lite-node --config lite_config.json
    """
    config = LiteNodeConfig()
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
            for key in ("node_id", "node_name", "primary_url", "primary_token",
                        "heartbeat_interval_sec", "offline_buffer_max_mb",
                        "offline_buffer_dir", "audit_log_path",
                        "allowed_capabilities", "device_adapters"):
                if key in data:
                    setattr(config, key, data[key])

    daemon = LiteNodeDaemon(config)
    daemon.start()

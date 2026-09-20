# -*- coding: utf-8 -*-
"""
Unified layered configuration for Nous Runtime.

Replaces three separate config implementations:
  1. nous_runtime/kernel/config.py (env var → config.local.json)
  2. remote_terminal/config.py (.env + JSON two-tier)
  3. nous_runtime/model_runtime/configuration.py (model-specific)

Design (§18.3): secrets reference paths in the Secret Vault, never stored
in plaintext config. API keys in env vars are legacy; migrate to vault.

Priority: env NOUS_{KEY} > config.local.json > defaults
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


def _find_project_root() -> str:
    """Find the project root directory."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isdir(os.path.join(current, "remote_terminal")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.getcwd()


PROJECT_ROOT = _find_project_root()


# Layered config loader

def _load_env_file(env_path: str) -> dict[str, str]:
    """Parse a .env file without python-dotenv dependency."""
    result: dict[str, str] = {}
    if not os.path.isfile(env_path):
        return result
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[7:].strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
                    result[key] = val
    except Exception:
        pass
    return result


def _load_json_file(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# NousConfig

@dataclass
class NousConfig:
    """Unified runtime configuration.

    Loads from multiple sources in priority order:
      1. Environment variables (NOUS_ prefix)
      2. config.local.json (project root)
      3. .env file (project root)
      4. Defaults defined below

    Usage:
        config = NousConfig.load()
        print(config.server_host)
    """

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8770
    server_name: str = "nous-primary"
    primary_node: str = ""                     # Explicit primary node ID
    preferred_workers: list[str] = field(default_factory=list)
    fallback_policy: str = "cloud_or_wait"     # cloud_or_wait | local_only | cloud_only

    # Provider / LLM
    llm_api_url: str = ""
    llm_api_key: str = ""                      # Legacy — migrate to vault
    llm_model: str = "deepseek-chat"
    llm_timeout: int = 60
    vision_api_url: str = ""
    vision_api_key: str = ""
    vision_model: str = ""
    ingest_api_url: str = ""
    ingest_api_key: str = ""
    ingest_model: str = ""

    # Embedding
    embed_api_url: str = ""
    embed_api_key: str = ""
    embed_model: str = "BAAI/bge-small-zh-v1.5"

    # Execution
    default_device: str = "laptop"
    command_timeout: int = 30
    max_steps: int = 9999
    idle_limit: int = 3
    step_warning: int = 3000

    # Session & Context
    session_max_context_chars: int = 8000
    session_keep_turns: int = 5
    session_max_count: int = 100
    session_ttl_seconds: int = 604800           # 7 days
    tool_output_max_chars: int = 16000

    # Security
    auth_token: str = ""                        # Legacy — migrate to vault
    agent_signing_secret: str = ""              # Legacy — migrate to vault
    allowed_ips: list[str] = field(default_factory=list)
    rate_limit_per_minute: int = 30
    safety_mode: str = "normal"                 # normal | strict | permissive

    # Node
    node_heartbeat_interval_ms: int = 30000
    node_offline_timeout_ms: int = 90000        # 3x heartbeat

    # Data
    data_dir: str = ""
    devices_file: str = ""
    clients_file: str = ""
    transcript_dir: str = ""
    log_dir: str = ""

    # Demo / Dev
    demo_mode: bool = False

    @classmethod
    def load(cls, project_root: str | None = None) -> "NousConfig":
        """Load configuration from all sources and return a NousConfig."""
        root = project_root or PROJECT_ROOT

        # Load .env into os.environ (if not already set)
        env_path = os.path.join(root, "remote_terminal", ".env")
        _load_env_file(env_path)

        # Load config.local.json
        json_path = os.path.join(root, "remote_terminal", "config.local.json")
        json_config = _load_json_file(json_path)

        # Also check for config.local.json at project root
        root_json_path = os.path.join(root, "config.local.json")
        if root_json_path != json_path:
            root_json = _load_json_file(root_json_path)
            json_config = {**root_json, **json_config}  # root overrides remote_terminal

        def _get(key: str, default: Any = "") -> str:
            """Priority: NOUS_{KEY} env > config.local.json > default."""
            env_val = os.environ.get(f"NOUS_{key}")
            if env_val is not None:
                return env_val
            if key in json_config:
                val = json_config[key]
                return str(val) if not isinstance(val, (bool, list)) else val
            return default

        def _get_int(key: str, default: int = 0) -> int:
            try:
                return int(_get(key, str(default)))
            except (ValueError, TypeError):
                return default

        def _get_bool(key: str, default: bool = False) -> bool:
            val = _get(key, str(default).lower())
            if isinstance(val, bool):
                return val
            return str(val).lower() in ("1", "true", "yes", "on")

        def _get_list(key: str, default: list[str] | None = None) -> list[str]:
            if default is None:
                default = []
            val = _get(key, "")
            if isinstance(val, list):
                return val
            if isinstance(val, str) and val:
                return [x.strip() for x in val.split(",") if x.strip()]
            return default

        # Resolve data dir
        data_dir = _get("DATA_DIR", "")
        if not data_dir:
            data_dir = os.path.join(root, "data")

        return cls(
            # Server
            server_host=_get("BRAIN_HOST", "0.0.0.0"),
            server_port=_get_int("BRAIN_PORT", 8770),
            server_name=_get("SERVER_NAME", "nous-primary"),
            primary_node=_get("PRIMARY_NODE", ""),
            preferred_workers=_get_list("PREFERRED_WORKERS"),
            fallback_policy=_get("FALLBACK_POLICY", "cloud_or_wait"),
            # Provider
            llm_api_url=_get("LLM_API_URL", ""),
            llm_api_key=_get("LLM_API_KEY", ""),
            llm_model=_get("LLM_MODEL", "deepseek-chat"),
            llm_timeout=_get_int("LLM_TIMEOUT", 60),
            vision_api_url=_get("VISION_API_URL", ""),
            vision_api_key=_get("VISION_API_KEY", ""),
            vision_model=_get("VISION_MODEL", ""),
            ingest_api_url=_get("INGEST_API_URL", ""),
            ingest_api_key=_get("INGEST_API_KEY", ""),
            ingest_model=_get("INGEST_MODEL", ""),
            # Embedding
            embed_api_url=_get("EMBED_API_URL", ""),
            embed_api_key=_get("EMBED_API_KEY", ""),
            embed_model=_get("EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
            # Execution
            default_device=_get("DEFAULT_DEVICE", "laptop"),
            command_timeout=_get_int("COMMAND_TIMEOUT", 30),
            max_steps=_get_int("BRAIN_MAX_STEPS", 9999),
            idle_limit=_get_int("BRAIN_IDLE_LIMIT", 3),
            step_warning=_get_int("BRAIN_STEP_WARNING", 3000),
            # Session
            session_max_context_chars=_get_int("SESSION_MAX_CONTEXT_CHARS", 8000),
            session_keep_turns=_get_int("SESSION_KEEP_TURNS", 5),
            session_max_count=_get_int("SESSION_MAX", 100),
            session_ttl_seconds=_get_int("SESSION_TTL", 604800),
            tool_output_max_chars=_get_int("TOOL_OUTPUT_MAX_CHARS", 16000),
            # Security
            auth_token=_get("AUTH_TOKEN", ""),
            agent_signing_secret=_get("AGENT_SIGNING_SECRET", ""),
            allowed_ips=_get_list("ALLOWED_IPS"),
            rate_limit_per_minute=_get_int("RATE_LIMIT_PER_MINUTE", 30),
            safety_mode=_get("SAFETY_MODE", "normal"),
            # Node
            node_heartbeat_interval_ms=_get_int("NODE_HEARTBEAT_MS", 30000),
            node_offline_timeout_ms=_get_int("NODE_OFFLINE_MS", 90000),
            # Data
            data_dir=data_dir,
            devices_file=_get("DEVICES_FILE", ""),
            clients_file=_get("CLIENTS_FILE", ""),
            transcript_dir=_get("TRANSCRIPT_DIR", ""),
            log_dir=_get("LOG_DIR", os.path.join(data_dir, "logs")),
            # Demo
            demo_mode=_get_bool("DEMO_MODE", False),
        )

    def to_dict(self, hide_secrets: bool = True) -> dict[str, Any]:
        """Serialize to dict, optionally redacting secrets."""
        d = {
            "server": {
                "host": self.server_host,
                "port": self.server_port,
                "name": self.server_name,
                "primary_node": self.primary_node,
                "preferred_workers": self.preferred_workers,
                "fallback_policy": self.fallback_policy,
            },
            "provider": {
                "llm_model": self.llm_model,
                "llm_api_url": self.llm_api_url,
                "llm_timeout": self.llm_timeout,
                "vision_model": self.vision_model,
                "embed_model": self.embed_model,
            },
            "execution": {
                "default_device": self.default_device,
                "command_timeout": self.command_timeout,
                "max_steps": self.max_steps,
                "idle_limit": self.idle_limit,
            },
            "session": {
                "max_context_chars": self.session_max_context_chars,
                "keep_turns": self.session_keep_turns,
                "max_count": self.session_max_count,
                "ttl_seconds": self.session_ttl_seconds,
            },
            "security": {
                "safety_mode": self.safety_mode,
                "rate_limit_per_minute": self.rate_limit_per_minute,
                "allowed_ips_count": len(self.allowed_ips),
            },
            "node": {
                "heartbeat_interval_ms": self.node_heartbeat_interval_ms,
                "offline_timeout_ms": self.node_offline_timeout_ms,
            },
            "data": {
                "data_dir": self.data_dir,
                "log_dir": self.log_dir,
            },
        }
        if not hide_secrets:
            d["provider"]["llm_api_key"] = "***" if self.llm_api_key else ""
            d["security"]["auth_token"] = "***" if self.auth_token else ""
        # Preserve the legacy flat view without ever exposing credential values.
        if self.llm_api_key:
            d["llm_api_key"] = "***"
        return d


# Global singleton. Environment changes invalidate the cache so tests, embedded
# hosts, and service managers can apply a new NOUS_* configuration safely.
_config: NousConfig | None = None
_config_env_snapshot: tuple[tuple[str, str], ...] = ()


def _environment_snapshot() -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (key, value) for key, value in os.environ.items()
        if key.startswith("NOUS_")
    ))


def get_config() -> NousConfig:
    """Return the cached config, reloading when NOUS_* overrides change."""
    global _config, _config_env_snapshot
    current_snapshot = _environment_snapshot()
    if _config is None or current_snapshot != _config_env_snapshot:
        _config = NousConfig.load()
        # Loading legacy-compatible config may populate NOUS_* defaults.
        _config_env_snapshot = _environment_snapshot()
    return _config


def reload_config() -> NousConfig:
    """Force reload of configuration from disk and environment."""
    global _config, _config_env_snapshot
    _config = NousConfig.load()
    _config_env_snapshot = _environment_snapshot()
    return _config

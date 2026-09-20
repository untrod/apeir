# -*- coding: utf-8 -*-
"""
Capability OS — the execution backbone of Nous.

Every system action is a capability. Instead of calling functions directly:
  call_gpt(prompt)           ← old way

You request a capability:
  request_capability("model.reason", prompt="...")   ← Capability OS

This provides:
  1. Uniform interface for all system actions
  2. Provider abstraction (swap backends without changing code)
  3. Risk-based gating (auto / confirm / block)
  4. Timeout enforcement
  5. Execution audit trail
  6. Future extensibility to robots, vehicles, space equipment

Usage:
  from nous_core.capability import register, request_capability, list_capabilities

  result = request_capability("model.reason", prompt="What is 2+2?")
  result = request_capability("device.pc.shell", command="dir")
  result = request_capability("notification.send", title="Hi", body="Hello world")
"""

from __future__ import annotations

import json as _json
import logging as _logging
import time as _time_module
from typing import Any, Callable

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.capability")

# Provider handler type
ProviderFn = Callable[..., Any]

# Provider Registry

_providers: dict[str, ProviderFn] = {}

# Risk levels
RISK_LOW = "low"          # Auto-execute, no confirmation
RISK_MEDIUM = "medium"    # Log and proceed
RISK_HIGH = "high"        # Require confirmation
RISK_CRITICAL = "critical"  # Require multi-party approval (future)

# Capability categories
CAT_MODEL = "model"
CAT_RAG = "rag"
CAT_DEVICE = "device"
CAT_NOTIFICATION = "notification"
CAT_TOOL = "tool"
CAT_AUTOMATION = "automation"
CAT_SOFTWARE = "software"
CAT_AGENT = "agent"
CAT_CONNECTOR = "connector"
CAT_CONFIGURATION = "configuration"

# Executor dispatch types
EXECUTOR_PROVIDER = "provider"
EXECUTOR_CONNECTOR = "connector"
EXECUTOR_SUBPROCESS = "subprocess"
EXECUTOR_NODE = "node"
EXECUTOR_RUNTIME = "runtime"

# Side-effect classification (declared, not inferred)
SIDE_EFFECT_READ_ONLY = "read_only"
SIDE_EFFECT_LOCAL_WRITE = "local_write"
SIDE_EFFECT_EXTERNAL_WRITE = "external_write"
SIDE_EFFECT_DESTRUCTIVE = "destructive"

# Reversibility classification (declared, not inferred)
REVERSIBILITY_REVERSIBLE = "reversible"
REVERSIBILITY_PARTIALLY = "partially_reversible"
REVERSIBILITY_IRREVERSIBLE = "irreversible"

# Well-known metadata keys for universal capability fields
META_EXECUTOR_TYPE = "executor_type"
META_SIDE_EFFECT_CLASS = "side_effect_class"
META_REVERSIBILITY = "reversibility"
META_MODEL_UNCERTAINTY = "model_uncertainty"
META_IDEMPOTENT = "idempotent"
META_PRIVILEGED = "privileged"
META_LOCALITY = "locality"
META_CONNECTION_TYPE = "connection_type"
META_RESOURCE_REQUIREMENTS = "resource_requirements"


# Registration

def _ensure_db() -> None:
    """Ensure the capability database is initialized (idempotent)."""
    try:
        from ..db import run_migrations as _run_migrations
        _run_migrations()
    except Exception:
        _log.warning("Failed to run migrations; capability DB may not be ready")


def register_capability(
    name: str,
    category: str = "",
    provider: str = "",
    description: str = "",
    risk: str = RISK_LOW,
    timeout_ms: int = 30000,
    max_retries: int = 1,
    requires_auth: bool = False,
    requires_device: bool = False,
    metadata: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    *,
    executor_type: str = "",
    side_effect_class: str = "",
    reversibility: str = "",
    model_uncertainty: float | None = None,
    idempotent: bool | None = None,
    privileged: bool = False,
    locality: str = "",
    connection_type: str = "",
    resource_requirements: dict[str, Any] | None = None,
) -> str:
    """Register a capability in the database. Auto-bootstraps DB if needed. Returns capability ID.

    Universal capability fields (stored in metadata JSON):
        executor_type: "provider" | "connector" | "subprocess" | "node" | "runtime"
        side_effect_class: "read_only" | "local_write" | "external_write" | "destructive"
        reversibility: "reversible" | "partially_reversible" | "irreversible"
        model_uncertainty: 0.0 (deterministic) to 1.0 (fully uncertain)
        idempotent: safe to retry without side-effects
        privileged: requires elevated authorization
        locality: "local" | "remote" | "embedded"
        connection_type: "none" | "ip" | "usb" | "wifi" | "ble" | "serial" | "can"
        resource_requirements: {"cpu": ..., "gpu": ..., "memory_mb": ..., ...}
    """
    _ensure_db()

    cid = _ids.make_id("cap")
    now = _time.utc_now()

    deps_json = _json.dumps(depends_on or [], ensure_ascii=False)

    # Merge universal fields into metadata
    meta = dict(metadata or {})
    if executor_type:
        meta.setdefault(META_EXECUTOR_TYPE, executor_type)
    if side_effect_class:
        meta.setdefault(META_SIDE_EFFECT_CLASS, side_effect_class)
    if reversibility:
        meta.setdefault(META_REVERSIBILITY, reversibility)
    if model_uncertainty is not None:
        meta.setdefault(META_MODEL_UNCERTAINTY, float(model_uncertainty))
    if idempotent is not None:
        meta.setdefault(META_IDEMPOTENT, bool(idempotent))
    if privileged:
        meta.setdefault(META_PRIVILEGED, True)
    if locality:
        meta.setdefault(META_LOCALITY, locality)
    if connection_type:
        meta.setdefault(META_CONNECTION_TYPE, connection_type)
    if resource_requirements:
        meta.setdefault(META_RESOURCE_REQUIREMENTS, dict(resource_requirements))

    try:
        with _connect() as db:
            existing = db.execute(
                "SELECT id FROM capabilities WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                db.execute(
                    """UPDATE capabilities SET category=?, provider=?, description=?,
                       risk=?, timeout_ms=?, max_retries=?, requires_auth=?,
                       requires_device=?, metadata=?, depends_on=?, updated_at=?
                       WHERE name=?""",
                    (category, provider, description, risk, timeout_ms, max_retries,
                     1 if requires_auth else 0, 1 if requires_device else 0,
                     _json.dumps(meta, ensure_ascii=False), deps_json, now, name),
                )
                rid = existing["id"]
            else:
                db.execute(
                    """INSERT INTO capabilities (id, name, category, provider, description,
                       risk, timeout_ms, max_retries, requires_auth, requires_device, metadata,
                       depends_on, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cid, name, category, provider, description, risk, timeout_ms,
                     max_retries, 1 if requires_auth else 0, 1 if requires_device else 0,
                     _json.dumps(meta, ensure_ascii=False), deps_json, now, now),
                )
                rid = cid

            # Rebuild edges for this capability
            db.execute("DELETE FROM capability_edges WHERE source = ?", (name,))
            for dep in (depends_on or []):
                db.execute("INSERT OR IGNORE INTO capability_edges (source, target) VALUES (?, ?)",
                          (name, dep))

        return rid
    except Exception as e:
        _log.error("register_capability(%s) failed: %s", name, e)
        return ""


def unregister_capability(name: str) -> bool:
    """
    Remove a capability from the database by name.

    Also cleans up capability_edges and capability_executions for that
    capability.  Returns True if a row was deleted, False if the
    capability wasn't found.
    """
    _ensure_db()
    try:
        with _connect() as db:
            # Delete edges pointing to or from this capability
            db.execute(
                "DELETE FROM capability_edges WHERE source = ? OR target = ?",
                (name, name),
            )
            # Delete execution log entries
            db.execute(
                "DELETE FROM capability_executions WHERE capability_name = ?",
                (name,),
            )
            cur = db.execute(
                "DELETE FROM capabilities WHERE name = ?", (name,)
            )
            deleted = cur.rowcount > 0
        if deleted:
            _log.info("Capability unregistered: %s", name)
        return deleted
    except Exception as e:
        _log.error("unregister_capability(%s) failed: %s", name, e)
        return False


def set_capability_enabled(name: str, enabled: bool) -> bool:
    """Persist the enabled state for an existing capability.

    Returns ``False`` when the capability does not exist or the registry cannot
    be updated. Callers must not report a successful lifecycle transition when
    no row changed.
    """
    _ensure_db()
    try:
        with _connect() as db:
            cur = db.execute(
                "UPDATE capabilities SET enabled = ?, updated_at = ? WHERE name = ?",
                (1 if enabled else 0, _time.utc_now(), name),
            )
            changed = cur.rowcount > 0
        if changed:
            _log.info(
                "Capability %s: %s",
                "enabled" if enabled else "disabled",
                name,
            )
        return changed
    except Exception as e:
        _log.error("set_capability_enabled(%s) failed: %s", name, e)
        return False


def unregister_capabilities_by_provider(provider: str) -> int:
    """
    Remove ALL capabilities whose provider column matches *provider*.

    Returns the number of capabilities removed.
    """
    _ensure_db()
    count = 0
    try:
        with _connect() as db:
            rows = db.execute(
                "SELECT name FROM capabilities WHERE provider = ?", (provider,)
            ).fetchall()
            names = [r["name"] for r in rows]
        for name in names:
            if unregister_capability(name):
                count += 1
        if count:
            _log.info(
                "Unregistered %d capability/capabilities for provider %r",
                count, provider,
            )
    except Exception as e:
        _log.error(
            "unregister_capabilities_by_provider(%s) failed: %s", provider, e
        )
    return count


def register_provider(provider_name: str, handler: ProviderFn):
    """Register a provider handler function."""
    _providers[provider_name] = handler
    _log.debug("Provider registered: %s", provider_name)


# The Core: request_capability()

def request_capability(
    name: str,
    *,
    session_id: str = "",
    auto_confirm: bool = False,
    **params,
) -> dict[str, Any]:
    """
    Request execution of a capability. This is THE single entry point
    for all system actions.

    Flow:
      1. Look up capability in registry
      2. Check risk gate
      3. Find provider handler
      4. Execute with timeout
      5. Record execution log
      6. Return result

    Returns: {
      "ok": bool,
      "result": ...,
      "capability": name,
      "provider": "...",
      "risk": "...",
      "duration_ms": ...,
      "execution_id": "..."
    }
    """
    eid = _ids.make_id("cex")
    started = _time_module.time()

    # 1. Look up capability
    cap = _get_capability(name)
    if not cap:
        return _fail(eid, name, "", "not_found",
                     f"Capability '{name}' is not registered")

    if not cap["enabled"]:
        return _fail(eid, name, cap["provider"], "disabled",
                     f"Capability '{name}' is disabled")

    # 2. Risk gate
    risk = cap["risk"]
    if risk in (RISK_HIGH, RISK_CRITICAL) and not auto_confirm:
        return {
            "ok": False,
            "status": "awaiting_confirmation",
            "capability": name,
            "provider": cap["provider"],
            "risk": risk,
            "message": f"Capability '{name}' requires confirmation (risk: {risk})",
            "execution_id": eid,
        }

    # 3. Find provider handler
    provider_name = cap["provider"]
    handler = _providers.get(provider_name)
    if not handler:
        return _fail(eid, name, provider_name, "no_handler",
                     f"No handler registered for provider '{provider_name}'")

    # 4. Execute
    timeout_sec = cap["timeout_ms"] / 1000.0
    result = None
    error = ""
    status = "done"

    try:
        import concurrent.futures as _futures
        with _futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(handler, **params)
            result = future.result(timeout=timeout_sec)
        if isinstance(result, dict) and not result.get("ok", True):
            status = "failed"
            error = result.get("error", "unknown")
    except _futures.TimeoutError:
        status = "timeout"
        error = f"Timed out after {timeout_sec}s"
    except Exception as e:
        status = "failed"
        error = str(e)[:500]

    # 5. Record execution
    duration = int((_time_module.time() - started) * 1000)
    _record_execution(eid, name, provider_name, session_id, status,
                      str(params)[:200], str(result)[:200] if result else "",
                      error, duration, risk, "auto")

    if status != "done":
        return _fail(eid, name, provider_name, status, error)

    return {
        "ok": True,
        "result": result,
        "capability": name,
        "provider": provider_name,
        "risk": risk,
        "duration_ms": duration,
        "execution_id": eid,
    }


# Query

def get_capability(name: str) -> dict[str, Any] | None:
    """Get a single capability by name."""
    return _get_capability(name)


def list_capabilities(category: str = "", enabled_only: bool = False) -> list[dict[str, Any]]:
    """List all registered capabilities. Auto-seeds defaults if empty."""
    try:
        # Ensure DB and migrations exist
        from ..db import run_migrations as _run_migrations
        _run_migrations()

        with _connect(readonly=True) as db:
            conds = []
            params = []
            if category:
                conds.append("category = ?"); params.append(category)
            if enabled_only:
                conds.append("enabled = 1")
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            rows = db.execute(
                f"SELECT * FROM capabilities {where} ORDER BY category, name", params
            ).fetchall()

        # Auto-seed if empty (safe: seed_default_capabilities is idempotent)
        if not rows:
            seed_default_capabilities()
            seed_composed_capabilities()
            with _connect(readonly=True) as db:
                rows = db.execute(
                    f"SELECT * FROM capabilities {where} ORDER BY category, name", params
                ).fetchall()

        return [_row_to_cap(r) for r in rows]
    except Exception:
        return []


def get_execution_log(capability_name: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Get recent execution logs."""
    limit = max(1, min(limit, 100))
    try:
        with _connect(readonly=True) as db:
            if capability_name:
                rows = db.execute(
                    "SELECT * FROM capability_executions WHERE capability_name = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (capability_name, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM capability_executions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# Bulk Registration (seed defaults)

def seed_default_capabilities() -> int:
    """Register all built-in capabilities. Idempotent."""
    defaults = [
        # Model capabilities
        ("model.reason", CAT_MODEL, "openai", "General reasoning and chat",
         RISK_LOW, 30000, 2, True, False, {}),
        ("model.code", CAT_MODEL, "claude_code", "Code generation and analysis",
         RISK_MEDIUM, 120000, 1, True, False, {}),
        ("model.embed", CAT_MODEL, "fastembed", "Text embedding for RAG",
         RISK_LOW, 10000, 1, False, False, {}),
        ("model.transcribe", CAT_MODEL, "whisper", "Speech-to-text transcription",
         RISK_LOW, 15000, 1, False, False, {}),
        ("model.tts", CAT_MODEL, "edge_tts", "Text-to-speech synthesis",
         RISK_LOW, 15000, 1, False, False, {}),

        # RAG capabilities
        ("rag.search", CAT_RAG, "chromadb", "Semantic search in knowledge base",
         RISK_LOW, 5000, 1, True, False, {}),
        ("rag.index", CAT_RAG, "chromadb", "Index document into vector store",
         RISK_LOW, 30000, 1, True, False, {}),

        # Device capabilities
        ("device.pc.shell", CAT_DEVICE, "pc_agent", "Execute shell command on PC",
         RISK_HIGH, 60000, 1, True, True, {}),
        ("device.pc.screenshot", CAT_DEVICE, "pc_agent", "Capture PC screen",
         RISK_LOW, 10000, 1, True, True, {}),
        ("device.pc.click", CAT_DEVICE, "pc_agent", "Click on PC screen at coordinates",
         RISK_HIGH, 10000, 1, True, True, {}),
        ("device.pc.type", CAT_DEVICE, "pc_agent", "Type text on PC",
         RISK_HIGH, 10000, 1, True, True, {}),
        ("device.phone.tap", CAT_DEVICE, "android", "Tap on phone screen",
         RISK_HIGH, 10000, 1, True, True, {}),
        ("device.phone.type", CAT_DEVICE, "android", "Type text on phone",
         RISK_HIGH, 10000, 1, True, True, {}),
        ("device.phone.screenshot", CAT_DEVICE, "android", "Capture phone screen",
         RISK_LOW, 10000, 1, True, True, {}),
        ("device.phone.ui_tree", CAT_DEVICE, "android", "Get phone UI element tree",
         RISK_LOW, 5000, 1, True, True, {}),
        ("device.watch.observe", CAT_DEVICE, "android", "Observe watch UI",
         RISK_LOW, 5000, 1, True, True, {}),

        # Notification capabilities
        ("notification.send", CAT_NOTIFICATION, "nous_notify", "Send notification to clients",
         RISK_LOW, 5000, 1, True, False, {}),

        # Tool capabilities
        ("network.fetch", CAT_TOOL, "nous", "Fetch public HTTP through the governed Runtime gateway",
         RISK_HIGH, 120000, 0, True, False,
         {META_EXECUTOR_TYPE: "runtime", META_SIDE_EFFECT_CLASS: SIDE_EFFECT_EXTERNAL_WRITE,
          META_REVERSIBILITY: "irreversible", META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_PRIVILEGED: True, META_LOCALITY: "remote",
          META_CONNECTION_TYPE: "ip",
          "service": "nous_runtime.evidence.web_gateway:WebGateway",
          "network_scope": "public_internet", "methods": ["GET", "HEAD", "POST"]}),
        ("tool.web_search", CAT_TOOL, "web", "Search the web",
         RISK_LOW, 15000, 1, True, False, {}),
        ("tool.file_read", CAT_TOOL, "pc_agent", "Read file from device",
         RISK_LOW, 10000, 1, True, True, {}),
        ("tool.file_write", CAT_TOOL, "pc_agent", "Write file to device",
         RISK_HIGH, 10000, 1, True, True, {}),
        ("tool.delegate_claude", CAT_TOOL, "claude_code", "Delegate to Claude Code CLI",
         RISK_HIGH, 300000, 1, True, True, {}),

        # Automation capabilities
        ("automation.trigger", CAT_AUTOMATION, "nous_automation", "Trigger an automation rule",
         RISK_LOW, 5000, 1, False, False, {}),

        # Local control-plane capabilities. These declarations keep routine,
        # reversible desktop actions from being treated as unknown/high risk.
        ("provider.create", CAT_CONFIGURATION, "nous", "Create a local Provider configuration",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_LOCALITY: "local"}),
        ("provider.configure", CAT_CONFIGURATION, "nous", "Update a local Provider configuration",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_LOCALITY: "local"}),
        ("provider.test", CAT_CONFIGURATION, "nous", "Test a Provider configuration",
         RISK_LOW, 15000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_READ_ONLY,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_LOCALITY: "local"}),
        ("provider.remove", CAT_CONFIGURATION, "nous", "Remove a local Provider configuration",
         RISK_HIGH, 10000, 1, True, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_DESTRUCTIVE,
          META_REVERSIBILITY: REVERSIBILITY_PARTIALLY, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, META_LOCALITY: "local"}),
        ("node.configure", CAT_CONFIGURATION, "nous", "Configure a Runtime node",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_LOCALITY: "local"}),
        ("task.analyze", CAT_CONFIGURATION, "nous", "Analyze a task request",
         RISK_LOW, 10000, 1, False, False, {}),
        ("task.plan", CAT_CONFIGURATION, "nous", "Plan a task request",
         RISK_LOW, 10000, 1, False, False, {}),
        ("task.create", CAT_CONFIGURATION, "nous", "Create a Runtime task",
         RISK_MEDIUM, 10000, 1, False, False, {}),
        ("task.approve", CAT_CONFIGURATION, "nous", "Record user approval for a Runtime task",
         RISK_MEDIUM, 10000, 1, False, False, {}),
        ("task.pause", CAT_CONFIGURATION, "nous", "Pause a Runtime task",
         RISK_MEDIUM, 10000, 1, False, False, {}),
        ("task.resume", CAT_CONFIGURATION, "nous", "Resume a Runtime task",
         RISK_MEDIUM, 10000, 1, False, False, {}),
        ("task.cancel", CAT_CONFIGURATION, "nous", "Cancel a Runtime task",
         RISK_MEDIUM, 10000, 1, False, False, {}),
        ("task.retry", CAT_CONFIGURATION, "nous", "Retry a Runtime task",
         RISK_MEDIUM, 10000, 1, False, False, {}),

        # Developer Platform lifecycle capabilities. Routine local operations
        # are bounded to the active workspace and remain reversible. Project
        # cancellation is declared separately so the Gate keeps approval.
        ("project.create", CAT_CONFIGURATION, "nous", "Create a local development project",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, META_LOCALITY: "local"}),
        ("project.control", CAT_CONFIGURATION, "nous", "Control a local development project",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_PARTIALLY, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, META_LOCALITY: "local"}),
        ("project.cancel", CAT_CONFIGURATION, "nous", "Cancel a development project",
         RISK_HIGH, 10000, 1, True, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_DESTRUCTIVE,
          META_REVERSIBILITY: REVERSIBILITY_PARTIALLY, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, META_LOCALITY: "local"}),
        ("experiment.create", CAT_CONFIGURATION, "nous", "Create a local experiment",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, META_LOCALITY: "local"}),
        ("experiment.evaluate", CAT_CONFIGURATION, "nous", "Evaluate measured experiment results",
         RISK_MEDIUM, 10000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_LOCALITY: "local"}),

        # Read-only product surfaces. Model output remains advisory; actions
        # requested by a conversation are governed by their own capabilities.
        ("product.chat", CAT_MODEL, "nous", "Generate a conversational response",
         RISK_LOW, 120000, 1, False, False,
         {META_SIDE_EFFECT_CLASS: SIDE_EFFECT_READ_ONLY,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.5,
          META_IDEMPOTENT: False, META_LOCALITY: "remote"}),

        # Software capabilities (v0.2.0)
        ("software.git.status", CAT_SOFTWARE, "git", "Check git working tree status",
         RISK_LOW, 10000, 1, False, False,
         {META_EXECUTOR_TYPE: EXECUTOR_SUBPROCESS, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_READ_ONLY,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, "command": ["git", "status", "--porcelain"]}),
        ("software.git.commit", CAT_SOFTWARE, "git", "Create a git commit",
         RISK_MEDIUM, 30000, 1, False, False,
         {META_EXECUTOR_TYPE: EXECUTOR_SUBPROCESS, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_PARTIALLY, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, "command": ["git", "commit", "-m", "{message}"]}),
        ("software.python.run", CAT_SOFTWARE, "python", "Execute a Python script",
         RISK_MEDIUM, 30000, 1, False, False,
         {META_EXECUTOR_TYPE: EXECUTOR_SUBPROCESS, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_LOCAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_PARTIALLY, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: False, "command": ["python", "{script}"]}),

        # Agent capabilities (v0.2.0)
        ("agent.code.execute", CAT_AGENT, "codex", "Execute a coding task via external agent",
         RISK_HIGH, 300000, 1, True, False,
         {META_EXECUTOR_TYPE: EXECUTOR_SUBPROCESS, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_EXTERNAL_WRITE,
          META_REVERSIBILITY: REVERSIBILITY_PARTIALLY, META_MODEL_UNCERTAINTY: 0.7,
          META_IDEMPOTENT: False, META_PRIVILEGED: True}),
        ("agent.code.review", CAT_AGENT, "codex", "Review code via external agent",
         RISK_MEDIUM, 120000, 1, True, False,
         {META_EXECUTOR_TYPE: EXECUTOR_SUBPROCESS, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_READ_ONLY,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.6,
          META_IDEMPOTENT: True}),

        # Device capabilities (v0.2.0 extensions)
        ("device.sensor.read", CAT_DEVICE, "esp32", "Read sensor data from embedded device",
         RISK_LOW, 5000, 1, True, True,
         {META_EXECUTOR_TYPE: EXECUTOR_NODE, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_READ_ONLY,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.0,
          META_IDEMPOTENT: True, META_LOCALITY: "embedded", META_CONNECTION_TYPE: "wifi"}),
        ("device.gpu.inference", CAT_DEVICE, "jetson", "Run ML inference on edge GPU",
         RISK_LOW, 60000, 1, True, True,
         {META_EXECUTOR_TYPE: EXECUTOR_NODE, META_SIDE_EFFECT_CLASS: SIDE_EFFECT_READ_ONLY,
          META_REVERSIBILITY: REVERSIBILITY_REVERSIBLE, META_MODEL_UNCERTAINTY: 0.4,
          META_IDEMPOTENT: True, META_LOCALITY: "local", META_CONNECTION_TYPE: "ip"}),
    ]

    count = 0
    for args in defaults:
        rid = register_capability(*args)
        if rid:
            count += 1
    if count:
        _log.info("Seeded %d default capabilities", count)
    return count



# Capability Graph — dependency resolution


def get_dependency_graph() -> dict[str, Any]:
    """
    Return the full capability dependency graph.

    Returns: {
      "nodes": [{name, category, provider, risk}, ...],
      "edges": [{source, target}, ...],
      "roots": [names with no deps],
      "composed": [names with deps]
    }
    """
    try:
        with _connect(readonly=True) as db:
            caps = db.execute(
                "SELECT name, category, provider, risk, depends_on FROM capabilities WHERE enabled=1"
            ).fetchall()
            edges = db.execute("SELECT source, target FROM capability_edges").fetchall()

        nodes, roots, composed = [], [], []
        for c in caps:
            node = {"name": c["name"], "category": c["category"],
                    "provider": c["provider"], "risk": c["risk"],
                    "depends_on": _json.loads(c["depends_on"]) if c["depends_on"] else []}
            nodes.append(node)
            if node["depends_on"]:
                composed.append(c["name"])
            else:
                roots.append(c["name"])

        return {
            "nodes": nodes,
            "edges": [{"source": e["source"], "target": e["target"]} for e in edges],
            "roots": roots,
            "composed": composed,
        }
    except Exception:
        return {"nodes": [], "edges": [], "roots": [], "composed": []}


def resolve_dependencies(name: str) -> dict[str, Any]:
    """
    Topological sort of a capability and all its transitive dependencies.

    Returns: {
      "capability": name,
      "order": [dep1, dep2, ..., self],
      "missing": [deps that aren't registered],
      "depth": max depth
    }
    """
    cap = _get_capability(name)
    if not cap:
        return {"capability": name, "order": [], "missing": [name], "depth": 0}

    deps_raw = cap.get("depends_on") or []
    if isinstance(deps_raw, str):
        try:
            deps_raw = _json.loads(deps_raw)
        except Exception:
            deps_raw = []

    visited: set[str] = set()
    order: list[str] = []
    missing: list[str] = []

    def _visit(n: str, depth: int = 0):
        if n in visited:
            return depth
        visited.add(n)
        c = _get_capability(n)
        if not c:
            if n != name:
                missing.append(n)
            return depth
        sub_deps = c.get("depends_on") or []
        if isinstance(sub_deps, str):
            try:
                sub_deps = _json.loads(sub_deps)
            except Exception:
                sub_deps = []
        max_sub_depth = depth
        for d in sub_deps:
            sd = _visit(d, depth + 1)
            if sd > max_sub_depth:
                max_sub_depth = sd
        order.append(n)
        return max_sub_depth

    max_depth = _visit(name, 0)

    return {
        "capability": name,
        "order": order,
        "missing": missing,
        "depth": max_depth,
    }


def request_capability_graph(
    name: str,
    *,
    session_id: str = "",
    **params,
) -> dict[str, Any]:
    """
    Execute a capability AND all its transitive dependencies, in dependency order.

    Each dependency's result is passed to the next as `_dep_results` context.

    Returns: {
      "ok": bool,
      "capability": name,
      "steps": [{capability, ok, duration_ms}, ...],
      "result": final result
    }
    """
    resolution = resolve_dependencies(name)
    if resolution["missing"]:
        return {
            "ok": False,
            "capability": name,
            "error": f"Missing dependencies: {', '.join(resolution['missing'])}",
            "steps": [],
        }

    dep_results: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []

    for cap_name in resolution["order"]:
        if cap_name == name:
            # Pass dependency results as context
            params["_dep_results"] = dep_results
            result = request_capability(name, session_id=session_id, **params)
        else:
            result = request_capability(cap_name, session_id=session_id)
            if result.get("ok"):
                dep_results[cap_name] = result.get("result")

        steps.append({
            "capability": cap_name,
            "ok": result.get("ok", False),
            "duration_ms": result.get("duration_ms", 0),
        })

        # Stop on dependency failure
        if not result.get("ok") and cap_name != name:
            return {
                "ok": False,
                "capability": name,
                "error": f"Dependency '{cap_name}' failed: {result.get('error', 'unknown')}",
                "steps": steps,
            }

    return {
        "ok": steps[-1]["ok"] if steps else False,
        "capability": name,
        "steps": steps,
        "result": steps[-1].get("result") if steps else None,
    }


def get_upstream_dependents(name: str) -> list[str]:
    """Find all capabilities that depend on a given capability."""
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT source FROM capability_edges WHERE target = ?", (name,)
            ).fetchall()
            return [r["source"] for r in rows]
    except Exception:
        return []


# Composed capabilities (meta-capabilities)

def seed_composed_capabilities() -> int:
    """Register composed (meta) capabilities that depend on multiple sub-capabilities."""
    composed = [
        ("study.summarize", CAT_RAG, "openai",
         "Generate a study summary: RAG retrieval + reasoning + statistics",
         RISK_LOW, 60000, 1, True, False, {},
         ["rag.search", "model.reason", "notification.send"]),

        ("study.generate_quiz", CAT_RAG, "openai",
         "Generate practice quiz: search knowledge base + reason + notify",
         RISK_LOW, 60000, 1, True, False, {},
         ["rag.search", "model.reason", "notification.send"]),

        ("device.pc.analyze", CAT_DEVICE, "pc_agent",
         "Full PC analysis: screenshot + shell + code reasoning",
         RISK_MEDIUM, 120000, 1, True, True, {},
         ["device.pc.screenshot", "device.pc.shell", "model.code"]),

        ("automation.respond_to_offline", CAT_AUTOMATION, "nous_automation",
         "When device goes offline: notify + log + create recovery job",
         RISK_LOW, 10000, 1, False, False, {},
         ["notification.send"]),

        ("learn.daily_review", CAT_RAG, "openai",
         "Complete daily review: RAG + reason + notify with report",
         RISK_LOW, 90000, 1, True, False, {},
         ["rag.search", "model.reason", "notification.send"]),
    ]

    count = 0
    for args in composed:
        rid = register_capability(args[0], category=args[1], provider=args[2],
                                   description=args[3], risk=args[4],
                                   timeout_ms=args[5], max_retries=args[6],
                                   requires_auth=args[7], requires_device=args[8],
                                   metadata=args[9], depends_on=args[10])
        if rid:
            count += 1
    if count:
        _log.info("Seeded %d composed capabilities", count)
    return count


# Internal helpers

def _get_capability(name: str) -> dict[str, Any] | None:
    try:
        with _connect(readonly=True) as db:
            row = db.execute(
                "SELECT * FROM capabilities WHERE name = ?", (name,)
            ).fetchone()
            return _row_to_cap(row) if row else None
    except Exception:
        return None


def _record_execution(eid, name, provider, sid, status, params_summary,
                      result_summary, error, duration, risk, gate):
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO capability_executions (id, capability_name, provider,
                   session_id, status, params_summary, result_summary, error,
                   duration_ms, risk, risk_gate, created_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, name, provider, sid, status, params_summary, result_summary,
                 error, duration, risk, gate, _time.utc_now(),
                 _time.utc_now() if status != "pending" else ""),
            )
    except Exception:
        pass


def _fail(eid, name, provider, status, error):
    return {
        "ok": False,
        "result": None,
        "capability": name,
        "provider": provider,
        "status": status,
        "error": error,
        "execution_id": eid,
    }


def _row_to_cap(row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["metadata"] = _json.loads(d.get("metadata", "{}"))
    except Exception:
        d["metadata"] = {}
    d["enabled"] = bool(d.get("enabled", 0))
    d["requires_auth"] = bool(d.get("requires_auth", 0))
    d["requires_device"] = bool(d.get("requires_device", 0))
    return d

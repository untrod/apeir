# -*- coding: utf-8 -*-
"""
Automation Engine — event→action rules.

When an event matches a rule's pattern (and optional conditions), an action
is triggered. Actions can be: notify users, create jobs, run tools, or call
webhooks. This runs as part of the event dispatcher pipeline.

Design:
  - Rules are stored in SQLite and loaded at dispatch time.
  - Each rule has a cooldown to prevent spam (e.g. don't notify about
    device offline more than once per 5 minutes).
  - Failed actions are logged to automation_log for debugging.
  - Built-in default rules are seeded on first run.

Usage:
  from nous_core.automation import add_rule, list_rules, evaluate_event

  # Register with the event dispatcher:
  register_handler("*", evaluate_event, name="automation-engine")

  # Or use the built-in seed function:
  seed_default_rules()
"""

from __future__ import annotations

import fnmatch as _fnmatch
import json as _json
import logging as _logging
import time as _time_module
from typing import Any

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.automation")

# Cache of enabled rules (refreshed periodically)
_rules_cache: list[dict[str, Any]] = []
_rules_cache_ts: float = 0.0
_CACHE_TTL = 30.0  # seconds


# Rule CRUD

def add_rule(
    name: str,
    event_pattern: str,
    action_type: str,
    *,
    description: str = "",
    enabled: bool = True,
    priority: int = 0,
    conditions: dict[str, Any] | None = None,
    action_config: dict[str, Any] | None = None,
    cooldown_sec: int = 0,
) -> str:
    """Create a new automation rule. Returns the rule ID."""
    rid = _ids.make_id("rule")
    now = _time.utc_now()
    cond_json = _json.dumps(conditions or {}, ensure_ascii=False)
    act_json = _json.dumps(action_config or {}, ensure_ascii=False)

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO automation_rules (id, name, description, enabled, priority,
                   event_pattern, conditions, action_type, action_config, cooldown_sec, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rid, name, description, 1 if enabled else 0, priority,
                 event_pattern, cond_json, action_type, act_json, cooldown_sec, now, now),
            )
        _log.info("Created rule '%s' (%s): %s → %s", name, rid, event_pattern, action_type)
        _invalidate_cache()
        return rid
    except Exception as e:
        _log.error("add_rule failed: %s", e)
        return ""


def update_rule(rule_id: str, **kw) -> bool:
    """Update fields on an existing rule."""
    allowed = {"name", "description", "enabled", "priority", "event_pattern",
               "conditions", "action_type", "action_config", "cooldown_sec"}
    updates = {k: v for k, v in kw.items() if k in allowed}
    if not updates:
        return False

    updates["updated_at"] = _time.utc_now()
    if "conditions" in updates and isinstance(updates["conditions"], dict):
        updates["conditions"] = _json.dumps(updates["conditions"], ensure_ascii=False)
    if "action_config" in updates and isinstance(updates["action_config"], dict):
        updates["action_config"] = _json.dumps(updates["action_config"], ensure_ascii=False)
    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0

    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [rule_id]

    try:
        with _connect() as db:
            db.execute(f"UPDATE automation_rules SET {sets} WHERE id = ?", vals)
        _invalidate_cache()
        return True
    except Exception as e:
        _log.error("update_rule failed: %s", e)
        return False


def delete_rule(rule_id: str) -> bool:
    """Delete a rule and its logs."""
    try:
        with _connect() as db:
            db.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
            db.execute("DELETE FROM automation_log WHERE rule_id = ?", (rule_id,))
        _invalidate_cache()
        return True
    except Exception:
        return False


def get_rule(rule_id: str) -> dict[str, Any] | None:
    """Read a single rule by ID."""
    try:
        with _connect(readonly=True) as db:
            row = db.execute("SELECT * FROM automation_rules WHERE id = ?",
                            (rule_id,)).fetchone()
            return _row_to_rule(row) if row else None
    except Exception:
        return None


def list_rules(enabled_only: bool = False) -> list[dict[str, Any]]:
    """List all rules, optionally only enabled ones."""
    try:
        with _connect(readonly=True) as db:
            if enabled_only:
                rows = db.execute(
                    "SELECT * FROM automation_rules WHERE enabled = 1 ORDER BY priority DESC"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM automation_rules ORDER BY priority DESC"
                ).fetchall()
            return [_row_to_rule(r) for r in rows]
    except Exception:
        return []


# Rule Evaluation (called by Event Dispatcher)

def _invalidate_cache():
    global _rules_cache, _rules_cache_ts
    _rules_cache = []
    _rules_cache_ts = 0.0


def _load_rules() -> list[dict[str, Any]]:
    """Load enabled rules, with simple in-process caching."""
    global _rules_cache, _rules_cache_ts
    now = _time_module.time()
    if _rules_cache and (now - _rules_cache_ts) < _CACHE_TTL:
        return _rules_cache
    _rules_cache = list_rules(enabled_only=True)
    _rules_cache_ts = now
    return _rules_cache


def evaluate_event(event: dict[str, Any]) -> bool:
    """
    Evaluate an event against all enabled rules and fire matching actions.

    This function is designed to be registered as a global handler
    in the event dispatcher:
      register_handler("*", evaluate_event, name="automation-engine")

    Returns True (always) — failures are logged but never block
    the dispatcher pipeline.
    """
    event_type = event.get("type", "")
    rules = _load_rules()

    fired = 0
    for rule in rules:
        if not _match_rule(rule, event):
            continue
        ok = _fire_rule(rule, event)
        if ok:
            fired += 1

    if fired:
        _log.debug("Automation: %d rule(s) fired for event %s", fired, event_type)
    return True  # Never block dispatcher


def _match_rule(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    """Check if a rule matches an event (pattern + conditions)."""
    # Pattern match
    pattern = rule.get("event_pattern", "")
    event_type = event.get("type", "")
    if not _fnmatch.fnmatch(event_type, pattern):
        return False

    # Optional conditions
    conditions = rule.get("conditions") or {}
    if isinstance(conditions, str):
        try:
            conditions = _json.loads(conditions)
        except Exception:
            conditions = {}

    if conditions:
        payload = event.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        for key, val in conditions.items():
            ev_val = payload.get(key) or event.get(key)
            if str(ev_val) != str(val):
                return False

    # Cooldown check
    cooldown = rule.get("cooldown_sec", 0)
    if cooldown > 0:
        last = rule.get("last_fired_at", "")
        if last:
            last_epoch = _time.parse_iso(last)
            if last_epoch > 0 and (_time_module.time() - last_epoch) < cooldown:
                return False

    return True


def _fire_rule(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    """Execute a rule's action. Logs result to automation_log."""
    rid = rule["id"]
    action_type = rule.get("action_type", "")
    action_config = rule.get("action_config") or {}
    if isinstance(action_config, str):
        try:
            action_config = _json.loads(action_config)
        except Exception:
            action_config = {}

    log_id = _ids.make_id("alog")
    now = _time.utc_now()

    success = True
    result = {}

    try:
        if action_type == "notify":
            result = _action_notify(rule, event, action_config)
        elif action_type == "create_job":
            result = _action_create_job(rule, event, action_config)
        elif action_type == "run_tool":
            result = _action_run_tool(rule, event, action_config)
        elif action_type == "claim_device_tasks":
            result = _action_claim_device_tasks(rule, event, action_config)
        elif action_type == "log_only":
            result = {"ok": True, "message": "logged"}
        else:
            success = False
            result = {"error": f"Unknown action_type: {action_type}"}
    except Exception as e:
        success = False
        result = {"error": str(e)}
        _log.warning("Rule '%s' action %s failed: %s", rule.get("name", rid), action_type, e)

    # Update rule metadata
    try:
        with _connect() as db:
            db.execute(
                "UPDATE automation_rules SET last_fired_at = ?, fire_count = fire_count + 1, "
                "updated_at = ? WHERE id = ?",
                (now, now, rid),
            )
    except Exception:
        pass

    # Write log
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO automation_log (id, rule_id, event_id, action_type,
                   action_result, success, fired_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (log_id, rid, event.get("id", ""), action_type,
                 _json.dumps(result, ensure_ascii=False), 1 if success else 0, now),
            )
    except Exception:
        pass

    _invalidate_cache()  # Cooldown timestamps changed
    return success


# Action Implementations

def _action_notify(rule: dict, event: dict, config: dict) -> dict:
    """Action: create a notification."""
    try:
        from ..notifications import notify
        title_tpl = config.get("title", "Automation: {rule_name}")
        body_tpl = config.get("body", "Event {event_type} fired")
        target = config.get("target_client", "")
        priority = int(config.get("priority", 0))

        title = title_tpl.format(rule_name=rule.get("name", ""),
                                 event_type=event.get("type", ""))
        body = body_tpl.format(rule_name=rule.get("name", ""),
                               event_type=event.get("type", ""),
                               event_source=event.get("source", ""),
                               event_payload=str(event.get("payload", {})))
        nid = notify("automation", title=title, body=body,
                     target_client=target, priority=priority,
                     data={"rule_id": rule["id"], "event_id": event.get("id", "")})
        return {"ok": True, "notification_id": nid}
    except ImportError:
        return {"ok": True, "notification_id": "", "warning": "notifications module not available"}


def _action_create_job(rule: dict, event: dict, config: dict) -> dict:
    """Action: create a job in the job system."""
    try:
        from ..jobs import create_job
        jid = create_job(
            config.get("job_type", "automation"),
            source=f"rule:{rule['id']}",
            session_id=event.get("session_id", ""),
            device_id=event.get("device_id", ""),
            correlation_id=event.get("correlation_id", ""),
            payload={
                "rule_id": rule["id"],
                "event_type": event.get("type", ""),
                "event_payload": event.get("payload", {}),
                **config.get("payload", {}),
            },
            timeout_sec=int(config.get("timeout_sec", 300)),
        )
        return {"ok": True, "job_id": jid}
    except ImportError:
        return {"ok": True, "job_id": "", "warning": "jobs module not available"}


def _action_run_tool(rule: dict, event: dict, config: dict) -> dict:
    """Action: execute a tool. Note: tools should be safe/read-only."""
    tool_name = config.get("tool_name", "")
    if not tool_name:
        return {"ok": False, "error": "tool_name not specified in action_config"}

    # Only allow safe read-only tools from automation
    safe_tools = {"log_event", "web_search", "weather", "learn_today_plan",
                  "learn_coverage", "learn_dashboard"}
    if tool_name not in safe_tools and not config.get("allow_dangerous"):
        return {"ok": False, "error": f"Tool '{tool_name}' not in safe automation list"}

    try:
        import tools as _tools_mod
        dummy_session = {"messages": [], "cwd": "C:\\"}
        result = _tools_mod.dispatch(
            tool_name,
            config.get("tool_args", {}),
            dummy_session,
            lambda cmd: ("automation-no-exec", -1),
        )
        return {"ok": True, "tool_output": result.output[:500],
                "tool_status": result.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Default Rules Seeding

def _action_claim_device_tasks(rule: dict, event: dict, config: dict) -> dict:
    """Action: claim pending tasks when a device comes online."""
    device_id = event.get("device_id", "")
    if not device_id:
        return {"ok": False, "error": "No device_id in event"}
    try:
        from ..capture import try_claim_pending_device_tasks
        claimed = try_claim_pending_device_tasks(device_id)
        if claimed:
            # Notify about claimed tasks
            try:
                from ..notifications import notify
                notify("task.auto_claimed",
                       title=f"🤖 {claimed} 个任务已启动",
                       body=f"设备 {device_id} 上线，自动领取了 {claimed} 个待处理任务。",
                       priority=1)
            except Exception:
                pass
        return {"ok": True, "claimed": claimed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def seed_default_rules() -> int:
    """
    Create the standard built-in rules if they don't exist.
    Idempotent — checks for existing rules before creating.

    Returns number of rules created.
    """
    existing_names = {r.get("name", "") for r in list_rules()}
    defaults = [
        {
            "name": "device-offline-notify",
            "description": "当设备离线时通知所有客户端",
            "event_pattern": "device.offline",
            "action_type": "notify",
            "priority": 10,
            "cooldown_sec": 300,
            "conditions": {},
            "action_config": {
                "title": "⚠️ 设备离线: {event_source}",
                "body": "设备 {event_source} 已离线 {event_payload}",
                "target_client": "",
                "priority": 1,
            },
        },
        {
            "name": "device-online-notify",
            "description": "当设备上线时记录日志",
            "event_pattern": "device.online",
            "action_type": "log_only",
            "priority": 5,
            "cooldown_sec": 120,
        },
        {
            "name": "confirmation-required-notify",
            "description": "当有命令需要确认时通知手机客户端",
            "event_pattern": "tool.confirmation_required",
            "action_type": "notify",
            "priority": 20,
            "cooldown_sec": 0,
            "action_config": {
                "title": "🔐 需要确认操作",
                "body": "{event_source} 请求执行: {event_payload}",
                "target_client": "phone",
                "priority": 2,
            },
        },
        {
            "name": "session-created-welcome",
            "description": "新会话创建时记录",
            "event_pattern": "session.created",
            "action_type": "log_only",
            "priority": 1,
        },
        {
            "name": "brain-startup-log",
            "description": "Brain启动时记录",
            "event_pattern": "brain.startup",
            "action_type": "log_only",
            "priority": 1,
        },
        # P1-2b: Study Question → evening review notification (fires on study.review_ready)
        {
            "name": "study-review-notify",
            "description": "学习提问后创建晚间复习提醒",
            "event_pattern": "study.review_ready",
            "action_type": "notify",
            "priority": 15,
            "cooldown_sec": 3600,
            "action_config": {
                "title": "📚 晚间复习提醒",
                "body": "你今天有未完成的复习任务，打开 Nous 继续学习吧。",
                "target_client": "phone",
                "priority": 1,
            },
        },
        # P1-2c: PC online → claim pending tasks for that device
        {
            "name": "pc-online-claim-tasks",
            "description": "设备上线时自动领取该设备的待处理任务",
            "event_pattern": "device.online",
            "action_type": "claim_device_tasks",
            "priority": 8,
            "cooldown_sec": 60,
        },
    ]

    created = 0
    for d in defaults:
        if d["name"] in existing_names:
            continue
        add_rule(**d)
        created += 1

    if created:
        _log.info("Seeded %d default automation rules", created)
    return created


# Helpers

def _row_to_rule(row) -> dict[str, Any]:
    d = dict(row)
    for field in ("conditions", "action_config"):
        try:
            d[field] = _json.loads(d.get(field, "{}"))
        except (_json.JSONDecodeError, TypeError):
            d[field] = {}
    d["enabled"] = bool(d.get("enabled", 0))
    return d

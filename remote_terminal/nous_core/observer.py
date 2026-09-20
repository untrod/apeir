# -*- coding: utf-8 -*-
"""
Observer — post-execution verification layer.

After every capability execution, verify:
  1. Did it actually execute?
  2. Did it succeed?
  3. Any anomalies?
  4. Should we retry?
  5. Is state updated?

This is the missing layer in most Agent systems — they fire and forget.
Observer makes Nous fire → verify → adapt.

Usage:
  from nous_core.observer import observe

  result = request_capability("notification.send", ...)
  verified = observe("notification.send", result, session_id="...")
  if not verified["verified"]:
      # observer auto-retried or flagged anomaly
"""

from __future__ import annotations

import json as _json
import logging as _logging
import time as _time_module
from typing import Any

from . import ids as _ids
from . import time as _time
from .db import connect as _connect

_log = _logging.getLogger("nous_core.observer")

# Verification rules per capability category
_OBSERVER_RULES: dict[str, dict] = {
    "notification": {
        "verify": "check_ack",
        "retry_on_fail": True,
        "max_retries": 2,
        "retry_delay_ms": 2000,
        "anomaly_threshold_ms": 30000,  # >30s is abnormal
    },
    "device": {
        "verify": "check_returncode",
        "retry_on_fail": False,  # Device ops don't auto-retry (dangerous)
        "max_retries": 0,
        "anomaly_threshold_ms": 60000,
    },
    "model": {
        "verify": "check_response",
        "retry_on_fail": True,
        "max_retries": 2,
        "retry_delay_ms": 1000,
        "anomaly_threshold_ms": 60000,
    },
    "rag": {
        "verify": "check_results",
        "retry_on_fail": True,
        "max_retries": 1,
        "retry_delay_ms": 500,
        "anomaly_threshold_ms": 10000,
    },
    "tool": {
        "verify": "check_output",
        "retry_on_fail": False,
        "max_retries": 0,
        "anomaly_threshold_ms": 30000,
    },
    "automation": {
        "verify": "check_triggered",
        "retry_on_fail": True,
        "max_retries": 1,
        "retry_delay_ms": 1000,
        "anomaly_threshold_ms": 5000,
    },
}

_DEFAULT_RULES = {
    "verify": "check_basic",
    "retry_on_fail": False,
    "max_retries": 0,
    "anomaly_threshold_ms": 30000,
}


def observe(
    capability: str,
    result: dict[str, Any],
    *,
    session_id: str = "",
    retry_fn=None,  # callable to retry: fn() -> new_result
) -> dict[str, Any]:
    """
    Verify a capability execution result. Returns verified result dict.

    Returns: {
      "verified": bool,
      "anomaly": bool,
      "retried": bool,
      "retry_count": int,
      "final_result": dict,
      "observations": [str, ...]
    }
    """
    cat = capability.split(".")[0] if "." in capability else capability
    rules = _OBSERVER_RULES.get(cat, _DEFAULT_RULES)
    observations: list[str] = []
    retried = False
    retry_count = 0

    # 1. Basic check: did we get a result at all?
    if result is None or not isinstance(result, dict):
        observations.append("No result returned")
        return _verdict(False, True, False, 0, result or {},
                       ["No result returned from capability"])

    ok = result.get("ok", False)
    duration = result.get("duration_ms", 0)
    error = result.get("error", "")

    # 2. Category-specific verification
    verify_fn = {
        "check_ack": _vfy_notification_ack,
        "check_returncode": _vfy_device_rc,
        "check_response": _vfy_model_response,
        "check_results": _vfy_rag_results,
        "check_output": _vfy_tool_output,
        "check_triggered": _vfy_automation,
        "check_basic": _vfy_basic,
    }.get(rules["verify"], _vfy_basic)

    verified, vfy_notes = verify_fn(result)
    observations.extend(vfy_notes)

    # 3. Anomaly detection
    anomaly = False
    if duration > rules["anomaly_threshold_ms"]:
        anomaly = True
        observations.append(f"Anomaly: duration {duration}ms > threshold {rules['anomaly_threshold_ms']}ms")

    if error and ok:
        anomaly = True
        observations.append(f"Anomaly: result has error but marked ok: {error[:100]}")

    # 4. Retry logic
    if not verified and rules["retry_on_fail"] and retry_fn and retry_count < rules["max_retries"]:
        for attempt in range(rules["max_retries"]):
            retry_count = attempt + 1
            delay = rules["retry_delay_ms"] * (2 ** attempt) / 1000.0
            _log.info("Observer: retry %d/%d for %s after %.1fs",
                      retry_count, rules["max_retries"], capability, delay)
            _time_module.sleep(delay)

            try:
                new_result = retry_fn()
                if new_result is None or not isinstance(new_result, dict):
                    new_result = {"ok": False, "error": "Retry returned None"}
            except Exception as e:
                new_result = {"ok": False, "error": f"Retry exception: {e}"}

            re_verified, re_notes = verify_fn(new_result)
            observations.append(f"Retry {retry_count}: {'OK' if re_verified else 'FAIL'}")
            observations.extend(re_notes)

            if re_verified:
                verified = True
                retried = True
                result = new_result
                anomaly = False
                break
            result = new_result

    # 5. Record observation
    _record_observation(capability, session_id, verified, anomaly,
                        retried, retry_count, observations, duration)

    return _verdict(verified, anomaly, retried, retry_count, result, observations)


# Verification functions

def _vfy_notification_ack(result: dict) -> tuple[bool, list[str]]:
    """Check notification was delivered. Currently checks notification_id exists."""
    notes = []
    r = result.get("result", result)
    nid = (r or {}).get("notification_id", "") if isinstance(r, dict) else ""
    if nid:
        notes.append(f"Notification {nid} created")
        return True, notes
    notes.append("No notification_id in result")
    return result.get("ok", False), notes


def _vfy_device_rc(result: dict) -> tuple[bool, list[str]]:
    """Check device command return code."""
    notes = []
    r = result.get("result", result)
    rc = (r or {}).get("returncode", -1) if isinstance(r, dict) else -1
    if rc == 0:
        notes.append("Return code 0 (success)")
        return True, notes
    notes.append(f"Return code {rc} (non-zero)")
    return False, notes


def _vfy_model_response(result: dict) -> tuple[bool, list[str]]:
    """Check model returned valid content."""
    notes = []
    r = result.get("result", result)
    content = (r or {}).get("content", "") if isinstance(r, dict) else ""
    if content and len(content) > 0:
        notes.append(f"Model returned {len(content)} chars")
        return True, notes
    notes.append("Model returned empty content")
    return result.get("ok", False), notes


def _vfy_rag_results(result: dict) -> tuple[bool, list[str]]:
    """Check RAG returned search results."""
    notes = []
    r = result.get("result", result)
    hits = 0
    if isinstance(r, dict):
        hits = r.get("knowledge_hits", 0) + r.get("document_hits", 0)
    if hits > 0:
        notes.append(f"RAG returned {hits} hits")
        return True, notes
    notes.append("RAG returned 0 hits")
    return result.get("ok", False), notes


def _vfy_tool_output(result: dict) -> tuple[bool, list[str]]:
    """Check tool returned output."""
    notes = []
    r = result.get("result", result)
    output = (r or {}).get("output", "") if isinstance(r, dict) else ""
    if output and len(output) > 0:
        notes.append(f"Tool output: {len(output)} chars")
        return True, notes
    return result.get("ok", False), notes


def _vfy_automation(result: dict) -> tuple[bool, list[str]]:
    """Check automation triggered correctly."""
    if result.get("ok", False):
        return True, ["Automation triggered successfully"]
    return False, [f"Automation failed: {result.get('error', 'unknown')}"]


def _vfy_basic(result: dict) -> tuple[bool, list[str]]:
    """Basic ok check."""
    return result.get("ok", False), ["Basic check: " + ("OK" if result.get("ok") else "FAIL")]


# Persistence

def _record_observation(capability, session_id, verified, anomaly,
                        retried, retry_count, observations, duration):
    """Record observer result to DB for analysis."""
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO observer_logs (id, capability, session_id, verified,
                   anomaly, retried, retry_count, observations, duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_ids.make_id("obs"), capability, session_id,
                 1 if verified else 0, 1 if anomaly else 0,
                 1 if retried else 0, retry_count,
                 _json.dumps(observations, ensure_ascii=False),
                 duration, _time.utc_now()),
            )
    except Exception:
        pass


def get_observer_stats() -> dict[str, Any]:
    """Get observer statistics: verification rates, anomaly rates, retry rates."""
    try:
        with _connect(readonly=True) as db:
            total = db.execute("SELECT COUNT(*) as n FROM observer_logs").fetchone()["n"]
            verified = db.execute(
                "SELECT COUNT(*) as n FROM observer_logs WHERE verified=1"
            ).fetchone()["n"]
            anomalies = db.execute(
                "SELECT COUNT(*) as n FROM observer_logs WHERE anomaly=1"
            ).fetchone()["n"]
            retried = db.execute(
                "SELECT COUNT(*) as n FROM observer_logs WHERE retried=1"
            ).fetchone()["n"]

            by_cap = db.execute(
                "SELECT capability, COUNT(*) as n, "
                "SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) as v, "
                "SUM(CASE WHEN anomaly=1 THEN 1 ELSE 0 END) as a "
                "FROM observer_logs GROUP BY capability ORDER BY n DESC LIMIT 10"
            ).fetchall()

            return {
                "total_observations": total,
                "verified_pct": round(verified / max(total, 1) * 100, 1),
                "anomaly_pct": round(anomalies / max(total, 1) * 100, 1),
                "retry_pct": round(retried / max(total, 1) * 100, 1),
                "by_capability": [
                    {"capability": r["capability"], "total": r["n"],
                     "verified": r["v"], "anomalies": r["a"]}
                    for r in by_cap
                ],
            }
    except Exception:
        return {"total_observations": 0}


def _verdict(verified, anomaly, retried, retry_count, result, observations):
    return {
        "verified": verified,
        "anomaly": anomaly,
        "retried": retried,
        "retry_count": retry_count,
        "final_result": result,
        "observations": observations,
    }

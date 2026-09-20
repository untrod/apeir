# -*- coding: utf-8 -*-
"""
Job System — persistent, recoverable job lifecycle management.

Replaces threading.Event for confirmation workflows and provides
a foundation for any long-running or interruptible task.

Key features:
  - Jobs survive process restarts (stored in SQLite).
  - Status state machine: pending → running → done | failed | cancelled.
  - Timeout detection: stale running jobs are auto-failed.
  - Retry with exponential backoff.
  - Callback-based execution (your code provides the work function).

Usage:
  from nous_core.jobs import create_job, claim_job, complete_job, fail_job, recover_stale_jobs

  # Create a confirmation job
  jid = create_job("confirmation", source="run_command", session_id=sid,
                   payload={"command": "rm -rf /", "dangers": [...]})

  # On restart, recover pending confirmations
  for job in list_jobs(status="pending", job_type="confirmation"):
      # re-present the confirmation to the user
      ...

  # Claim and execute
  job = claim_job(jid)
  try:
      result = do_work(job)
      complete_job(jid, result)
  except Exception as e:
      fail_job(jid, str(e))
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.jobs")

# Valid status transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"running", "cancelled"},
    "running":   {"done", "failed", "cancelled"},
    "done":      set(),       # terminal
    "failed":    {"pending"}, # can retry
    "cancelled": set(),       # terminal
}


# CRUD

def create_job(
    job_type: str,
    *,
    source: str = "",
    session_id: str = "",
    device_id: str = "",
    correlation_id: str = "",
    payload: dict[str, Any] | None = None,
    timeout_sec: int = 300,
    max_retries: int = 3,
) -> str:
    """
    Create a new job. Returns the job ID.

    The job starts in 'pending' status and must be claimed (claim_job)
    before execution.
    """
    job_id = _ids.make_job_id()
    corr_id = correlation_id or _ids.make_corr_id()
    now = _time.utc_now()
    payload_json = _json.dumps(payload or {}, ensure_ascii=False)

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO jobs (id, type, status, source, session_id, device_id,
                   correlation_id, payload, timeout_sec, max_retries, created_at)
                   VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, job_type, source, session_id, device_id,
                 corr_id, payload_json, timeout_sec, max_retries, now),
            )
        _log.debug("Created job %s type=%s", job_id, job_type)
        return job_id
    except Exception as e:
        _log.error("Failed to create job: %s", e)
        return ""


def get_job(job_id: str) -> dict[str, Any] | None:
    """Read a single job by ID."""
    try:
        with _connect(readonly=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _row_to_job(row) if row else None
    except Exception:
        return None


def list_jobs(
    status: str = "",
    job_type: str = "",
    session_id: str = "",
    device_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query jobs with optional filters."""
    limit = max(1, min(limit, 500))
    conds: list[str] = []
    params: list[Any] = []

    if status:
        conds.append("status = ?"); params.append(status)
    if job_type:
        conds.append("type = ?"); params.append(job_type)
    if session_id:
        conds.append("session_id = ?"); params.append(session_id)
    if device_id:
        conds.append("device_id = ?"); params.append(device_id)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    query = f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with _connect(readonly=True) as db:
            return [_row_to_job(r) for r in db.execute(query, params).fetchall()]
    except Exception:
        return []


def count_jobs(status: str = "", job_type: str = "") -> int:
    """Count jobs, optionally filtered."""
    try:
        with _connect(readonly=True) as db:
            conds = []
            params = []
            if status:
                conds.append("status = ?"); params.append(status)
            if job_type:
                conds.append("type = ?"); params.append(job_type)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            row = db.execute(f"SELECT COUNT(*) as cnt FROM jobs {where}", params).fetchone()
            return row["cnt"] if row else 0
    except Exception:
        return 0


# State Machine

def claim_job(job_id: str) -> dict[str, Any] | None:
    """
    Transition pending → running. Returns the job dict or None if
    the job doesn't exist or is not in pending status.

    This is atomic: only one caller can claim a given job.
    """
    now = _time.utc_now()
    try:
        with _connect() as db:
            # Check current status first
            row = db.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                _log.warning("claim_job: job %s not found", job_id)
                return None
            if row["status"] != "pending":
                _log.warning("claim_job: job %s is %s (expected pending)", job_id, row["status"])
                return None

            db.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                (now, job_id),
            )
            # Re-read to return full job
            updated = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _row_to_job(updated) if updated else None
    except Exception as e:
        _log.error("claim_job failed for %s: %s", job_id, e)
        return None


def complete_job(job_id: str, result: dict[str, Any] | str = "") -> bool:
    """Transition running → done. Store result."""
    now = _time.utc_now()
    result_json = _json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
    try:
        with _connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["status"] != "running":
                return False
            db.execute(
                """UPDATE jobs SET status = 'done', result = ?, progress = 100,
                   completed_at = ? WHERE id = ?""",
                (result_json, now, job_id),
            )
        _log.debug("Job %s completed", job_id)
        return True
    except Exception as e:
        _log.error("complete_job failed for %s: %s", job_id, e)
        return False


def fail_job(job_id: str, error: str = "", will_retry: bool = False) -> bool:
    """
    Transition running → failed (or back to pending for retry).

    If will_retry=True and retries < max_retries, the job goes back to
    'pending' with next_retry_at set (exponential backoff).
    """
    now = _time.utc_now()
    try:
        with _connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["status"] != "running":
                return False

            retries = row["retries"]
            max_retries = row["max_retries"]

            if will_retry and retries < max_retries:
                # Exponential backoff: 1s, 2s, 4s, 8s, ...
                import time as _time_module
                delay = 2 ** retries
                next_retry = _time.utc_now_epoch() + delay
                from datetime import datetime as _dt, timezone as _tz
                next_retry_at = _dt.fromtimestamp(next_retry, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                db.execute(
                    """UPDATE jobs SET status = 'pending', error = ?, retries = ?,
                       next_retry_at = ?, progress = 0, started_at = '', completed_at = ''
                       WHERE id = ?""",
                    (error, retries + 1, next_retry_at, job_id),
                )
                _log.info("Job %s failed, retry %d/%d in %ds: %s",
                          job_id, retries + 1, max_retries, delay, error)
            else:
                db.execute(
                    """UPDATE jobs SET status = 'failed', error = ?,
                       completed_at = ? WHERE id = ?""",
                    (error, now, job_id),
                )
                _log.warning("Job %s permanently failed: %s", job_id, error)
        return True
    except Exception as e:
        _log.error("fail_job failed for %s: %s", job_id, e)
        return False


def cancel_job(job_id: str) -> bool:
    """Transition pending|running → cancelled."""
    try:
        with _connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["status"] in ("done", "failed", "cancelled"):
                return False
            db.execute(
                "UPDATE jobs SET status = 'cancelled', completed_at = ? WHERE id = ?",
                (_time.utc_now(), job_id),
            )
        _log.info("Job %s cancelled", job_id)
        return True
    except Exception as e:
        _log.error("cancel_job failed for %s: %s", job_id, e)
        return False


# Recovery

def recover_stale_jobs(timeout_sec: int = 300) -> int:
    """
    Find running jobs that started more than `timeout_sec` seconds ago
    and have no completed_at — mark them as failed so they can be retried
    or cleaned up.

    Returns the number of jobs recovered.
    """
    from ..time import parse_iso as _parse_iso
    now_epoch = _time.utc_now_epoch()
    count = 0

    try:
        with _connect() as db:
            rows = db.execute(
                "SELECT id, started_at, retries, max_retries FROM jobs "
                "WHERE status = 'running' AND started_at != ''"
            ).fetchall()

            for row in rows:
                started = _parse_iso(row["started_at"])
                if started > 0 and (now_epoch - started) > timeout_sec:
                    retries = row["retries"]
                    max_r = row["max_retries"]
                    if retries < max_r:
                        # Schedule retry
                        delay = 2 ** retries
                        from datetime import datetime as _dt, timezone as _tz
                        next_retry_at = _dt.fromtimestamp(now_epoch + delay, tz=_tz.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ")
                        db.execute(
                            """UPDATE jobs SET status = 'pending',
                               error = 'timeout (recovered)', retries = ?,
                               next_retry_at = ?, progress = 0,
                               started_at = '', completed_at = ''
                               WHERE id = ?""",
                            (retries + 1, next_retry_at, row["id"]),
                        )
                    else:
                        db.execute(
                            """UPDATE jobs SET status = 'failed',
                               error = 'timeout (no retries remaining)',
                               completed_at = ?
                               WHERE id = ?""",
                            (_time.utc_now(), row["id"]),
                        )
                    count += 1
                    _log.warning("Recovered stale job %s (was running for %.0fs)",
                                 row["id"], now_epoch - started)
    except Exception as e:
        _log.error("recover_stale_jobs error: %s", e)

    return count


def retry_ready_jobs() -> list[dict[str, Any]]:
    """
    Find pending jobs whose next_retry_at has passed — they are ready
    to be claimed and executed again.

    Returns the list of ready-to-retry jobs.
    """
    now = _time.utc_now()
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE status = 'pending' AND retries > 0 "
                "AND next_retry_at != '' AND next_retry_at <= ? "
                "ORDER BY next_retry_at ASC",
                (now,),
            ).fetchall()
            return [_row_to_job(r) for r in rows]
    except Exception:
        return []


def purge_terminal_jobs(older_than_days: int = 7) -> int:
    """
    Delete done/failed/cancelled jobs older than N days to prevent
    unbounded table growth.
    """
    try:
        with _connect() as db:
            cur = db.execute(
                "DELETE FROM jobs WHERE status IN ('done', 'failed', 'cancelled') "
                "AND completed_at < datetime('now', ?)",
                (f'-{older_than_days} days',),
            )
            deleted = cur.rowcount
            if deleted:
                _log.info("Purged %d terminal jobs older than %d days", deleted, older_than_days)
            return deleted
    except Exception as e:
        _log.error("purge_terminal_jobs: %s", e)
        return 0


# Helpers

def _row_to_job(row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict with parsed JSON fields."""
    d = dict(row)
    for field in ("payload", "result"):
        try:
            d[field] = _json.loads(d.get(field, "{}"))
        except (_json.JSONDecodeError, TypeError):
            d[field] = {} if field == "payload" else d.get(field, "")
    return d

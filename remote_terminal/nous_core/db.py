# -*- coding: utf-8 -*-
"""
nous_core database layer — SQLite connection management and migration runner.

Design:
  - One database file: nous_core.db (separate from learn_data.db)
  - WAL mode + busy_timeout for concurrent read/write safety
  - Context manager pattern (same style as learn_db.py)
  - Auto-creates DB and runs migrations on first access
  - Thread-safe: each operation opens its own connection (no shared singleton)

Usage:
  from nous_core.db import get_db_path, run_migrations, connect

  run_migrations()          # call once at startup
  with connect() as db:
      db.execute("SELECT ...")
"""

from __future__ import annotations

import logging as _logging
import os as _os
import sqlite3 as _sqlite3
from contextlib import contextmanager as _contextmanager

from .config import get_config as _get_config

_log = _logging.getLogger("nous_core")


# Database path
def get_db_path() -> str:
    """Return the full path to nous_core.db (inside data_dir)."""
    data_dir = _get_config("data_dir")
    _os.makedirs(data_dir, exist_ok=True)
    return _os.path.join(data_dir, "nous_core.db")


# Connection context manager
@_contextmanager
def connect(readonly: bool = False):
    """
    Context manager for a SQLite connection.
    Auto-commits on success, rolls back on exception, always closes.

    Args:
      readonly: if True, opens in read-only mode (for queries that don't need writes)
    """
    path = get_db_path()
    # Use URI mode for read-only connections
    uri = f"file:{path}" if readonly else path
    mode = "?mode=ro" if readonly else ""
    db_path = f"{uri}{mode}" if readonly else path

    conn = _sqlite3.connect(db_path, uri=readonly)
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


# Inline bootstrap (for installed-package scenarios where
# migrations/*.sql files may not be present on disk)

def bootstrap_core_tables() -> int:
    """
    Create all required nous_core tables inline, without relying on
    migration .sql files.  Uses CREATE TABLE IF NOT EXISTS so the
    function is idempotent — safe to call on every startup.

    Returns the number of tables that were newly created.
    """
    before = _existing_table_count()

    with connect() as db:
        # 001_initial
        db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT '',
                session_id  TEXT DEFAULT '',
                device_id   TEXT DEFAULT '',
                payload     TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                processed   INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_corr ON events(correlation_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")

        # 002_jobs
        db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                source       TEXT NOT NULL DEFAULT '',
                session_id   TEXT DEFAULT '',
                device_id    TEXT DEFAULT '',
                correlation_id TEXT DEFAULT '',
                payload      TEXT NOT NULL DEFAULT '{}',
                result       TEXT DEFAULT '',
                error        TEXT DEFAULT '',
                progress     INTEGER NOT NULL DEFAULT 0,
                timeout_sec  INTEGER NOT NULL DEFAULT 300,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                started_at   TEXT DEFAULT '',
                completed_at TEXT DEFAULT '',
                retries      INTEGER NOT NULL DEFAULT 0,
                max_retries  INTEGER NOT NULL DEFAULT 3,
                next_retry_at TEXT DEFAULT ''
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at)")

        # 003_devices
        db.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL DEFAULT '',
                device_type   TEXT NOT NULL DEFAULT 'unknown',
                host          TEXT NOT NULL DEFAULT '',
                port          INTEGER NOT NULL DEFAULT 0,
                capabilities  TEXT NOT NULL DEFAULT '[]',
                metadata      TEXT NOT NULL DEFAULT '{}',
                is_online     INTEGER NOT NULL DEFAULT 0,
                last_seen     TEXT DEFAULT '',
                last_heartbeat TEXT DEFAULT '',
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_devices_online ON devices(is_online)")

        # 004_notifications
        db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id              TEXT PRIMARY KEY,
                type            TEXT NOT NULL,
                title           TEXT NOT NULL DEFAULT '',
                body            TEXT NOT NULL DEFAULT '',
                target_client   TEXT NOT NULL DEFAULT '',
                target_session  TEXT NOT NULL DEFAULT '',
                data            TEXT NOT NULL DEFAULT '{}',
                priority        INTEGER NOT NULL DEFAULT 0,
                ttl_sec         INTEGER NOT NULL DEFAULT 86400,
                read_at         TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_nfns_unread "
            "ON notifications(target_client, target_session, read_at)")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_nfns_priority "
            "ON notifications(priority DESC, created_at DESC)")

        # 005_automation
        db.execute("""
            CREATE TABLE IF NOT EXISTS automation_rules (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL DEFAULT '',
                description   TEXT NOT NULL DEFAULT '',
                enabled       INTEGER NOT NULL DEFAULT 1,
                priority      INTEGER NOT NULL DEFAULT 0,
                event_pattern TEXT NOT NULL,
                conditions    TEXT NOT NULL DEFAULT '{}',
                action_type   TEXT NOT NULL,
                action_config TEXT NOT NULL DEFAULT '{}',
                cooldown_sec  INTEGER NOT NULL DEFAULT 0,
                last_fired_at TEXT DEFAULT '',
                fire_count    INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_arules_enabled "
            "ON automation_rules(enabled, priority DESC)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS automation_log (
                id            TEXT PRIMARY KEY,
                rule_id       TEXT NOT NULL,
                event_id      TEXT NOT NULL DEFAULT '',
                action_type   TEXT NOT NULL,
                action_result TEXT NOT NULL DEFAULT '{}',
                success       INTEGER NOT NULL DEFAULT 1,
                fired_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_alog_rule ON automation_log(rule_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_alog_fired ON automation_log(fired_at)")

        # 006_audit
        db.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id            TEXT PRIMARY KEY,
                action        TEXT NOT NULL,
                actor         TEXT NOT NULL DEFAULT '',
                target        TEXT DEFAULT '',
                session_id    TEXT DEFAULT '',
                result        TEXT NOT NULL DEFAULT '',
                detail        TEXT NOT NULL DEFAULT '{}',
                ip_address    TEXT DEFAULT '',
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)")

        # 007_inbox
        db.execute("""
            CREATE TABLE IF NOT EXISTS inbox (
                id            TEXT PRIMARY KEY,
                content       TEXT NOT NULL,
                content_type  TEXT NOT NULL DEFAULT 'text',
                source        TEXT NOT NULL DEFAULT '',
                category      TEXT NOT NULL DEFAULT 'uncategorized',
                tags          TEXT NOT NULL DEFAULT '[]',
                priority      INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'new',
                session_id    TEXT DEFAULT '',
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                reviewed_at   TEXT DEFAULT '',
                archived_at   TEXT DEFAULT ''
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_inbox_category ON inbox(category)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_inbox_source ON inbox(source)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_inbox_created ON inbox(created_at)")

        # 008_study_sessions
        db.execute("""
            CREATE TABLE IF NOT EXISTS study_sessions (
                id                TEXT PRIMARY KEY,
                subject           TEXT NOT NULL DEFAULT '',
                chapter           TEXT NOT NULL DEFAULT '',
                goals             TEXT NOT NULL DEFAULT '',
                status            TEXT NOT NULL DEFAULT 'active',
                minutes           INTEGER NOT NULL DEFAULT 0,
                exercises_done    INTEGER NOT NULL DEFAULT 0,
                exercises_correct INTEGER NOT NULL DEFAULT 0,
                started_at        TEXT NOT NULL DEFAULT '',
                ended_at          TEXT DEFAULT '',
                created_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS session_questions (
                id           TEXT PRIMARY KEY,
                session_id   TEXT NOT NULL REFERENCES study_sessions(id),
                question     TEXT NOT NULL DEFAULT '',
                answer       TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS session_mistakes (
                id             TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL REFERENCES study_sessions(id),
                exercise_id    INTEGER NOT NULL DEFAULT 0,
                user_answer    TEXT NOT NULL DEFAULT '',
                correct_answer TEXT NOT NULL DEFAULT '',
                error_type     TEXT NOT NULL DEFAULT '',
                note           TEXT NOT NULL DEFAULT '',
                created_at     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_ssn_status ON study_sessions(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ssn_subject ON study_sessions(subject)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ssn_date ON study_sessions(created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sq_session ON session_questions(session_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sm_session ON session_mistakes(session_id)")

        # 009_capabilities
        # depends_on column is added by bootstrap 010 below; for a
        # fresh CREATE we include it from the start.
        db.execute("""
            CREATE TABLE IF NOT EXISTS capabilities (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL UNIQUE,
                category        TEXT NOT NULL DEFAULT '',
                provider        TEXT NOT NULL DEFAULT '',
                description     TEXT NOT NULL DEFAULT '',
                risk            TEXT NOT NULL DEFAULT 'low',
                timeout_ms      INTEGER NOT NULL DEFAULT 30000,
                max_retries     INTEGER NOT NULL DEFAULT 1,
                requires_auth   INTEGER NOT NULL DEFAULT 0,
                requires_device INTEGER NOT NULL DEFAULT 0,
                metadata        TEXT NOT NULL DEFAULT '{}',
                depends_on      TEXT NOT NULL DEFAULT '[]',
                enabled         INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_cap_category ON capabilities(category)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cap_risk ON capabilities(risk)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cap_enabled ON capabilities(enabled)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS capability_executions (
                id              TEXT PRIMARY KEY,
                capability_name TEXT NOT NULL,
                provider        TEXT NOT NULL DEFAULT '',
                session_id      TEXT DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'pending',
                params_summary  TEXT DEFAULT '',
                result_summary  TEXT DEFAULT '',
                error           TEXT DEFAULT '',
                duration_ms     INTEGER NOT NULL DEFAULT 0,
                risk            TEXT NOT NULL DEFAULT 'low',
                risk_gate       TEXT NOT NULL DEFAULT 'auto',
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at    TEXT DEFAULT ''
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_cex_cap ON capability_executions(capability_name)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cex_status ON capability_executions(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cex_created ON capability_executions(created_at)")

        # 010_capability_graph
        # depends_on may already exist (included in 009 CREATE above);
        # ALTER TABLE … ADD COLUMN is safe because of IF NOT EXISTS
        # semantics handled via try/except.
        try:
            db.execute(
                "ALTER TABLE capabilities ADD COLUMN depends_on TEXT NOT NULL DEFAULT '[]'")
        except _sqlite3.OperationalError:
            pass  # column already exists
        db.execute("""
            CREATE TABLE IF NOT EXISTS capability_edges (
                source       TEXT NOT NULL,
                target       TEXT NOT NULL,
                PRIMARY KEY (source, target)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_cedges_source ON capability_edges(source)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cedges_target ON capability_edges(target)")

        # 011_reasoning_trace
        db.execute("""
            CREATE TABLE IF NOT EXISTS reasoning_traces (
                id              TEXT PRIMARY KEY,
                session_id      TEXT DEFAULT '',
                capability      TEXT NOT NULL DEFAULT '',
                question        TEXT NOT NULL DEFAULT '',
                decision        TEXT NOT NULL DEFAULT '',
                rationale       TEXT NOT NULL DEFAULT '',
                outcome         TEXT NOT NULL DEFAULT 'unknown',
                context         TEXT NOT NULL DEFAULT '{}',
                correlation_id  TEXT DEFAULT '',
                duration_ms     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS trace_steps (
                id              TEXT PRIMARY KEY,
                trace_id        TEXT NOT NULL REFERENCES reasoning_traces(id),
                step_order      INTEGER NOT NULL DEFAULT 0,
                step_type       TEXT NOT NULL DEFAULT 'info',
                question        TEXT NOT NULL DEFAULT '',
                options         TEXT NOT NULL DEFAULT '[]',
                chosen          TEXT NOT NULL DEFAULT '',
                why             TEXT NOT NULL DEFAULT '',
                result          TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_rtrace_session ON reasoning_traces(session_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_rtrace_cap ON reasoning_traces(capability)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_rtrace_outcome ON reasoning_traces(outcome)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tstep_trace ON trace_steps(trace_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tstep_type ON trace_steps(step_type)")

        # 012_observer
        db.execute("""
            CREATE TABLE IF NOT EXISTS observer_logs (
                id              TEXT PRIMARY KEY,
                capability      TEXT NOT NULL DEFAULT '',
                session_id      TEXT DEFAULT '',
                verified        INTEGER NOT NULL DEFAULT 0,
                anomaly         INTEGER NOT NULL DEFAULT 0,
                retried         INTEGER NOT NULL DEFAULT 0,
                retry_count     INTEGER NOT NULL DEFAULT 0,
                observations    TEXT NOT NULL DEFAULT '[]',
                duration_ms     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_obs_cap ON observer_logs(capability)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_obs_verified ON observer_logs(verified)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_obs_anomaly ON observer_logs(anomaly)")

        # 013_security
        db.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id            TEXT PRIMARY KEY,
                event_type    TEXT NOT NULL,
                actor         TEXT NOT NULL DEFAULT '',
                target        TEXT NOT NULL DEFAULT '',
                risk          TEXT NOT NULL DEFAULT 'low',
                decision      TEXT NOT NULL DEFAULT '',
                detail        TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_sec_risk ON security_events(risk)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sec_decision ON security_events(decision)")

        # 014_stability
        db.execute("""
            CREATE TABLE IF NOT EXISTS stability_snapshots (
                id                  TEXT PRIMARY KEY,
                timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
                events_total        INTEGER NOT NULL DEFAULT 0,
                jobs_pending        INTEGER NOT NULL DEFAULT 0,
                jobs_running        INTEGER NOT NULL DEFAULT 0,
                jobs_failed         INTEGER NOT NULL DEFAULT 0,
                devices_total       INTEGER NOT NULL DEFAULT 0,
                devices_online      INTEGER NOT NULL DEFAULT 0,
                notifications_unread INTEGER NOT NULL DEFAULT 0,
                inbox_new           INTEGER NOT NULL DEFAULT 0,
                db_size_kb          INTEGER NOT NULL DEFAULT 0,
                uptime_seconds      REAL NOT NULL DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_stab_time ON stability_snapshots(timestamp)")

        # Record that all file-based migrations are "applied"
        # so future file-based runs don't duplicate effort
        _record_bootstrap_versions(db)

    after = _existing_table_count()
    created = after - before
    if created > 0:
        _log.info("Bootstrap created %d new table(s); %d total now exist", created, after)
    else:
        _log.debug("Bootstrap: all tables already exist (%d total)", after)
    return created


def _record_bootstrap_versions(db):
    """Mark all known migration versions as applied so that a later
    file-based run_migrations() call treats them as already-run."""
    _all_versions = list(range(1, 15))  # migrations 001–014
    for v in _all_versions:
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
            (v, f"bootstrap_{v:03d}"),
        )


def _existing_table_count() -> int:
    """Return the number of user tables currently in the database."""
    try:
        with connect(readonly=True) as db:
            rows = db.execute(
                "SELECT COUNT(*) AS n FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()
            return rows["n"] if rows else 0
    except Exception:
        return 0


# Migration runner

def run_migrations() -> int:
    """
    Run all pending migrations from nous_core/migrations/.

    Migrations are SQL files named NNN_description.sql.
    They are applied in order, and each is recorded in the schema_migrations table.
    This function is idempotent — running it multiple times is safe.

    When the migrations directory is not found (common in pip-installed
    packages where .sql files may not be bundled), the function falls
    back to ``bootstrap_core_tables()`` which creates every required
    table inline.

    Returns the number of migrations applied (0 if already up to date).
    """
    import re as _re

    migrations_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "migrations")

    if not _os.path.isdir(migrations_dir):
        _log.info("Migrations directory not found; bootstrapping inline: %s", migrations_dir)
        return bootstrap_core_tables()

    # Ensure schema_migrations table exists first (it's in 001_initial.sql,
    # but we create it here so migrations can be run in any order)
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

    # Find all .sql migration files, sorted by version number
    migration_files: list[tuple[int, str, str]] = []
    for fname in _os.listdir(migrations_dir):
        m = _re.match(r"^(\d{3})_(.+)\.sql$", fname)
        if m:
            version = int(m.group(1))
            name = m.group(2)
            full_path = _os.path.join(migrations_dir, fname)
            migration_files.append((version, name, full_path))
    migration_files.sort(key=lambda x: x[0])

    # Read already-applied versions
    with connect(readonly=True) as db:
        try:
            applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations")}
        except _sqlite3.OperationalError:
            applied = set()

    # Apply pending migrations
    count = 0
    for version, name, path in migration_files:
        if version in applied:
            continue
        _log.info("Applying migration %03d: %s", version, name)
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        with connect() as db:
            db.executescript(sql)
        count += 1

    if count > 0:
        _log.info("%d migration(s) applied successfully", count)
    else:
        _log.info("Database is up to date (no pending migrations)")

    # Defence in depth: after file-based migrations, also call
    # bootstrap to ensure any tables missing from the files are created.
    # bootstrap_core_tables is a no-op if everything already exists.
    bootstrap_core_tables()

    return count

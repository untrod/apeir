-- Migration 014: Stability snapshots
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
);
CREATE INDEX IF NOT EXISTS idx_stab_time ON stability_snapshots(timestamp);
INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (14, '014_stability');

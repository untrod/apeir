-- ============================================================
-- Nous Core — Migration 012: Observer logs
-- ============================================================

CREATE TABLE IF NOT EXISTS observer_logs (
    id              TEXT PRIMARY KEY,                    -- obs_YYYYMMDD_XXXXXXXX
    capability      TEXT NOT NULL DEFAULT '',
    session_id      TEXT DEFAULT '',
    verified        INTEGER NOT NULL DEFAULT 0,
    anomaly         INTEGER NOT NULL DEFAULT 0,
    retried         INTEGER NOT NULL DEFAULT 0,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    observations    TEXT NOT NULL DEFAULT '[]',          -- JSON array of notes
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_obs_cap ON observer_logs(capability);
CREATE INDEX IF NOT EXISTS idx_obs_verified ON observer_logs(verified);
CREATE INDEX IF NOT EXISTS idx_obs_anomaly ON observer_logs(anomaly);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (12, '012_observer');

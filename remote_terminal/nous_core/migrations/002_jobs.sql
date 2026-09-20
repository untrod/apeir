-- ============================================================
-- Nous Core — Migration 002: Jobs table
-- ============================================================
-- Adds persistent job storage for P0-3 Job System.
-- Replaces threading.Event with serializable state for crash recovery.

CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,                   -- job_YYYYMMDD_XXXXXXXX
    type         TEXT NOT NULL,                      -- "confirmation", "command", "cleanup", "notification"
    status       TEXT NOT NULL DEFAULT 'pending',    -- pending → running → done | failed | cancelled
    source       TEXT NOT NULL DEFAULT '',           -- who created this job (tool name / "brain")
    session_id   TEXT DEFAULT '',                    -- optional session correlation
    device_id    TEXT DEFAULT '',                    -- optional device correlation
    correlation_id TEXT DEFAULT '',                  -- links to events table
    payload      TEXT NOT NULL DEFAULT '{}',         -- JSON: job-specific data
    result       TEXT DEFAULT '',                    -- JSON: output on completion
    error        TEXT DEFAULT '',                    -- error message if failed
    progress     INTEGER NOT NULL DEFAULT 0,         -- 0-100 percent (for long-running jobs)
    timeout_sec  INTEGER NOT NULL DEFAULT 300,       -- max runtime in seconds
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT DEFAULT '',
    completed_at TEXT DEFAULT '',
    retries      INTEGER NOT NULL DEFAULT 0,         -- number of retry attempts
    max_retries  INTEGER NOT NULL DEFAULT 3,         -- max retry attempts before permanent failure
    next_retry_at TEXT DEFAULT ''                    -- for exponential backoff scheduling
);

-- Find jobs by status (e.g. all pending jobs)
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- Find jobs by type (e.g. all confirmation jobs)
CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type);

-- Find jobs for a specific session
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);

-- Find stale running jobs (started but too old)
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at);

-- Migration tracking
INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (2, '002_jobs');

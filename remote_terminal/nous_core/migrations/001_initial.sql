-- ============================================================
-- Nous Core — Migration 001: Initial schema
-- ============================================================
-- Creates the events table for P0-2 Event System.
-- Future migrations will add jobs, devices, notifications, audit_logs.

-- Event store — records everything that happens in the system.
-- Designed for append-heavy, read-by-time-range access patterns.
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,                  -- evt_YYYYMMDD_XXXXXXXX
    type        TEXT NOT NULL,                     -- e.g. "chat.message.received"
    source      TEXT NOT NULL DEFAULT '',          -- client_id, device_id, or "brain"
    session_id  TEXT DEFAULT '',                   -- optional session correlation
    device_id   TEXT DEFAULT '',                   -- optional device correlation
    payload     TEXT NOT NULL DEFAULT '{}',        -- JSON object with event data
    correlation_id TEXT DEFAULT '',                -- corr_YYYYMMDD_XXXXXXXX for tracing chains
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),  -- UTC ISO-8601
    processed   INTEGER NOT NULL DEFAULT 0         -- 0=pending, 1=processed (for dispatcher)
);

-- Fast lookup by event type (e.g. find all device.heartbeat events)
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

-- Fast lookup by time range (e.g. recent events for dashboard)
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);

-- Fast lookup by correlation chain (e.g. trace all events from one user action)
CREATE INDEX IF NOT EXISTS idx_events_corr ON events(correlation_id);

-- Fast lookup by session (e.g. all events in one chat session)
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

-- ============================================================
-- Migration tracking table
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (1, '001_initial');

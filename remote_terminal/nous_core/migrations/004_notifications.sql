-- ============================================================
-- Nous Core — Migration 004: Notifications table
-- ============================================================

CREATE TABLE IF NOT EXISTS notifications (
    id              TEXT PRIMARY KEY,                    -- ntf_YYYYMMDD_XXXXXXXX
    type            TEXT NOT NULL,                       -- e.g. "tool.confirmation_required"
    title           TEXT NOT NULL DEFAULT '',            -- short title
    body            TEXT NOT NULL DEFAULT '',            -- longer description
    target_client   TEXT NOT NULL DEFAULT '',            -- "phone", "watch", "laptop" — empty = broadcast
    target_session  TEXT NOT NULL DEFAULT '',            -- optional session scope
    data            TEXT NOT NULL DEFAULT '{}',          -- JSON payload
    priority        INTEGER NOT NULL DEFAULT 0,          -- 0=normal, 1=high, 2=urgent
    ttl_sec         INTEGER NOT NULL DEFAULT 86400,      -- auto-expire in seconds
    read_at         TEXT NOT NULL DEFAULT '',            -- UTC ISO-8601 when read
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fast lookup for unread notifications by client
CREATE INDEX IF NOT EXISTS idx_nfns_unread ON notifications(target_client, target_session, read_at);

-- Fast lookup by priority (urgent first)
CREATE INDEX IF NOT EXISTS idx_nfns_priority ON notifications(priority DESC, created_at DESC);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (4, '004_notifications');

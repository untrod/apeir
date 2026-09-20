-- ============================================================
-- Nous Core — Migration 007: Inbox (Quick Capture)
-- ============================================================

CREATE TABLE IF NOT EXISTS inbox (
    id            TEXT PRIMARY KEY,                    -- inb_YYYYMMDD_XXXXXXXX
    content       TEXT NOT NULL,                       -- captured text/voice transcription
    content_type  TEXT NOT NULL DEFAULT 'text',        -- "text", "voice", "photo", "link"
    source        TEXT NOT NULL DEFAULT '',            -- "phone", "watch", "web"
    category      TEXT NOT NULL DEFAULT 'uncategorized', -- auto-classified: "study", "todo", "idea", "reminder", "link", "other"
    tags          TEXT NOT NULL DEFAULT '[]',          -- JSON array of tags
    priority      INTEGER NOT NULL DEFAULT 0,          -- 0=normal, 1=high, 2=urgent
    status        TEXT NOT NULL DEFAULT 'new',         -- new → reviewed → archived → deleted
    session_id    TEXT DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at   TEXT DEFAULT '',
    archived_at   TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox(status);
CREATE INDEX IF NOT EXISTS idx_inbox_category ON inbox(category);
CREATE INDEX IF NOT EXISTS idx_inbox_source ON inbox(source);
CREATE INDEX IF NOT EXISTS idx_inbox_created ON inbox(created_at);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (7, '007_inbox');

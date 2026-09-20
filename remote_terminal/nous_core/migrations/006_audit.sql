-- ============================================================
-- Nous Core — Migration 006: Audit logs
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id            TEXT PRIMARY KEY,                    -- aud_YYYYMMDD_XXXXXXXX
    action        TEXT NOT NULL,                       -- "tool.executed", "confirmation.approved", "auth.success", etc.
    actor         TEXT NOT NULL DEFAULT '',            -- client_id, device_id, or "brain"
    target        TEXT DEFAULT '',                     -- what was acted upon (tool name, session_id, etc.)
    session_id    TEXT DEFAULT '',
    result        TEXT NOT NULL DEFAULT '',            -- "success", "denied", "error"
    detail        TEXT NOT NULL DEFAULT '{}',          -- JSON: additional context (sanitized — no secrets)
    ip_address    TEXT DEFAULT '',                     -- source IP (if from HTTP request)
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fast lookup by action type (e.g. all auth events)
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

-- Fast lookup by actor (e.g. what did client X do?)
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor);

-- Fast lookup by time range
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (6, '006_audit');

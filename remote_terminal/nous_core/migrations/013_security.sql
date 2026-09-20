-- ============================================================
-- Nous Core — Migration 013: Security events
-- ============================================================

CREATE TABLE IF NOT EXISTS security_events (
    id            TEXT PRIMARY KEY,                    -- aud_YYYYMMDD_XXXXXXXX
    event_type    TEXT NOT NULL,                       -- "risk_check", "permission_denied", "rate_limit"
    actor         TEXT NOT NULL DEFAULT '',
    target        TEXT NOT NULL DEFAULT '',
    risk          TEXT NOT NULL DEFAULT 'low',
    decision      TEXT NOT NULL DEFAULT '',            -- "allowed", "denied", "confirmed", "auto_approved"
    detail        TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sec_risk ON security_events(risk);
CREATE INDEX IF NOT EXISTS idx_sec_decision ON security_events(decision);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (13, '013_security');

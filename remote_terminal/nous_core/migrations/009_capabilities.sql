-- ============================================================
-- Nous Core — Migration 009: Capability Registry
-- ============================================================
-- Foundation of Capability OS: every system action is a capability.

CREATE TABLE IF NOT EXISTS capabilities (
    id              TEXT PRIMARY KEY,                    -- cap_YYYYMMDD_XXXXXXXX
    name            TEXT NOT NULL UNIQUE,                -- "model.reason", "device.pc.shell"
    category        TEXT NOT NULL DEFAULT '',            -- "model", "rag", "device", "notification", "tool", "automation"
    provider        TEXT NOT NULL DEFAULT '',            -- "openai", "claude", "chromadb", "pc_agent", "android"
    description     TEXT NOT NULL DEFAULT '',
    risk            TEXT NOT NULL DEFAULT 'low',         -- "low", "medium", "high", "critical"
    timeout_ms      INTEGER NOT NULL DEFAULT 30000,      -- default timeout in milliseconds
    max_retries     INTEGER NOT NULL DEFAULT 1,          -- retry count on failure
    requires_auth   INTEGER NOT NULL DEFAULT 0,          -- 0=no, 1=yes (must pass auth check)
    requires_device INTEGER NOT NULL DEFAULT 0,          -- 0=no, 1=yes (must have device online)
    enabled         INTEGER NOT NULL DEFAULT 1,
    metadata        TEXT NOT NULL DEFAULT '{}',          -- JSON: provider-specific config
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cap_category ON capabilities(category);
CREATE INDEX IF NOT EXISTS idx_cap_risk ON capabilities(risk);
CREATE INDEX IF NOT EXISTS idx_cap_enabled ON capabilities(enabled);

-- Execution log: every capability request is recorded
CREATE TABLE IF NOT EXISTS capability_executions (
    id              TEXT PRIMARY KEY,                    -- cex_YYYYMMDD_XXXXXXXX
    capability_name TEXT NOT NULL,
    provider        TEXT NOT NULL DEFAULT '',
    session_id      TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',     -- pending → running → done | failed | timeout | blocked
    params_summary  TEXT DEFAULT '',                     -- first 200 chars of params (sanitized)
    result_summary  TEXT DEFAULT '',                     -- first 200 chars of result
    error           TEXT DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    risk            TEXT NOT NULL DEFAULT 'low',
    risk_gate       TEXT NOT NULL DEFAULT 'auto',       -- "auto", "confirmed", "blocked"
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_cex_cap ON capability_executions(capability_name);
CREATE INDEX IF NOT EXISTS idx_cex_status ON capability_executions(status);
CREATE INDEX IF NOT EXISTS idx_cex_created ON capability_executions(created_at);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (9, '009_capabilities');

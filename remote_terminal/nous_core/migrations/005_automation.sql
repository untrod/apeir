-- ============================================================
-- Nous Core — Migration 005: Automation rules
-- ============================================================

CREATE TABLE IF NOT EXISTS automation_rules (
    id            TEXT PRIMARY KEY,                    -- rule_YYYYMMDD_XXXXXXXX
    name          TEXT NOT NULL DEFAULT '',            -- human-readable name
    description   TEXT NOT NULL DEFAULT '',            -- what this rule does
    enabled       INTEGER NOT NULL DEFAULT 1,          -- 0=disabled, 1=enabled
    priority      INTEGER NOT NULL DEFAULT 0,          -- higher = runs first
    event_pattern TEXT NOT NULL,                       -- fnmatch pattern e.g. "device.offline"
    conditions    TEXT NOT NULL DEFAULT '{}',          -- JSON: optional filters {device_type: "phone", ...}
    action_type   TEXT NOT NULL,                       -- "notify", "create_job", "run_tool", "webhook"
    action_config TEXT NOT NULL DEFAULT '{}',          -- JSON: action-specific config
    cooldown_sec  INTEGER NOT NULL DEFAULT 0,          -- min seconds between firings (0=no cooldown)
    last_fired_at TEXT DEFAULT '',                     -- UTC ISO-8601
    fire_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fast lookup of enabled rules matching an event pattern
CREATE INDEX IF NOT EXISTS idx_arules_enabled ON automation_rules(enabled, priority DESC);

CREATE TABLE IF NOT EXISTS automation_log (
    id            TEXT PRIMARY KEY,                    -- log_YYYYMMDD_XXXXXXXX
    rule_id       TEXT NOT NULL,                       -- which rule fired
    event_id      TEXT NOT NULL DEFAULT '',            -- which event triggered it
    action_type   TEXT NOT NULL,
    action_result TEXT NOT NULL DEFAULT '{}',          -- JSON: output/error from action
    success       INTEGER NOT NULL DEFAULT 1,          -- 0=failed, 1=success
    fired_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_alog_rule ON automation_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_alog_fired ON automation_log(fired_at);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (5, '005_automation');

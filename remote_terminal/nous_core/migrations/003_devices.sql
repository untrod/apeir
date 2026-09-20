-- ============================================================
-- Nous Core — Migration 003: Devices table
-- ============================================================

CREATE TABLE IF NOT EXISTS devices (
    id            TEXT PRIMARY KEY,                    -- stable device ID (e.g. "laptop", "phone")
    name          TEXT NOT NULL DEFAULT '',            -- display name
    device_type   TEXT NOT NULL DEFAULT 'unknown',     -- pc, phone, watch, server, unknown
    host          TEXT NOT NULL DEFAULT '',            -- IP address
    port          INTEGER NOT NULL DEFAULT 0,          -- agent port
    capabilities  TEXT NOT NULL DEFAULT '[]',          -- JSON array of capability strings
    metadata      TEXT NOT NULL DEFAULT '{}',          -- JSON: os, default_cwd, etc.
    is_online     INTEGER NOT NULL DEFAULT 0,          -- 0/1, updated on heartbeat
    last_seen     TEXT DEFAULT '',                     -- UTC ISO-8601
    last_heartbeat TEXT DEFAULT '',                    -- UTC ISO-8601
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fast lookup by device type
CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type);

-- Fast lookup of online devices
CREATE INDEX IF NOT EXISTS idx_devices_online ON devices(is_online);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (3, '003_devices');

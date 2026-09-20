-- ============================================================
-- Nous Core — Migration 010: Capability Graph
-- ============================================================
-- Adds dependency graph support to the capability system.

-- Add depends_on field to capabilities
ALTER TABLE capabilities ADD COLUMN depends_on TEXT NOT NULL DEFAULT '[]';

-- Table for cached graph edges (materialized from depends_on for fast queries)
CREATE TABLE IF NOT EXISTS capability_edges (
    source       TEXT NOT NULL,                          -- capability that depends
    target       TEXT NOT NULL,                          -- capability it depends on
    PRIMARY KEY (source, target)
);

CREATE INDEX IF NOT EXISTS idx_cedges_source ON capability_edges(source);
CREATE INDEX IF NOT EXISTS idx_cedges_target ON capability_edges(target);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (10, '010_capability_graph');

-- ============================================================
-- Nous Core — Migration 011: Reasoning Trace
-- ============================================================
-- Captures not just WHAT happened, but WHY each decision was made.

CREATE TABLE IF NOT EXISTS reasoning_traces (
    id              TEXT PRIMARY KEY,                    -- rtr_YYYYMMDD_XXXXXXXX
    session_id      TEXT DEFAULT '',
    capability      TEXT NOT NULL DEFAULT '',            -- which capability was requested
    question        TEXT NOT NULL DEFAULT '',            -- what was being decided
    decision        TEXT NOT NULL DEFAULT '',            -- what was chosen
    rationale       TEXT NOT NULL DEFAULT '',            -- why this choice
    outcome         TEXT NOT NULL DEFAULT 'unknown',     -- success / failure / partial / cancelled
    context         TEXT NOT NULL DEFAULT '{}',          -- JSON: relevant state at decision time
    correlation_id  TEXT DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trace_steps (
    id              TEXT PRIMARY KEY,                    -- trs_YYYYMMDD_XXXXXXXX
    trace_id        TEXT NOT NULL REFERENCES reasoning_traces(id),
    step_order      INTEGER NOT NULL DEFAULT 0,          -- order within the trace
    step_type       TEXT NOT NULL DEFAULT 'info',        -- model_choice, device_choice, tool_choice,
                                                         -- error, branch, dependency, observation
    question        TEXT NOT NULL DEFAULT '',            -- micro-decision being made
    options         TEXT NOT NULL DEFAULT '[]',          -- JSON: alternatives considered
    chosen          TEXT NOT NULL DEFAULT '',            -- what was picked
    why             TEXT NOT NULL DEFAULT '',            -- why was this picked
    result          TEXT NOT NULL DEFAULT '',            -- what happened as a result
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rtrace_session ON reasoning_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_rtrace_cap ON reasoning_traces(capability);
CREATE INDEX IF NOT EXISTS idx_rtrace_outcome ON reasoning_traces(outcome);
CREATE INDEX IF NOT EXISTS idx_tstep_trace ON trace_steps(trace_id);
CREATE INDEX IF NOT EXISTS idx_tstep_type ON trace_steps(step_type);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (11, '011_reasoning_trace');

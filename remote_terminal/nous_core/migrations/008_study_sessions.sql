-- ============================================================
-- Nous Core — Migration 008: Study Session tables
-- ============================================================

CREATE TABLE IF NOT EXISTS study_sessions (
    id                TEXT PRIMARY KEY,                    -- ssn_YYYYMMDD_XXXXXXXX
    subject           TEXT NOT NULL DEFAULT '',
    chapter           TEXT NOT NULL DEFAULT '',
    goals             TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'active',     -- active → completed → abandoned
    minutes           INTEGER NOT NULL DEFAULT 0,
    exercises_done    INTEGER NOT NULL DEFAULT 0,
    exercises_correct INTEGER NOT NULL DEFAULT 0,
    started_at        TEXT NOT NULL DEFAULT '',
    ended_at          TEXT DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS session_questions (
    id           TEXT PRIMARY KEY,                         -- stq_YYYYMMDD_XXXXXXXX
    session_id   TEXT NOT NULL REFERENCES study_sessions(id),
    question     TEXT NOT NULL DEFAULT '',
    answer       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS session_mistakes (
    id             TEXT PRIMARY KEY,                       -- stm_YYYYMMDD_XXXXXXXX
    session_id     TEXT NOT NULL REFERENCES study_sessions(id),
    exercise_id    INTEGER NOT NULL DEFAULT 0,
    user_answer    TEXT NOT NULL DEFAULT '',
    correct_answer TEXT NOT NULL DEFAULT '',
    error_type     TEXT NOT NULL DEFAULT '',               -- concept, calculation, careless, memory
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ssn_status ON study_sessions(status);
CREATE INDEX IF NOT EXISTS idx_ssn_subject ON study_sessions(subject);
CREATE INDEX IF NOT EXISTS idx_ssn_date ON study_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sq_session ON session_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_sm_session ON session_mistakes(session_id);

INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (8, '008_study_sessions');

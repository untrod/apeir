# Learning Domain Migration Plan v1.0

## Principle

The Runtime manages HOW learning works. Packs provide WHAT is being learned.

## Current State

`learn_db.py` contains 22 tables. Some are generic learning primitives; others are domain-specific to exam preparation.

## Classification

### Generic Runtime Tables (Stay)

| Table | Purpose | Why Generic |
|-------|---------|-------------|
| `knowledge_points` | Tree-structured knowledge entries | Any domain has knowledge |
| `formulas` | LaTeX formulas with SM-2 | Generic spaced repetition |
| `exercises` | Question bank | Any domain has exercises |
| `mistake_records` | Error tracking | Universal learning pattern |
| `progress_log` | Daily study summary | Generic progress tracking |
| `flashcards` | Anki-style cards | Generic flashcard system |
| `focus_sessions` | Pomodoro timer | Generic focus tracking |
| `quick_notes` | Free-text notes | Generic note-taking |
| `question_templates` | Parameterized questions | Generic question generation |

### Domain-Specific Tables (Move to Study Pack)

| Table | Purpose | Why Domain-Specific |
|-------|---------|---------------------|
| `exams` | Exam records with dates | Tied to specific exams |
| `study_plans` | Plans tied to exams | Exam-specific planning |
| `content_gaps` | Syllabus gaps per exam | Exam syllabus tracking |
| `courses` | Curriculum tree | Course structure is domain |
| `chapters` | Chapter organization | Domain-specific hierarchy |
| `study_phases` | Multi-phase exam prep | "Phase 1/2/3" is exam concept |
| `daily_plans` | Per-day subject content | Has math/english/cs/chinese columns |
| `daily_checkins` | Daily subject checkin | References specific subjects |
| `phase_summaries` | Cross-phase memory | Exam phase concept |

### Mixed Tables (Split)

| Table | Generic Part | Domain Part |
|-------|-------------|-------------|
| `documents` | filename, filepath, filetype, parsed, status | `stage`, `doc_type` (exam-specific) |

## Migration Path

### Phase A: Deprecation (v1.0.0)
- Mark domain tables with `DEPRECATED: will move to Study Pack in v1.1` comments
- Add `warnings.warn(DeprecationWarning)` on first access
- All existing code continues to work

### Phase B: Extraction (v1.1)
- Create `packs/study_pack/` with migration scripts
- Move domain table schemas to Study Pack
- Provide data migration tool: `nous pack migrate study_pack`
- Keep generic tables in learn_db.py

### Phase C: Removal (v2.0)
- Remove domain tables from learn_db.py
- Study Pack is the only way to use exam/phase/course features
- Existing data preserved in Study Pack's own database

## What the Runtime Guarantees

After migration, the Runtime provides:
1. `MasteryState` — per-item mastery tracking
2. `SpacedRepetitionScheduler` — SM-2 scheduling
3. `ProgressTracker` — coverage, streaks, weak-spot detection
4. `StudySession` — session lifecycle (start/record/end)
5. Generic database tables for knowledge, exercises, formulas, mistakes

The Runtime never knows:
- What subjects exist
- What exams the user is preparing for
- What phase or sprint they're in
- What their course structure looks like

# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — SQLite 数据库层。

表:
  knowledge_points — 知识点(树形结构,含认知状态)
  formulas         — 公式库(LaTeX+纯文本,SM-2调度)
  exercises        — 题库(关联知识点+公式,Bloom层次)
  mistake_records  — 错题记录(AI分析+知识断点)
  documents        — 上传的文档(PDF/Word/txt)
  progress_log     — 每日学习记录

设计原则:
  - 数据库文件路径由 config 管理，默认 learn_data.db
  - 所有写操作返回影响行数，读操作返回 dict/list
  - 不依赖 Brain/Agent，纯本地数据库操作
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager


def _db_path():
    import config
    return getattr(config, "LEARN_DB_PATH", "") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "learn_data.db")


@contextmanager
def _conn():
    db = sqlite3.connect(_db_path())
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    """创建所有表(幂等)。首次使用时自动调用。"""
    with _conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL DEFAULT '',
            chapter TEXT DEFAULT '',
            section TEXT DEFAULT '',
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            parent_id INTEGER DEFAULT NULL,
            prerequisites TEXT DEFAULT '[]',
            difficulty INTEGER DEFAULT 2,
            source_doc TEXT DEFAULT '',
            source_page INTEGER DEFAULT 0,
            mastery REAL DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            last_reviewed TEXT DEFAULT '',
            next_review TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (parent_id) REFERENCES knowledge_points(id)
        );

        CREATE TABLE IF NOT EXISTS formulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            latex TEXT DEFAULT '',
            plain_text TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            knowledge_point_id INTEGER DEFAULT NULL,
            source_doc TEXT DEFAULT '',
            source_page INTEGER DEFAULT 0,
            importance INTEGER DEFAULT 2,
            usage_tags TEXT DEFAULT '[]',
            learned_at TEXT DEFAULT '',
            last_reviewed TEXT DEFAULT '',
            next_review TEXT DEFAULT '',
            review_count INTEGER DEFAULT 0,
            mastery REAL DEFAULT 0,
            FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
        );

        CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            knowledge_point_id INTEGER DEFAULT NULL,
            formula_ids TEXT DEFAULT '[]',
            question TEXT NOT NULL,
            answer TEXT DEFAULT '',
            solution_steps TEXT DEFAULT '[]',
            difficulty INTEGER DEFAULT 2,
            bloom_level INTEGER DEFAULT 3,
            source_doc TEXT DEFAULT '',
            source_page INTEGER DEFAULT 0,
            is_mistake INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
        );

        CREATE TABLE IF NOT EXISTS mistake_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_id INTEGER DEFAULT NULL,
            user_answer TEXT DEFAULT '',
            error_type TEXT DEFAULT '',
            ai_analysis TEXT DEFAULT '',
            knowledge_gap_id INTEGER DEFAULT NULL,
            reviewed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (exercise_id) REFERENCES exercises(id),
            FOREIGN KEY (knowledge_gap_id) REFERENCES knowledge_points(id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filepath TEXT DEFAULT '',
            filetype TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            total_pages INTEGER DEFAULT 0,
            parsed INTEGER DEFAULT 0,
            kp_count INTEGER DEFAULT 0,
            ex_count INTEGER DEFAULT 0,
            uploaded_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS progress_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL DEFAULT (date('now')),
            subject TEXT DEFAULT '',
            study_minutes INTEGER DEFAULT 0,
            formulas_reviewed INTEGER DEFAULT 0,
            exercises_done INTEGER DEFAULT 0,
            exercises_correct INTEGER DEFAULT 0,
            weak_topics TEXT DEFAULT '[]',
            notes TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_kp_subject ON knowledge_points(subject);
        CREATE INDEX IF NOT EXISTS idx_kp_parent ON knowledge_points(parent_id);
        CREATE INDEX IF NOT EXISTS idx_fm_subject ON formulas(subject);
        CREATE INDEX IF NOT EXISTS idx_fm_kp ON formulas(knowledge_point_id);
        CREATE INDEX IF NOT EXISTS idx_ex_kp ON exercises(knowledge_point_id);
        CREATE INDEX IF NOT EXISTS idx_mr_ex ON mistake_records(exercise_id);
        CREATE INDEX IF NOT EXISTS idx_pl_date ON progress_log(date);
        CREATE INDEX IF NOT EXISTS idx_docs_parsed ON documents(parsed);

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            subjects TEXT DEFAULT '[]',
            scope TEXT DEFAULT '',
            target_score TEXT DEFAULT '',
            status TEXT DEFAULT 'upcoming',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS study_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            plan_type TEXT DEFAULT 'daily',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            exam_id INTEGER DEFAULT NULL,
            tasks TEXT DEFAULT '[]',
            progress REAL DEFAULT 0,
            auto_generated INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (exam_id) REFERENCES exams(id)
        );

        CREATE TABLE IF NOT EXISTS content_gaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER DEFAULT NULL,
            subject TEXT DEFAULT '',
            topic TEXT NOT NULL,
            covered INTEGER DEFAULT 0,
            priority INTEGER DEFAULT 3,
            source_hint TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            FOREIGN KEY (exam_id) REFERENCES exams(id)
        );

        CREATE INDEX IF NOT EXISTS idx_exams_date ON exams(exam_date);
        CREATE INDEX IF NOT EXISTS idx_plans_dates ON study_plans(start_date, end_date);
        CREATE INDEX IF NOT EXISTS idx_gaps_exam ON content_gaps(exam_id);

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT DEFAULT '',
            description TEXT DEFAULT '',
            total_chapters INTEGER DEFAULT 0,
            total_kps INTEGER DEFAULT 0,
            completed_kps INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            kp_count INTEGER DEFAULT 0,
            completed_count INTEGER DEFAULT 0,
            estimated_hours REAL DEFAULT 1.0,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            hint TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            knowledge_point_id INTEGER DEFAULT NULL,
            source TEXT DEFAULT '',
            deck TEXT DEFAULT 'default',
            ease REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 1,
            repetitions INTEGER DEFAULT 0,
            next_review TEXT DEFAULT (date('now')),
            mastery REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
        );

        CREATE INDEX IF NOT EXISTS idx_chapters_course ON chapters(course_id);
        CREATE INDEX IF NOT EXISTS idx_cards_review ON flashcards(next_review);
        CREATE INDEX IF NOT EXISTS idx_cards_deck ON flashcards(deck);

        CREATE TABLE IF NOT EXISTS focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT DEFAULT '',
            task TEXT DEFAULT '',
            duration_seconds INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 参数化题目模板（零延迟生成题目，不依赖 LLM）
        CREATE TABLE IF NOT EXISTS question_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT DEFAULT '',
            knowledge_point_id INTEGER REFERENCES knowledge_points(id),
            template TEXT NOT NULL,           -- 题目模板: "求 {func} 在 x={x0} 处的导数"
            param_ranges TEXT NOT NULL,       -- JSON: {"func":["x^2","sin(x)","e^x"],"x0":[0,1,2]}
            answer_expr TEXT NOT NULL,        -- Python 表达式根据 params 计算答案
            difficulty INTEGER DEFAULT 3,     -- 1-6 (Bloom)
            bloom_level INTEGER DEFAULT 2,    -- 1-6
            explanation TEXT DEFAULT '',      -- 解题步骤模板
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 已生成的题目实例（缓存，下次不重复生成）
        CREATE TABLE IF NOT EXISTS question_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER REFERENCES question_templates(id),
            params TEXT NOT NULL,             -- JSON: {"func":"x^2","x0":3}
            answer TEXT NOT NULL,             -- 计算好的答案
            used_count INTEGER DEFAULT 0,     -- 被使用的次数
            last_used TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS quick_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            subject TEXT DEFAULT '',
            category TEXT DEFAULT 'general',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 学习阶段计划（备考阶段一/阶段二等）
        CREATE TABLE IF NOT EXISTS study_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            goal TEXT DEFAULT '',
            strategy TEXT DEFAULT '',
            daily_schedule TEXT DEFAULT '',
            acceptance_criteria TEXT DEFAULT '',
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',      -- active/completed/paused
            current_day INTEGER DEFAULT 1,     -- 当前学到第几天(1-based)
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 每日学习计划
        CREATE TABLE IF NOT EXISTS daily_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phase_id INTEGER NOT NULL REFERENCES study_phases(id) ON DELETE CASCADE,
            date TEXT NOT NULL,                -- 原计划日期 YYYY-MM-DD（固定不变）
            day_number INTEGER DEFAULT 0,      -- 第几天 (1-based)
            phase_position TEXT DEFAULT '',    -- 该日在阶段中的定位
            math_content TEXT DEFAULT '',      -- 高数内容
            english_content TEXT DEFAULT '',   -- 英语内容
            cs_content TEXT DEFAULT '',        -- 计算机内容
            chinese_content TEXT DEFAULT '',   -- 语文内容
            study_time TEXT DEFAULT '',        -- 建议学习时间
            expected_output TEXT DEFAULT '',   -- 当日产出
            review_focus TEXT DEFAULT '',      -- 复盘重点
            math_detail TEXT DEFAULT '',       -- 高数详细讲义
            english_detail TEXT DEFAULT '',    -- 英语详细讲义
            cs_detail TEXT DEFAULT '',         -- 计算机详细讲义
            chinese_detail TEXT DEFAULT '',    -- 语文详细讲义
            must_know TEXT DEFAULT '',         -- 今日必须会/必须背
            exercises TEXT DEFAULT '',         -- 练习与检验
            status TEXT DEFAULT 'pending',     -- pending/done/partial/skipped
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(phase_id, date)             -- 防止重复导入
        );

        -- 每日打卡/反思
        CREATE TABLE IF NOT EXISTS daily_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER REFERENCES daily_plans(id),
            date TEXT NOT NULL,
            completed_subjects TEXT DEFAULT '', -- JSON: {"math":true, "english":false, ...}
            study_duration INTEGER DEFAULT 0,   -- 实际学习分钟数
            reflection TEXT DEFAULT '',         -- 当日反思
            difficulties TEXT DEFAULT '',       -- 遇到的困难
            achievements TEXT DEFAULT '',       -- 今日收获
            mood INTEGER DEFAULT 3,             -- 心情 1-5
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 阶段总结/记忆（跨阶段传承）
        CREATE TABLE IF NOT EXISTS phase_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phase_id INTEGER REFERENCES study_phases(id),
            subject TEXT DEFAULT '',           -- math/english/cs/chinese/all
            summary_type TEXT DEFAULT '',      -- weak_points/strong_points/mistakes/strategies/next_phase_tips
            content TEXT DEFAULT '',           -- AI 生成的总结内容
            key_data TEXT DEFAULT '',          -- JSON: 关键数据（掌握度变化/正确率等）
            created_at TEXT DEFAULT (datetime('now'))
        );

        """)
    _migrate()
    # 预置数学题目模板(幂等,已存在则跳过)
    try:
        n = seed_math_templates()
        if n > 0:
            import logging
            logging.getLogger("learn_db").info("已预置 %d 个数学题目模板", n)
    except Exception:
        pass


def _migrate():
    """幂等加列(老库升级用)。"""
    cols = {
        "documents": [("stage", "TEXT DEFAULT ''"), ("doc_type", "TEXT DEFAULT ''"),
                      ("status", "TEXT DEFAULT ''"), ("note", "TEXT DEFAULT ''"),
                      ("progress", "TEXT DEFAULT ''")],
        "knowledge_points": [("stage", "TEXT DEFAULT ''")],
        "study_phases": [("current_day", "INTEGER DEFAULT 1")],
        "daily_plans": [("day_number", "INTEGER DEFAULT 0")],
    }
    with _conn() as db:
        for table, adds in cols.items():
            try:
                existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
            except Exception:
                continue
            for name, decl in adds:
                if name not in existing:
                    try:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                    except Exception:
                        pass



# 知识点 CRUD


def add_knowledge_point(subject, title, content="", chapter="", section="",
                        parent_id=None, prerequisites=None, difficulty=2,
                        source_doc="", source_page=0, stage="") -> int:
    """添加知识点,返回 id。"""
    with _conn() as db:
        c = db.execute("""
            INSERT INTO knowledge_points (subject, chapter, section, title, content,
                parent_id, prerequisites, difficulty, source_doc, source_page, stage)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (subject, chapter, section, title, content, parent_id,
              json.dumps(prerequisites or [], ensure_ascii=False),
              difficulty, source_doc, source_page, stage))
        return c.lastrowid


def get_knowledge_point(kp_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM knowledge_points WHERE id=?", (kp_id,)).fetchone()
        return dict(row) if row else {}


def search_knowledge_points(subject="", keyword="", source_doc="", limit=20) -> list:
    """按科目/关键词/来源文档搜索知识点。"""
    with _conn() as db:
        q = "SELECT id,subject,chapter,section,title,content,parent_id,difficulty,mastery FROM knowledge_points WHERE 1=1"
        params = []
        if subject:
            q += " AND subject=?"
            params.append(subject)
        if keyword:
            q += " AND (title LIKE ? OR content LIKE ?)"
            kw = f"%{keyword}%"
            params.extend([kw, kw])
        if source_doc:
            q += " AND source_doc=?"
            params.append(source_doc)
        q += " ORDER BY subject,chapter,section LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def get_kp_tree(subject="", parent_id=None) -> list:
    """获取知识树(递归子节点)。"""
    with _conn() as db:
        if subject:
            roots = db.execute(
                "SELECT * FROM knowledge_points WHERE subject=? AND parent_id IS NULL "
                "ORDER BY chapter,section", (subject,)).fetchall()
        elif parent_id is not None:
            roots = db.execute(
                "SELECT * FROM knowledge_points WHERE parent_id=? "
                "ORDER BY chapter,section", (parent_id,)).fetchall()
        else:
            roots = db.execute(
                "SELECT * FROM knowledge_points WHERE parent_id IS NULL "
                "ORDER BY subject,chapter,section").fetchall()
        result = []
        for r in roots:
            node = dict(r)
            node["children"] = get_kp_tree(subject="", parent_id=r["id"])
            result.append(node)
        return result


def get_next_unlearned_kp(subject="", limit=5, mastery_below=40) -> list:
    """按章节顺序取"还没学/掌握低"的真实知识点(有正文、未排过复习),用于推进新内容。"""
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        q = """SELECT id,subject,chapter,section,title,mastery FROM knowledge_points
               WHERE mastery < ? AND content != ''
               AND (next_review IS NULL OR next_review = '')"""
        params = [mastery_below]
        if subject:
            q += " AND subject=?"; params.append(subject)
        q += " ORDER BY subject, chapter, section, id LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def update_kp_mastery(kp_id: int, mastery: float):
    """更新知识点掌握度 + 复习计数。"""
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        db.execute("""
            UPDATE knowledge_points
            SET mastery=?, review_count=review_count+1, last_reviewed=?
            WHERE id=?
        """, (max(0, min(100, mastery)), today, kp_id))


def update_kp_next_review(kp_id: int, next_review: str):
    with _conn() as db:
        db.execute("UPDATE knowledge_points SET next_review=? WHERE id=?", (next_review, kp_id))


def get_due_knowledge_points(subject="", limit=10) -> list:
    """获取到期待复习的知识点。仅含【学过的】(next_review 已设置且 ≤ 今天);
    从没学过的(next_review='')属于"待学习"不算"待复习",不计入。"""
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        q = """SELECT * FROM knowledge_points
               WHERE next_review != '' AND next_review <= ?
               AND mastery < 80"""
        params = [today]
        if subject:
            q += " AND subject=?"
            params.append(subject)
        q += " ORDER BY mastery ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]



# 公式 CRUD


def add_formula(name, latex="", plain_text="", subject="",
                knowledge_point_id=None, source_doc="", source_page=0,
                importance=2, usage_tags=None) -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO formulas (name, latex, plain_text, subject, knowledge_point_id,
                source_doc, source_page, importance, usage_tags, learned_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (name, latex, plain_text, subject, knowledge_point_id,
              source_doc, source_page, importance,
              json.dumps(usage_tags or [], ensure_ascii=False),
              time.strftime("%Y-%m-%d")))
        return c.lastrowid


def get_formula(f_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM formulas WHERE id=?", (f_id,)).fetchone()
        return dict(row) if row else {}


def search_formulas(subject="", keyword="", limit=20) -> list:
    with _conn() as db:
        q = "SELECT * FROM formulas WHERE 1=1"
        params = []
        if subject:
            q += " AND subject=?"
            params.append(subject)
        if keyword:
            kw = f"%{keyword}%"
            q += " AND (name LIKE ? OR plain_text LIKE ?)"
            params.extend([kw, kw])
        q += " ORDER BY importance DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def get_due_formulas(subject="", limit=5) -> list:
    """获取到期待复习的公式(SM-2 调度)。"""
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        q = """SELECT * FROM formulas
               WHERE (next_review <= ? OR next_review = '')
               AND mastery < 80"""
        params = [today]
        if subject:
            q += " AND subject=?"
            params.append(subject)
        q += " ORDER BY mastery ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def update_formula_mastery(f_id: int, mastery: float):
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        db.execute("""
            UPDATE formulas SET mastery=?, review_count=review_count+1, last_reviewed=?
            WHERE id=?
        """, (max(0, min(100, mastery)), today, f_id))


def update_formula_next_review(f_id: int, next_review: str):
    with _conn() as db:
        db.execute("UPDATE formulas SET next_review=? WHERE id=?", (next_review, f_id))



# 题目 CRUD


def add_exercise(knowledge_point_id=None, formula_ids=None, question="",
                 answer="", solution_steps=None, difficulty=2, bloom_level=3,
                 source_doc="", source_page=0, is_mistake=False) -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO exercises (knowledge_point_id, formula_ids, question, answer,
                solution_steps, difficulty, bloom_level, source_doc, source_page, is_mistake)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (knowledge_point_id,
              json.dumps(formula_ids or [], ensure_ascii=False),
              question, answer,
              json.dumps(solution_steps or [], ensure_ascii=False),
              difficulty, bloom_level, source_doc, source_page,
              1 if is_mistake else 0))
        return c.lastrowid


def get_exercise(ex_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM exercises WHERE id=?", (ex_id,)).fetchone()
        return dict(row) if row else {}


def search_exercises(subject="", kp_id=None, difficulty=None, limit=20) -> list:
    with _conn() as db:
        q = "SELECT e.* FROM exercises e"
        params = []
        if subject or kp_id:
            q += " LEFT JOIN knowledge_points k ON e.knowledge_point_id = k.id WHERE 1=1"
            if subject:
                q += " AND k.subject=?"
                params.append(subject)
            if kp_id:
                q += " AND e.knowledge_point_id=?"
                params.append(kp_id)
        else:
            q += " WHERE 1=1"
        if difficulty is not None:
            q += " AND e.difficulty=?"
            params.append(difficulty)
        q += " ORDER BY e.created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def get_recent_exercises(exclude_ids=None, limit=10) -> list:
    """获取近期做过的题目(用于出题时避免重复)。"""
    with _conn() as db:
        q = "SELECT id,question,answer FROM exercises ORDER BY created_at DESC LIMIT ?"
        return [dict(r) for r in db.execute(q, (limit,)).fetchall()]



# 错题 CRUD


def add_mistake(exercise_id=None, user_answer="", error_type="",
                ai_analysis="", knowledge_gap_id=None) -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO mistake_records (exercise_id, user_answer, error_type,
                ai_analysis, knowledge_gap_id)
            VALUES (?,?,?,?,?)
        """, (exercise_id, user_answer, error_type, ai_analysis, knowledge_gap_id))
        return c.lastrowid


def get_mistakes(subject="", reviewed=None, limit=30) -> list:
    with _conn() as db:
        q = """SELECT m.*, e.question, e.answer, kp.title as kp_title
               FROM mistake_records m
               LEFT JOIN exercises e ON m.exercise_id = e.id
               LEFT JOIN knowledge_points kp ON m.knowledge_gap_id = kp.id
               WHERE 1=1"""
        params = []
        if subject:
            q += " AND kp.subject=?"
            params.append(subject)
        if reviewed is not None:
            q += " AND m.reviewed=?"
            params.append(1 if reviewed else 0)
        q += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def mark_mistake_reviewed(m_id: int):
    with _conn() as db:
        db.execute("UPDATE mistake_records SET reviewed=1 WHERE id=?", (m_id,))



# 文档 CRUD


def add_document(filename, filepath="", filetype="", subject="", total_pages=0,
                 stage="", doc_type="") -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO documents (filename, filepath, filetype, subject, total_pages, stage, doc_type)
            VALUES (?,?,?,?,?,?,?)
        """, (filename, filepath, filetype, subject, total_pages, stage, doc_type))
        return c.lastrowid


def update_document_meta(doc_id: int, stage=None, subject=None, doc_type=None):
    """人工修正文档分类(阶段/科目/类型),并同步到其知识点的 stage/subject。"""
    sets, vals = [], []
    if stage is not None: sets.append("stage=?"); vals.append(stage)
    if subject is not None: sets.append("subject=?"); vals.append(subject)
    if doc_type is not None: sets.append("doc_type=?"); vals.append(doc_type)
    if not sets:
        return
    vals.append(doc_id)
    with _conn() as db:
        doc = db.execute("SELECT filename FROM documents WHERE id=?", (doc_id,)).fetchone()
        db.execute(f"UPDATE documents SET {','.join(sets)} WHERE id=?", vals)
        # 同步知识点(按来源文档名匹配)
        if doc:
            fn = doc[0]
            if stage is not None:
                db.execute("UPDATE knowledge_points SET stage=? WHERE source_doc=?", (stage, fn))
            if subject is not None:
                db.execute("UPDATE knowledge_points SET subject=? WHERE source_doc=?", (subject, fn))


def get_document(doc_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else {}


def list_documents(parsed=None) -> list:
    with _conn() as db:
        q = "SELECT * FROM documents"
        if parsed is not None:
            q += " WHERE parsed=?"
            return [dict(r) for r in db.execute(q, (1 if parsed else 0,)).fetchall()]
        return [dict(r) for r in db.execute(q + " ORDER BY uploaded_at DESC").fetchall()]


def mark_document_parsed(doc_id: int, kp_count=0, ex_count=0):
    with _conn() as db:
        db.execute("""UPDATE documents SET parsed=1, status='done', kp_count=?, ex_count=? WHERE id=?""",
                   (kp_count, ex_count, doc_id))


def update_document_status(doc_id: int, status="", note=None, progress=None):
    """更新文档处理状态:parsing/done/error;note=错误原因;progress=如 '3/8'。"""
    sets, vals = ["status=?"], [status]
    if note is not None: sets.append("note=?"); vals.append(note)
    if progress is not None: sets.append("progress=?"); vals.append(progress)
    vals.append(doc_id)
    with _conn() as db:
        db.execute(f"UPDATE documents SET {','.join(sets)} WHERE id=?", vals)


def delete_document_by_filename(filename: str) -> int:
    """删除同名文档行及其来源知识点(重复上传=刷新)。返回删除的文档数。"""
    with _conn() as db:
        rows = db.execute("SELECT id FROM documents WHERE filename=?", (filename,)).fetchall()
        if not rows:
            return 0
        db.execute("DELETE FROM knowledge_points WHERE source_doc=?", (filename,))
        db.execute("DELETE FROM documents WHERE filename=?", (filename,))
        return len(rows)


def delete_document(doc_id: int) -> bool:
    """按 id 删除文档及其来源知识点。"""
    with _conn() as db:
        row = db.execute("SELECT filename FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return False
        fn = row[0]
        db.execute("DELETE FROM knowledge_points WHERE source_doc=?", (fn,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        return True


def delete_failed_documents() -> int:
    """删除所有解析失败的文档。返回删除数。"""
    with _conn() as db:
        rows = db.execute("SELECT id, filename FROM documents WHERE status='error'").fetchall()
        for r in rows:
            db.execute("DELETE FROM knowledge_points WHERE source_doc=?", (r[1],))
        db.execute("DELETE FROM documents WHERE status='error'")
        return len(rows)


def delete_unfinished_documents() -> int:
    """删除"待解析/卡住"(未完成且非失败)的文档,保留已解析好的。返回删除数。"""
    cond = "parsed=0 AND status IN ('pending','parsing','')"
    with _conn() as db:
        rows = db.execute(f"SELECT id,filename FROM documents WHERE {cond}").fetchall()
        for r in rows:
            db.execute("DELETE FROM knowledge_points WHERE source_doc=?", (r[1],))
        db.execute(f"DELETE FROM documents WHERE {cond}")
        return len(rows)


def delete_all_documents() -> int:
    """清空整个资料/知识库(文档+知识点+题目+公式+词卡+错题),保留考试/计划/课表/画像。
    用于"只保留精选":先清空,再上传精选。返回清掉的文档数。"""
    with _conn() as db:
        n = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        for t in ("knowledge_points", "exercises", "formulas", "flashcards",
                  "mistake_records", "documents"):
            try:
                db.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        return n


def delete_empty_documents() -> int:
    """删除已解析但 0 知识点 0 题(没抽出内容)的文档。返回删除数。"""
    with _conn() as db:
        rows = db.execute("SELECT id, filename FROM documents "
                          "WHERE parsed=1 AND (kp_count + ex_count)=0").fetchall()
        for r in rows:
            db.execute("DELETE FROM knowledge_points WHERE source_doc=?", (r[1],))
        db.execute("DELETE FROM documents WHERE parsed=1 AND (kp_count + ex_count)=0")
        return len(rows)


def find_kp_by_title(subject: str, title: str) -> dict:
    """按 (科目,标题) 精确查知识点(去重用,避免 LIKE 误并)。"""
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM knowledge_points WHERE subject=? AND title=? LIMIT 1",
            (subject, title)).fetchone()
        return dict(row) if row else {}


# 参数化题库 CRUD

def add_question_template(subject, template, param_ranges, answer_expr, knowledge_point_id=None,
                          difficulty=3, bloom_level=2, explanation=""):
    """添加题目模板。param_ranges 是 dict, answer_expr 是 Python 表达式(字符串)。"""
    with _conn() as db:
        db.execute(
            "INSERT INTO question_templates(subject,knowledge_point_id,template,param_ranges,answer_expr,difficulty,bloom_level,explanation) VALUES(?,?,?,?,?,?,?,?)",
            (subject, knowledge_point_id, template, json.dumps(param_ranges, ensure_ascii=False),
             answer_expr, difficulty, bloom_level, explanation))
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_templates_for_kp(knowledge_point_id, limit=5):
    """获取某知识点的题目模板。"""
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM question_templates WHERE knowledge_point_id=? ORDER BY difficulty LIMIT ?",
            (knowledge_point_id, limit)).fetchall()
        return [_rowdict(r) for r in rows]


def get_templates_by_subject(subject, limit=20):
    """按科目获取题目模板。"""
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM question_templates WHERE subject=? ORDER BY difficulty LIMIT ?",
            (subject, limit)).fetchall()
        return [_rowdict(r) for r in rows]


def generate_from_template(template_id, avoid_params=None):
    """
    从模板生成一道题:选一组未用过的参数,计算答案,存入 question_instances。
    返回 dict: {id, question_text, answer, explanation, template_id, params} 或 None(参数耗尽)。
    """
    with _conn() as db:
        row = db.execute("SELECT * FROM question_templates WHERE id=?", (template_id,)).fetchone()
        if not row:
            return None
        t = _rowdict(row)
        ranges = json.loads(t["param_ranges"]) if isinstance(t["param_ranges"], str) else t["param_ranges"]
        # 找一组还没用过的参数
        avoid = set(tuple(sorted(v.items())) if isinstance(v, dict) else (str(v),) for v in (avoid_params or []))
        # 尝试参数组合
        import random
        keys = list(ranges.keys())
        tried = 0
        while tried < 50:
            params = {}
            for k in keys:
                vals = ranges[k]
                if isinstance(vals, list) and len(vals) > 0:
                    params[k] = random.choice(vals)
            pk = json.dumps(params, ensure_ascii=False, sort_keys=True)
            # 检查是否已用过
            existing = db.execute(
                "SELECT id FROM question_instances WHERE template_id=? AND params=?",
                (template_id, pk)).fetchone()
            if not existing:
                break
            tried += 1
        else:
            # 参数组合基本用完了，允许重复
            params = {k: random.choice(ranges[k]) if isinstance(ranges[k], list) else ranges[k] for k in keys}
        # 计算答案
        try:
            answer = _eval_answer(t["answer_expr"], params)
        except Exception:
            answer = "[答案计算失败]"
        question_text = t["template"]
        for k, v in params.items():
            question_text = question_text.replace("{" + k + "}", str(v))
        # 存入实例
        db.execute(
            "INSERT INTO question_instances(template_id,params,answer) VALUES(?,?,?)",
            (template_id, json.dumps(params, ensure_ascii=False, sort_keys=True), str(answer)))
        iid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {
            "id": iid, "question_text": question_text, "answer": str(answer),
            "explanation": t.get("explanation", ""), "template_id": template_id,
            "params": params, "difficulty": t["difficulty"], "bloom_level": t["bloom_level"],
        }


def _eval_answer(expr, params):
    """安全计算答案表达式。只允许 math 函数和基本运算。"""
    import math
    safe = {"__builtins__": {}, "math": math, "abs": abs, "round": round, "pow": pow,
            "sum": sum, "max": max, "min": min, "int": int, "float": float}
    safe.update(params)
    return eval(expr, safe)


def mark_instance_used(instance_id):
    """标记题目实例已使用。"""
    with _conn() as db:
        db.execute(
            "UPDATE question_instances SET used_count=used_count+1, last_used=datetime('now') WHERE id=?",
            (instance_id,))


def seed_math_templates():
    """预置高数/数学题目模板(幂等:已存在则跳过)。"""
    existing = 0
    with _conn() as db:
        existing = db.execute("SELECT COUNT(*) FROM question_templates WHERE subject='math'").fetchone()[0]
    if existing > 0:
        return existing

    templates = [
        # 导数
        ("math", "求函数 $f(x)={func}$ 在 $x={x0}$ 处的导数",
         {"func": ["x^2", "x^3", "sin(x)", "cos(x)", "e^x", "ln(x)", "2x+1", "x^2+3x"],
          "x0": [0, 1, 2, -1, 3]},
         "2*x0 if func=='x^2' else 3*x0**2 if func=='x^3' else math.cos(x0) if func=='sin(x)' else -math.sin(x0) if func=='cos(x)' else math.exp(x0) if func=='e^x' else 1/x0 if func=='ln(x)' else 2 if func=='2x+1' else 2*x0+3",
         2, 2, "使用基本求导公式计算。"),

        # 定积分
        ("math", "计算定积分 $\\int_{{{a}}}^{{{b}}} {func} \\,dx$",
         {"func": ["x", "x^2", "sin(x)", "cos(x)", "e^x"],
          "a": [0, 1, -1], "b": [1, 2, 3]},
         "b**2/2-a**2/2 if func=='x' else b**3/3-a**3/3 if func=='x^2' else -math.cos(b)+math.cos(a) if func=='sin(x)' else math.sin(b)-math.sin(a) if func=='cos(x)' else math.exp(b)-math.exp(a)",
         3, 2, "使用牛顿-莱布尼茨公式计算。"),

        # 极限
        ("math", "求极限 $\\lim_{{x \\to {x0}}} \\frac{{{num}}}{{{den}}}$",
         {"x0": [0, 1, 2, -1],
          "num": ["x^2-1", "x^2-4", "sin(x)", "e^x-1"],
          "den": ["x-1", "x-2", "x", "x"]},
         "2*x0 if num=='x^2-1' and den=='x-1' else 4 if num=='x^2-4' and den=='x-2' and x0==2 else 1 if num=='sin(x)' and den=='x' and x0==0 else 1 if num=='e^x-1' and den=='x' and x0==0 else 0",
         3, 3, "使用洛必达法则或等价无穷小代换。"),

        # 概率
        ("math", "从{total}个物品中随机抽取{draw}个，求抽到{target}个目标物品的概率",
         {"total": [5, 10, 20], "draw": [2, 3], "target": [1, 2]},
         "min(1.0, round(target*draw/total, 4))",
         3, 3, "使用组合数公式计算超几何分布概率。"),
    ]

    count = 0
    for t in templates:
        try:
            add_question_template(*t)
            count += 1
        except Exception:
            pass
    return count


def _rowdict(row):
    """sqlite3.Row → dict。"""
    return dict(row) if row else {}


# 阶段学习计划 CRUD

def create_phase(name, goal, strategy, daily_schedule, acceptance_criteria, start_date, end_date, current_day=1):
    with _conn() as db:
        db.execute(
            "INSERT INTO study_phases(name,goal,strategy,daily_schedule,acceptance_criteria,start_date,end_date,current_day) VALUES(?,?,?,?,?,?,?,?)",
            (name, goal, strategy, daily_schedule, acceptance_criteria, start_date, end_date, current_day))
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_active_phase():
    with _conn() as db:
        row = db.execute("SELECT * FROM study_phases WHERE status='active' ORDER BY start_date DESC LIMIT 1").fetchone()
        return _rowdict(row) if row else None

def list_phases():
    with _conn() as db:
        return [_rowdict(r) for r in db.execute("SELECT * FROM study_phases ORDER BY start_date").fetchall()]

def get_phase(phase_id):
    with _conn() as db:
        return _rowdict(db.execute("SELECT * FROM study_phases WHERE id=?", (phase_id,)).fetchone())

def complete_phase(phase_id):
    with _conn() as db:
        db.execute("UPDATE study_phases SET status='completed' WHERE id=?", (phase_id,))

def add_daily_plan(phase_id, date, day_number=0, phase_position="", math_content="", english_content="",
                   cs_content="", chinese_content="", study_time="", expected_output="", review_focus="",
                   math_detail="", english_detail="", cs_detail="", chinese_detail="",
                   must_know="", exercises=""):
    with _conn() as db:
        db.execute(
            "INSERT OR REPLACE INTO daily_plans(phase_id,date,day_number,phase_position,math_content,english_content,cs_content,chinese_content,study_time,expected_output,review_focus,math_detail,english_detail,cs_detail,chinese_detail,must_know,exercises) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (phase_id,str(date)[:10],day_number,phase_position,math_content,english_content,cs_content,chinese_content,study_time,expected_output,review_focus,math_detail,english_detail,cs_detail,chinese_detail,must_know,exercises))
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_today_plan(date_str=None):
    """按日历日期获取计划（兼容旧接口）。"""
    if not date_str:
        from datetime import date
        date_str = date.today().isoformat()
    with _conn() as db:
        row = db.execute("SELECT * FROM daily_plans WHERE date=? ORDER BY id LIMIT 1", (date_str,)).fetchone()
        return _rowdict(row) if row else None

def get_current_plan():
    """获取当前应学的计划（按学习节奏，不是日历日期）。"""
    phase = get_active_phase()
    if not phase:
        return None
    day = phase.get("current_day", 1)
    with _conn() as db:
        # 先按 day_number 查
        row = db.execute(
            "SELECT * FROM daily_plans WHERE phase_id=? AND day_number=?",
            (phase["id"], day)).fetchone()
        if row:
            return _rowdict(row)
        # 没编号则按 date 排序取第 N 条
        rows = db.execute(
            "SELECT * FROM daily_plans WHERE phase_id=? ORDER BY date LIMIT 1 OFFSET ?",
            (phase["id"], day - 1)).fetchall()
        return _rowdict(rows[0]) if rows else None

def advance_day():
    """完成今天的学习 → 推进到下一天。返回新的 current_day。"""
    phase = get_active_phase()
    if not phase:
        return 0
    new_day = phase.get("current_day", 1) + 1
    total = get_phase_plans_count(phase["id"])
    if new_day > total:
        new_day = total  # 不超出范围
    with _conn() as db:
        db.execute("UPDATE study_phases SET current_day=? WHERE id=?", (new_day, phase["id"]))
    return new_day

def set_current_day(day_num):
    """手动设置当前学习日。"""
    phase = get_active_phase()
    if not phase:
        return
    total = get_phase_plans_count(phase["id"])
    day_num = max(1, min(day_num, total))
    with _conn() as db:
        db.execute("UPDATE study_phases SET current_day=? WHERE id=?", (day_num, phase["id"]))

def get_phase_plans_count(phase_id):
    with _conn() as db:
        return db.execute("SELECT COUNT(*) FROM daily_plans WHERE phase_id=?", (phase_id,)).fetchone()[0]

def get_phase_plans(phase_id):
    with _conn() as db:
        return [_rowdict(r) for r in db.execute(
            "SELECT * FROM daily_plans WHERE phase_id=? ORDER BY date", (phase_id,)).fetchall()]

def update_plan_status(plan_id, status):
    with _conn() as db:
        db.execute("UPDATE daily_plans SET status=? WHERE id=?", (status, plan_id))

def checkin(plan_id, date_str, completed_subjects, study_duration, reflection="",
            difficulties="", achievements="", mood=3):
    """每日打卡。completed_subjects 是 dict，如 {"math":true,"english":false}。"""
    with _conn() as db:
        # upsert
        existing = db.execute("SELECT id FROM daily_checkins WHERE plan_id=? AND date=?",
                              (plan_id, date_str)).fetchone()
        subj_json = json.dumps(completed_subjects, ensure_ascii=False)
        if existing:
            db.execute(
                "UPDATE daily_checkins SET completed_subjects=?,study_duration=?,reflection=?,difficulties=?,achievements=?,mood=? WHERE id=?",
                (subj_json, study_duration, reflection, difficulties, achievements, mood, existing[0]))
        else:
            db.execute(
                "INSERT INTO daily_checkins(plan_id,date,completed_subjects,study_duration,reflection,difficulties,achievements,mood) VALUES(?,?,?,?,?,?,?,?)",
                (plan_id, date_str, subj_json, study_duration, reflection, difficulties, achievements, mood))

def get_checkins(phase_id):
    with _conn() as db:
        return [_rowdict(r) for r in db.execute(
            "SELECT dc.* FROM daily_checkins dc JOIN daily_plans dp ON dc.plan_id=dp.id WHERE dp.phase_id=? ORDER BY dc.date",
            (phase_id,)).fetchall()]

def get_phase_progress(phase_id):
    """阶段进度统计。"""
    with _conn() as db:
        total = db.execute("SELECT COUNT(*) FROM daily_plans WHERE phase_id=?", (phase_id,)).fetchone()[0]
        done = db.execute("SELECT COUNT(*) FROM daily_plans WHERE phase_id=? AND status IN ('done','partial')",
                          (phase_id,)).fetchone()[0]
        checkins = db.execute("SELECT COUNT(*) FROM daily_checkins dc JOIN daily_plans dp ON dc.plan_id=dp.id WHERE dp.phase_id=?",
                              (phase_id,)).fetchone()[0]
        return {"total_days": total, "completed_days": done, "checkin_count": checkins,
                "progress_pct": round(done/max(total,1)*100)}

def add_phase_summary(phase_id, subject, summary_type, content, key_data=""):
    with _conn() as db:
        db.execute(
            "INSERT INTO phase_summaries(phase_id,subject,summary_type,content,key_data) VALUES(?,?,?,?,?)",
            (phase_id, subject, summary_type, content, key_data))

def get_phase_summaries(phase_id):
    with _conn() as db:
        return [_rowdict(r) for r in db.execute(
            "SELECT * FROM phase_summaries WHERE phase_id=? ORDER BY subject, summary_type", (phase_id,)).fetchall()]

def get_pace_analysis():
    """学习节奏分析: 按固定日历日期计算差距 + 给出建议。"""
    from datetime import date, datetime
    phase = get_active_phase()
    if not phase:
        return None

    today = date.today()
    try:
        start = datetime.strptime(str(phase["start_date"])[:10], "%Y-%m-%d").date()
        end = datetime.strptime(str(phase["end_date"])[:10], "%Y-%m-%d").date()
    except Exception:
        return None

    total = get_phase_plans_count(phase["id"])
    current = phase.get("current_day", 1)
    remaining_plan = total - current + 1

    # 按日历算：今天应该学到第几天
    expected_day = (today - start).days + 1
    days_behind = expected_day - current  # 正数 = 落后于日历

    # 截止日期剩余日历天数
    calendar_remaining = (end - today).days + 1

    # 所需节奏：剩余学习日 / 剩余日历日
    needed_pace = round(remaining_plan / max(calendar_remaining, 1), 1)

    # 紧急程度
    if days_behind <= 0:
        urgency = "on_track"    # 正常或提前
        urgency_text = "节奏正常 ✅"
    elif needed_pace <= 1.2:
        urgency = "mild"
        urgency_text = f"略落后 {days_behind} 天，每天多学一点即可赶上 ⚠️"
    elif needed_pace <= 2.0:
        urgency = "warning"
        urgency_text = f"落后 {days_behind} 天！需每天完成 {needed_pace} 天计划 🔴"
    else:
        urgency = "critical"
        urgency_text = f"严重落后 {days_behind} 天！需要每天完成 {needed_pace} 天，建议精简非核心内容 🆘"

    # 找出可以"合并"的轻量日（学习时间较短的）
    plans = get_phase_plans(phase["id"])
    light_days = []
    for p in plans:
        study_time = p.get("study_time", "") or ""
        # 解析 "6.5-7小时" → 取低值
        import re
        m = re.search(r'(\d+(?:\.\d+)?)', study_time)
        hours = float(m.group(1)) if m else 7
        if hours <= 5:
            light_days.append({
                "day": p.get("day_number", 0),
                "date": str(p.get("date", ""))[:10],
                "hours": hours,
                "phase": p.get("phase_position", ""),
            })

    # 如果落后，建议合并哪些天
    catchup_suggestion = ""
    if days_behind > 0 and light_days:
        catchable = [d for d in light_days if d["day"] > current][:3]
        if catchable:
            catchup_suggestion = "可合并的轻量日: " + ", ".join(
                f'第{d["day"]}天({d["date"][5:]}, {d["hours"]}h)' for d in catchable)

    return {
        "total_days": total,
        "current_day": current,
        "remaining_plan_days": remaining_plan,
        "calendar_remaining_days": calendar_remaining,
        "expected_today": expected_day,
        "days_behind": days_behind,
        "needed_pace": needed_pace,
        "urgency": urgency,
        "urgency_text": urgency_text,
        "start_date": str(start),
        "end_date": str(end),
        "today": str(today),
        "catchup_suggestion": catchup_suggestion,
    }


def get_cross_phase_memories(subject=""):
    """跨阶段记忆: 提取所有已完成阶段的总结供新阶段参考。"""
    with _conn() as db:
        q = ("SELECT ps.*, sp.name as phase_name FROM phase_summaries ps "
             "JOIN study_phases sp ON ps.phase_id=sp.id WHERE sp.status='completed'")
        params = []
        if subject:
            q += " AND ps.subject=?"
            params.append(subject)
        q += " ORDER BY ps.created_at DESC"
        return [_rowdict(r) for r in db.execute(q, params).fetchall()]


def get_coverage(subject="", mastered_at=60) -> list:
    """大纲覆盖度:按科目统计 总知识点 / 已掌握(mastery≥mastered_at)。"""
    q = ("SELECT subject, COUNT(*) total, "
         "SUM(CASE WHEN mastery>=? THEN 1 ELSE 0 END) mastered, "
         "AVG(mastery) avg_m FROM knowledge_points WHERE subject!=''")
    params = [mastered_at]
    if subject:
        q += " AND subject=?"; params.append(subject)
    q += " GROUP BY subject ORDER BY total DESC"
    with _conn() as db:
        return [{"subject": r["subject"], "total": r["total"],
                 "mastered": r["mastered"] or 0, "avg": round(r["avg_m"] or 0)}
                for r in db.execute(q, params).fetchall()]


def merge_subject(frm: str, to: str) -> int:
    """把科目 frm 合并到 to(知识点+公式+文档),返回受影响知识点数。"""
    frm, to = frm.strip(), to.strip()
    if not frm or not to or frm == to:
        return 0
    with _conn() as db:
        n = db.execute("SELECT COUNT(*) c FROM knowledge_points WHERE subject=?", (frm,)).fetchone()["c"]
        db.execute("UPDATE knowledge_points SET subject=? WHERE subject=?", (to, frm))
        db.execute("UPDATE documents SET subject=? WHERE subject=?", (to, frm))
        try:
            db.execute("UPDATE formulas SET subject=? WHERE subject=?", (to, frm))
        except Exception:
            pass
        return n


def taxonomy_values() -> dict:
    """库里已有的阶段/科目/类型(去重),给前端下拉和分类提示用。"""
    out = {"stages": [], "subjects": [], "doc_types": []}
    with _conn() as db:
        try:
            out["stages"] = [r[0] for r in db.execute(
                "SELECT DISTINCT stage FROM documents WHERE stage!='' ORDER BY stage").fetchall()]
            out["subjects"] = [r[0] for r in db.execute(
                "SELECT DISTINCT subject FROM documents WHERE subject!='' ORDER BY subject").fetchall()]
            out["doc_types"] = [r[0] for r in db.execute(
                "SELECT DISTINCT doc_type FROM documents WHERE doc_type!='' ORDER BY doc_type").fetchall()]
        except Exception:
            pass
    return out


def get_catalog(stage="", subject="") -> dict:
    """
    token 友好的知识目录:阶段→科目→章节→知识点(只含 id/title/mastery,不含正文)。
    供大脑先看目录、再按需取详情(get_kp_details),避免一次性灌全文。
    """
    q = ("SELECT id, stage, subject, chapter, title, mastery FROM knowledge_points "
         "WHERE 1=1")
    params = []
    if stage:
        q += " AND stage=?"; params.append(stage)
    if subject:
        q += " AND subject=?"; params.append(subject)
    q += " ORDER BY stage, subject, chapter, id"
    tree = {}
    with _conn() as db:
        for r in db.execute(q, params).fetchall():
            st = r["stage"] or "未分阶段"
            sj = r["subject"] or "未分科目"
            ch = r["chapter"] or "未分章节"
            tree.setdefault(st, {}).setdefault(sj, {}).setdefault(ch, []).append(
                {"id": r["id"], "title": r["title"], "mastery": round(r["mastery"] or 0)})
    return tree


def get_kp_details(ids: list) -> list:
    """按 id 批量取知识点完整内容(供大脑选中后调取)。"""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    with _conn() as db:
        rows = db.execute(
            f"SELECT id, stage, subject, chapter, section, title, content, difficulty, mastery "
            f"FROM knowledge_points WHERE id IN ({marks})", list(ids)).fetchall()
        return [dict(r) for r in rows]



# 进度 CRUD


def log_progress(subject="", study_minutes=0, formulas_reviewed=0,
                 exercises_done=0, exercises_correct=0, weak_topics=None, notes=""):
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        # 今天已有记录则更新（合并）
        existing = db.execute(
            "SELECT id FROM progress_log WHERE date=? AND subject=?", (today, subject)).fetchone()
        if existing:
            db.execute("""
                UPDATE progress_log SET
                    study_minutes=study_minutes+?, formulas_reviewed=formulas_reviewed+?,
                    exercises_done=exercises_done+?, exercises_correct=exercises_correct+?,
                    weak_topics=?, notes=?
                WHERE id=?
            """, (study_minutes, formulas_reviewed, exercises_done, exercises_correct,
                  json.dumps(weak_topics or [], ensure_ascii=False), notes, existing["id"]))
        else:
            db.execute("""
                INSERT INTO progress_log (date, subject, study_minutes, formulas_reviewed,
                    exercises_done, exercises_correct, weak_topics, notes)
                VALUES (?,?,?,?,?,?,?,?)
            """, (today, subject, study_minutes, formulas_reviewed,
                  exercises_done, exercises_correct,
                  json.dumps(weak_topics or [], ensure_ascii=False), notes))


def get_today_progress(subject="") -> list:
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        q = "SELECT * FROM progress_log WHERE date=?"
        params = [today]
        if subject:
            q += " AND subject=?"
            params.append(subject)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def get_progress_summary(days=30) -> list:
    """获取最近 N 天的学习统计摘要。"""
    with _conn() as db:
        return [dict(r) for r in db.execute("""
            SELECT date,
                   SUM(study_minutes) as total_minutes,
                   SUM(exercises_done) as total_ex,
                   CASE WHEN SUM(exercises_done) > 0
                     THEN ROUND(100.0*SUM(exercises_correct)/SUM(exercises_done),1)
                     ELSE 0 END as accuracy,
                   SUM(formulas_reviewed) as total_fm
            FROM progress_log
            WHERE date >= date('now', ?)
            GROUP BY date ORDER BY date ASC
        """, (f"-{days}d",)).fetchall()]


def get_weak_topics(subject="", top_n=5) -> list:
    """获取最薄弱的知识点(按 mastery 升序)。"""
    with _conn() as db:
        q = """SELECT id,title,subject,mastery,review_count,last_reviewed
               FROM knowledge_points WHERE mastery < 80"""
        params = []
        if subject:
            q += " AND subject=?"
            params.append(subject)
        q += " ORDER BY mastery ASC LIMIT ?"
        params.append(top_n)
        return [dict(r) for r in db.execute(q, params).fetchall()]



# 批量操作


def batch_add_knowledge_points(items: list[dict]) -> int:
    """批量添加知识点,items 每项为 add_knowledge_point 参数 dict。返回添加数量。"""
    count = 0
    for item in items:
        try:
            add_knowledge_point(**item)
            count += 1
        except Exception:
            pass
    return count


def batch_add_formulas(items: list[dict]) -> int:
    count = 0
    for item in items:
        try:
            add_formula(**item)
            count += 1
        except Exception:
            pass
    return count


def batch_add_exercises(items: list[dict]) -> int:
    count = 0
    for item in items:
        try:
            add_exercise(**item)
            count += 1
        except Exception:
            pass
    return count


def get_stats() -> dict:
    """整体统计摘要。"""
    with _conn() as db:
        kp = db.execute("SELECT COUNT(*) as c FROM knowledge_points").fetchone()["c"]
        fm = db.execute("SELECT COUNT(*) as c FROM formulas").fetchone()["c"]
        ex = db.execute("SELECT COUNT(*) as c FROM exercises").fetchone()["c"]
        ms = db.execute("SELECT COUNT(*) as c FROM mistake_records WHERE reviewed=0").fetchone()["c"]
        dc = db.execute("SELECT COUNT(*) as c FROM documents WHERE parsed=0").fetchone()["c"]
        pm = db.execute("""
            SELECT COALESCE(SUM(study_minutes),0) as m,
                   COALESCE(SUM(exercises_done),0) as e
            FROM progress_log WHERE date=date('now')
        """).fetchone()
        return {
            "total_knowledge_points": kp,
            "total_formulas": fm,
            "total_exercises": ex,
            "unreviewed_mistakes": ms,
            "unprocessed_documents": dc,
            "today_study_minutes": pm["m"],
            "today_exercises": pm["e"],
        }



# 考试 CRUD


def add_exam(name, exam_date, subjects=None, scope="", target_score="", notes="") -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO exams (name, exam_date, subjects, scope, target_score, notes)
            VALUES (?,?,?,?,?,?)
        """, (name, exam_date, json.dumps(subjects or [], ensure_ascii=False),
              scope, target_score, notes))
        return c.lastrowid


def get_exam(exam_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
        return dict(row) if row else {}


def list_exams(status="") -> list:
    with _conn() as db:
        q = "SELECT * FROM exams"
        params = []
        if status:
            q += " WHERE status=?"
            params.append(status)
        q += " ORDER BY exam_date ASC"
        return [dict(r) for r in db.execute(q, params).fetchall()]


def update_exam_status(exam_id: int, status: str):
    with _conn() as db:
        db.execute("UPDATE exams SET status=? WHERE id=?", (status, exam_id))


def get_upcoming_exams(days_ahead=90) -> list:
    """获取未来 N 天内的考试。"""
    import datetime
    today = datetime.date.today().isoformat()
    end = (datetime.date.today() + datetime.timedelta(days=days_ahead)).isoformat()
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM exams WHERE exam_date BETWEEN ? AND ? AND status='upcoming' "
            "ORDER BY exam_date", (today, end)).fetchall()]



# 学习计划 CRUD


def add_study_plan(name, plan_type, start_date, end_date,
                   exam_id=None, tasks=None, auto_generated=False) -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO study_plans (name, plan_type, start_date, end_date,
                exam_id, tasks, auto_generated)
            VALUES (?,?,?,?,?,?,?)
        """, (name, plan_type, start_date, end_date, exam_id,
              json.dumps(tasks or [], ensure_ascii=False),
              1 if auto_generated else 0))
        return c.lastrowid


def get_study_plan(plan_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM study_plans WHERE id=?", (plan_id,)).fetchone()
        return dict(row) if row else {}


def list_study_plans(plan_type="", limit=20) -> list:
    with _conn() as db:
        q = "SELECT * FROM study_plans"
        params = []
        if plan_type:
            q += " WHERE plan_type=?"
            params.append(plan_type)
        q += " ORDER BY start_date DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def get_active_plans(date_str="") -> list:
    """获取指定日期有效的计划。"""
    if not date_str:
        date_str = time.strftime("%Y-%m-%d")
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM study_plans WHERE start_date <= ? AND end_date >= ? "
            "ORDER BY start_date", (date_str, date_str)).fetchall()]


def update_plan_progress(plan_id: int, progress: float):
    with _conn() as db:
        db.execute("UPDATE study_plans SET progress=? WHERE id=?",
                   (max(0, min(100, progress)), plan_id))



# 内容缺口 CRUD


def add_content_gap(exam_id=None, subject="", topic="", covered=False,
                    priority=3, source_hint="", notes="") -> int:
    with _conn() as db:
        c = db.execute("""
            INSERT INTO content_gaps (exam_id, subject, topic, covered, priority, source_hint, notes)
            VALUES (?,?,?,?,?,?,?)
        """, (exam_id, subject, topic, 1 if covered else 0, priority, source_hint, notes))
        return c.lastrowid


def list_content_gaps(exam_id=None, covered=None) -> list:
    with _conn() as db:
        q = "SELECT * FROM content_gaps WHERE 1=1"
        params = []
        if exam_id:
            q += " AND exam_id=?"
            params.append(exam_id)
        if covered is not None:
            q += " AND covered=?"
            params.append(1 if covered else 0)
        q += " ORDER BY priority DESC"
        return [dict(r) for r in db.execute(q, params).fetchall()]


def mark_gap_covered(gap_id: int):
    with _conn() as db:
        db.execute("UPDATE content_gaps SET covered=1 WHERE id=?", (gap_id,))


def get_exam_coverage(exam_id: int) -> dict:
    """考试覆盖度: 已学 / 总数。"""
    gaps = list_content_gaps(exam_id)
    total = len(gaps)
    covered = sum(1 for g in gaps if g.get("covered"))
    return {
        "total_topics": total,
        "covered": covered,
        "uncovered": total - covered,
        "coverage_pct": round(100 * covered / max(1, total), 1),
        "gaps": [g for g in gaps if not g.get("covered")],
    }



# 课程 CRUD


def add_course(name, subject="", description="") -> int:
    with _conn() as db:
        c = db.execute("INSERT INTO courses (name,subject,description) VALUES (?,?,?)",
                       (name, subject, description))
        return c.lastrowid

def get_course(course_id: int) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        return dict(row) if row else {}

def list_courses(status="") -> list:
    with _conn() as db:
        q = "SELECT * FROM courses"
        params = []
        if status:
            q += " WHERE status=?"
            params.append(status)
        return [dict(r) for r in db.execute(q + " ORDER BY created_at DESC", params).fetchall()]

def update_course_progress(course_id: int):
    with _conn() as db:
        chs = db.execute("SELECT SUM(kp_count) as tkp, SUM(completed_count) as tdone "
                         "FROM chapters WHERE course_id=?", (course_id,)).fetchone()
        db.execute("UPDATE courses SET total_kps=?, completed_kps=?, total_chapters="
                   "(SELECT COUNT(*) FROM chapters WHERE course_id=?) WHERE id=?",
                   (chs["tkp"] or 0, chs["tdone"] or 0, course_id, course_id))

# 章节
def add_chapter(course_id: int, title: str, sort_order=0, description="",
                estimated_hours=1.0) -> int:
    with _conn() as db:
        c = db.execute("INSERT INTO chapters (course_id,title,sort_order,description,"
                       "estimated_hours) VALUES (?,?,?,?,?)",
                       (course_id, title, sort_order, description, estimated_hours))
        return c.lastrowid

def list_chapters(course_id: int) -> list:
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM chapters WHERE course_id=? ORDER BY sort_order",
            (course_id,)).fetchall()]

def update_chapter_progress(chapter_id: int):
    with _conn() as db:
        kps = db.execute(
            "SELECT COUNT(*) as c FROM knowledge_points WHERE chapter="
            "(SELECT title FROM chapters WHERE id=?)", (chapter_id,)).fetchone()["c"]
        done = db.execute(
            "SELECT COUNT(*) as c FROM knowledge_points WHERE chapter="
            "(SELECT title FROM chapters WHERE id=?) AND mastery>=70",
            (chapter_id,)).fetchone()["c"]
        db.execute("UPDATE chapters SET kp_count=?, completed_count=?, status="
                   "CASE WHEN ?>=? THEN 'done' ELSE 'in_progress' END WHERE id=?",
                   (kps, done, done, kps if kps > 0 else 1, chapter_id))

# 闪卡
def add_flashcard(front, back, hint="", subject="", knowledge_point_id=None,
                  source="", deck="default") -> int:
    with _conn() as db:
        c = db.execute("INSERT INTO flashcards (front,back,hint,subject,"
                       "knowledge_point_id,source,deck) VALUES (?,?,?,?,?,?,?)",
                       (front, back, hint, subject, knowledge_point_id, source, deck))
        return c.lastrowid

def get_new_flashcards(deck="", limit=15) -> list:
    """没背过的新词卡(repetitions=0)。"""
    with _conn() as db:
        q = "SELECT * FROM flashcards WHERE repetitions=0"
        params = []
        if deck:
            q += " AND deck=?"; params.append(deck)
        q += " ORDER BY id LIMIT ?"; params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]


def count_cards(due_only=False, new_only=False) -> int:
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        if new_only:
            return db.execute("SELECT COUNT(*) c FROM flashcards WHERE repetitions=0").fetchone()["c"]
        if due_only:
            return db.execute("SELECT COUNT(*) c FROM flashcards WHERE repetitions>0 AND next_review<=?",
                              (today,)).fetchone()["c"]
        return db.execute("SELECT COUNT(*) c FROM flashcards").fetchone()["c"]


def list_pending_docs(limit=1) -> list:
    """待解析(仅上传未解析)的文档,按上传顺序。"""
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM documents WHERE status='pending' ORDER BY id LIMIT ?",
            (limit,)).fetchall()]


def count_pending() -> int:
    with _conn() as db:
        return db.execute("SELECT COUNT(*) c FROM documents WHERE status='pending'").fetchone()["c"]


def document_has_content(filename: str) -> bool:
    """同名文档是否已成功解析且有内容(知识点或题目>0)。用于上传防重。"""
    with _conn() as db:
        r = db.execute("SELECT parsed,kp_count,ex_count FROM documents WHERE filename=? "
                       "ORDER BY id DESC LIMIT 1", (filename,)).fetchone()
        return bool(r and r[0] and (r[1] + r[2]) > 0)


def get_due_flashcards(deck="", limit=20) -> list:
    today = time.strftime("%Y-%m-%d")
    with _conn() as db:
        q = "SELECT * FROM flashcards WHERE next_review <= ?"
        params = [today]
        if deck:
            q += " AND deck=?"
            params.append(deck)
        q += " ORDER BY mastery ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(q, params).fetchall()]

def update_flashcard_review(card_id: int, quality: int):
    """quality: 0-5 SM-2"""
    import datetime
    with _conn() as db:
        card = db.execute("SELECT * FROM flashcards WHERE id=?", (card_id,)).fetchone()
        if not card:
            return
        ef = card["ease"]
        reps = card["repetitions"]
        interval = card["interval_days"]
        if quality >= 3:
            if reps == 0: new_interval = 1
            elif reps == 1: new_interval = 6
            else: new_interval = int(round(interval * ef))
            ef = max(1.3, ef + (0.1 - (5 - quality) * 0.08))
            reps += 1
        else:
            new_interval = 1; reps = 0; ef = max(1.3, ef - 0.2)
        mastery = max(0, min(100, card["mastery"] + (20 if quality >= 4 else 10 if quality >= 3 else -15)))
        next_date = (datetime.date.today() +
                     datetime.timedelta(days=min(new_interval, 365))).isoformat()
        db.execute("UPDATE flashcards SET ease=?, interval_days=?, repetitions=?,"
                   "next_review=?, mastery=? WHERE id=?",
                   (ef, new_interval, reps, next_date, mastery, card_id))

def count_flashcards(deck="") -> int:
    with _conn() as db:
        q = "SELECT COUNT(*) as c FROM flashcards"
        if deck:
            q += " WHERE deck=?"
            return db.execute(q, (deck,)).fetchone()["c"]
        return db.execute(q).fetchone()["c"]

def batch_add_flashcards(items: list[dict]) -> int:
    count = 0
    for item in items:
        try:
            add_flashcard(**item)
            count += 1
        except Exception:
            pass
    return count



# 专注会话 CRUD


def add_focus_session(subject="", task="", duration_seconds=0, completed=1) -> int:
    with _conn() as db:
        c = db.execute("INSERT INTO focus_sessions (subject,task,duration_seconds,completed) VALUES (?,?,?,?)",
                       (subject, task, duration_seconds, completed))
        return c.lastrowid

def get_focus_history(days=30) -> list:
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT *,date(created_at) as d FROM focus_sessions "
            "WHERE created_at >= date('now',?) ORDER BY created_at DESC LIMIT 100",
            (f"-{days}d",)).fetchall()]

def get_focus_stats() -> dict:
    with _conn() as db:
        today = time.strftime("%Y-%m-%d")
        total = db.execute("SELECT COALESCE(SUM(duration_seconds),0) as s FROM focus_sessions").fetchone()["s"]
        today_s = db.execute("SELECT COALESCE(SUM(duration_seconds),0) as s FROM focus_sessions WHERE date(created_at)=?",
                             (today,)).fetchone()["s"]
        count = db.execute("SELECT COUNT(*) as c FROM focus_sessions").fetchone()["c"]
        return {"total_seconds": total, "today_seconds": today_s, "total_sessions": count,
                "total_hours": round(total / 3600.0, 1), "today_minutes": round(today_s / 60.0, 1)}

# 快速笔记
def add_quick_note(content: str, subject="", category="general") -> int:
    with _conn() as db:
        c = db.execute("INSERT INTO quick_notes (content,subject,category) VALUES (?,?,?)",
                       (content, subject, category))
        return c.lastrowid

def get_quick_notes(limit=50) -> list:
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM quick_notes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

def search_quick_notes(keyword="", limit=20) -> list:
    with _conn() as db:
        kw = f"%{keyword}%"
        return [dict(r) for r in db.execute(
            "SELECT * FROM quick_notes WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (kw, limit)).fetchall()]


# 首次导入时自动初始化
init()

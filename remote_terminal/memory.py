# -*- coding: utf-8 -*-
"""
Nous 长期记忆系统 — 持久化用户偏好/事实/目标/情绪/进度。

存储: SQLite 表 memories,本地文件 brain_memory.db。
调用方: brain_prompt 在每次对话时注入相关记忆,brain 在对话后异步提取新记忆。

设计原则:
  - 记忆自动衰减(低频访问的记忆降低 importance)
  - 检索用关键词匹配(轻量,不依赖 embedding API)
  - 分类明确,便于按场景注入不同类别的记忆
"""

import json as _json
import logging as _logging
import os as _os
import sqlite3 as _sqlite3
from contextlib import contextmanager as _contextmanager

_log = _logging.getLogger("memory")

_MEMORY_DB = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "brain_memory.db")

# 记忆分类
CATEGORIES = ("preference", "fact", "goal", "emotion", "progress")

# 记忆提取提示(给便宜模型用)
EXTRACT_PROMPT = (
    "你是用户记忆提取器。从用户这句话中提取值得长期记住的信息,仅输出 JSON 数组(不要 markdown):\n"
    '[{"category":"分类","content":"内容","importance":5}]\n\n'
    "分类只从: preference(偏好/习惯), fact(事实/个人数据), goal(目标/计划), "
    "emotion(情绪/心态), progress(学习进度)中选。\n"
    "importance 1-10: 10=非常重要必须记住,5=一般,1=琐碎可不记。\n"
    "没有值得记的内容就输出空数组 []。只输出数组,不要其他文字。\n\n"
    "用户消息:\n{text}"
)


@_contextmanager
def _conn():
    db = _sqlite3.connect(_MEMORY_DB)
    db.row_factory = _sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    """创建记忆表(幂等)。"""
    with _conn() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT '',
            category TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            access_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_accessed_at TEXT DEFAULT (datetime('now'))
        )
        """)


def add_memory(content: str, category: str = "fact", importance: int = 5,
                user_id: str = "") -> int:
    """添加一条记忆。返回新记忆 ID。"""
    init()
    if category not in CATEGORIES:
        category = "fact"
    importance = max(1, min(10, importance))
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO memories (user_id, category, content, importance) VALUES (?,?,?,?)",
            (user_id, category, content, importance))
        return cur.lastrowid


def search_memories(keyword: str = "", category: str = "", limit: int = 10,
                     user_id: str = "") -> list:
    """搜索记忆(关键词匹配)。返回按 importance*access_count 降序排列的结果。"""
    init()
    sql = "SELECT * FROM memories WHERE 1=1"
    params = []
    if keyword:
        sql += " AND content LIKE ?"
        params.append(f"%{keyword}%")
    if category and category in CATEGORIES:
        sql += " AND category = ?"
        params.append(category)
    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)
    sql += " ORDER BY importance * (1 + access_count) DESC LIMIT ?"
    params.append(limit)

    with _conn() as db:
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    # 更新访问计数
    if rows:
        with _conn() as db:
            ids = [r["id"] for r in rows]
            db.execute(
                f"UPDATE memories SET access_count = access_count + 1, "
                f"last_accessed_at = datetime('now') WHERE id IN "
                f"({','.join('?' for _ in ids)})", ids)
            for r in rows:
                r["access_count"] += 1
    return rows


def get_recent_memories(limit: int = 20, user_id: str = "") -> list:
    """获取最近更新的记忆。"""
    init()
    sql = "SELECT * FROM memories WHERE 1=1"
    params = []
    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)
    sql += " ORDER BY last_accessed_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]


def forget_memory(memory_id: int) -> bool:
    """删除一条记忆。"""
    init()
    with _conn() as db:
        cur = db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cur.rowcount > 0


def decay_memories(days_threshold: int = 30) -> int:
    """衰减长期未访问的记忆(降低 importance)。返回衰减条数。"""
    init()
    with _conn() as db:
        cur = db.execute(
            "UPDATE memories SET importance = MAX(1, importance - 1) "
            "WHERE last_accessed_at < datetime('now', ?) AND importance > 1",
            (f"-{days_threshold} days",))
        return cur.rowcount


def get_memory_stats() -> dict:
    """获取记忆统计。"""
    init()
    with _conn() as db:
        total = db.execute("SELECT COUNT(*) as n FROM memories").fetchone()["n"]
        by_cat = {}
        for row in db.execute(
            "SELECT category, COUNT(*) as n FROM memories GROUP BY category").fetchall():
            by_cat[row["category"]] = row["n"]
        return {"total": total, "by_category": by_cat}


def extract_from_text(user_text: str, call_ingest_model) -> list:
    """
    从用户消息中提取可记忆的内容(调便宜 LLM)。
    返回 [(content, category, importance), ...]。
    """
    if not user_text or len(user_text) < 10:
        return []
    if not call_ingest_model:
        return []

    prompt = EXTRACT_PROMPT.format(text=user_text[:1500])
    try:
        resp = (call_ingest_model([{"role": "user", "content": prompt}],
                 None, False).get("content") or "").strip()
        # 解析 JSON 数组
        if resp.startswith("["):
            items = _json.loads(resp)
        else:
            # 尝试提取 [...]
            s, e = resp.find("["), resp.rfind("]")
            if s != -1 and e != -1:
                items = _json.loads(resp[s:e + 1])
            else:
                return []
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            cat = str(item.get("category", "fact")).strip()
            if cat not in CATEGORIES:
                cat = "fact"
            cont = str(item.get("content", "")).strip()
            if not cont:
                continue
            imp = int(item.get("importance", 5))
            result.append((cont, cat, max(1, min(10, imp))))
        return result
    except Exception as e:
        _log.debug("记忆提取失败(非关键): %s", e)
        return []


def extract_and_store(user_text: str, call_ingest_model, user_id: str = "") -> int:
    """
    从用户消息提取记忆并自动存入数据库。返回新增条数。
    失败静默(记忆提取是 best-effort,不应影响主对话)。
    """
    items = extract_from_text(user_text, call_ingest_model)
    count = 0
    for content, category, importance in items:
        try:
            add_memory(content, category, importance, user_id)
            count += 1
        except Exception as e:
            _log.debug("记忆存储失败: %s", e)
    if count:
        _log.info("自动提取 %d 条记忆", count)
    return count


def format_for_prompt(memories: list, max_chars: int = 800) -> str:
    """将记忆列表格式化为可注入 system prompt 的文本。"""
    if not memories:
        return ""
    lines = ["\n[相关记忆]"]
    total = 0
    for m in memories:
        cat_icon = {"preference": "💚", "fact": "📌", "goal": "🎯",
                    "emotion": "💭", "progress": "📊"}
        icon = cat_icon.get(m.get("category", ""), "•")
        line = f"{icon} {m['content']}"
        total += len(line)
        if total > max_chars:
            lines.append("…(更多记忆省略)")
            break
        lines.append(line)
    return "\n".join(lines)

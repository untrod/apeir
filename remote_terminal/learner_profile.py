# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 学习者画像 + 持久记忆 + 主动引导。

核心设计:
  1. 学习者画像 — 学习风格、节奏、活跃时段、强弱项
  2. 跨会话记忆 — 上次学到哪、卡在哪、偏好什么
  3. 主动引导 — AI 不是等待提问，而是主动给建议
  4. 人格适配 — 像 Claude 一样记住用户的习惯和偏好

工作方式:
  - 每次对话开始时，画像注入到 system prompt
  - 每次对话结束时，从消息中自动提取关键信息更新画像
  - 画像持久化在 learn_db 中
"""

import json
import logging
from datetime import date, datetime

import learn_db

log = logging.getLogger("learner")



# 画像数据结构


DEFAULT_PROFILE = {
    "name": "",
    "level": "beginner",          # beginner / intermediate / advanced
    "goals": [],                   # User-defined goals
    "active_subjects": [],         # ["math","english"]
    "weak_subjects": [],           # ["english"]
    "strong_subjects": [],         # ["math"]

    # 学习风格
    "style": {
        "prefers_examples": True,       # 喜欢看例题
        "prefers_theory_first": False,  # 先理论后实践
        "prefers_voice": True,          # 偏好语音交互
        "prefers_quick": True,          # 喜欢简短回复(手表场景)
        "pace": "normal",               # slow / normal / fast
    },

    # 行为模式
    "behavior": {
        "active_hours": [],             # ["08:00","20:00"]
        "avg_session_minutes": 15,      # 平均每次学习时长
        "avg_questions_per_session": 5, # 平均每次问题数
        "preferred_time": "evening",    # morning/afternoon/evening/night
        "consecutive_days": 0,          # 连续学习天数
    },

    # 当前状态
    "current": {
        "last_studied": "",             # 最后学习日期
        "last_subject": "",             # 最后学科
        "last_topic": "",               # 最后知识点
        "current_course_id": None,      # 当前课程
        "current_exam_id": None,        # 最近考试
        "stuck_on": [],                 # 卡住的知识点
        "recent_improvements": [],      # 最近有进步的知识点
    },

    # 偏好
    "preferences": {
        "default_subject": "math",
        "cards_per_review": 10,
        "questions_per_quiz": 3,
        "review_reminder_time": "20:00",
    },

    # 学习风格(VARK模型 — 自动追踪)
    "learning_style": {
        "visual": 0.25,        # 偏好图表/可视化
        "auditory": 0.25,       # 偏好语音/讲解
        "reading": 0.25,        # 偏好阅读/文字
        "kinesthetic": 0.25,    # 偏好动手/练习
        "socratic_preferred": False,  # 偏好引导式教学
        "detail_level": "concise",    # concise / normal / detailed
        "examples_requested": 0,      # 用户主动要例题的次数
        "voice_interactions": 0,      # 语音交互次数
    },

    # 统计数据(自动更新)
    "stats": {
        "total_sessions": 0,
        "total_questions": 0,
        "total_correct": 0,
        "longest_streak": 0,
        "created_at": "",
        "updated_at": "",
    },
}


def _raw_db():
    """获取原始 sqlite3 连接(用于建表等操作)。"""
    import sqlite3
    db = sqlite3.connect(learn_db._db_path())
    db.row_factory = sqlite3.Row
    return db


def _init_tables():
    """确保画像相关表存在。"""
    db = _raw_db()
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS learner_profile (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS learner_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT DEFAULT 'general',
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,
                source TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS interaction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT DEFAULT '',
                user_input TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                intent TEXT DEFAULT '',
                tools_used TEXT DEFAULT '',
                duration_seconds INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        db.commit()
    finally:
        db.close()


def load_profile() -> dict:
    """加载学习者画像。"""
    _init_tables()
    db = _raw_db()
    try:
        row = db.execute(
            "SELECT value FROM learner_profile WHERE key='profile'").fetchone()
        if row:
            try:
                saved = json.loads(row["value"])
                profile = DEFAULT_PROFILE.copy()
                _deep_update(profile, saved)
                return profile
            except Exception:
                pass
        return DEFAULT_PROFILE.copy()
    finally:
        db.close()


def save_profile(profile: dict):
    """保存学习者画像。"""
    profile["stats"]["updated_at"] = datetime.now().isoformat()
    db = _raw_db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO learner_profile (key, value) VALUES (?,?)",
            ("profile", json.dumps(profile, ensure_ascii=False)))
        db.commit()
    finally:
        db.close()


def update_profile(**kwargs):
    """更新画像的部分字段。"""
    profile = load_profile()
    _deep_update(profile, kwargs)
    save_profile(profile)
    return profile



# 跨会话记忆


def add_memory(category: str, content: str, importance=1, source=""):
    """添加一条持久记忆。类似 Claude 的 memory 系统。"""
    db = _raw_db()
    try:
        db.execute("INSERT INTO learner_memory (category,content,importance,source) "
                   "VALUES (?,?,?,?)", (category, content, importance, source))
        db.commit()
    finally:
        db.close()


def get_memories(category="", limit=30) -> list:
    """获取记忆。按重要度降序。"""
    db = _raw_db()
    try:
        if category:
            rows = db.execute(
                "SELECT * FROM learner_memory WHERE category=? "
                "ORDER BY importance DESC, created_at DESC LIMIT ?",
                (category, limit)).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM learner_memory "
                "ORDER BY importance DESC, created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_recent_memories(days=7, limit=20) -> list:
    """获取最近的记忆(用于注入 system prompt)。"""
    db = _raw_db()
    try:
        rows = db.execute(
            "SELECT * FROM learner_memory WHERE created_at >= date('now', ?) "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (f"-{days}d", limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()



# 交互日志(自动学习)


def log_interaction(session_id="", user_input="", subject="",
                    intent="", tools_used=""):
    """记录一次交互,用于分析用户行为模式。"""
    db = _raw_db()
    try:
        db.execute(
            "INSERT INTO interaction_log (session_id, user_input, subject, "
            "intent, tools_used) VALUES (?,?,?,?,?)",
            (session_id, user_input[:500], subject, intent, tools_used))
        db.commit()
    finally:
        db.close()



# 画像自动更新引擎


class ProfileUpdater:
    """
    根据对话内容自动更新画像。

    更新规则:
      - 检测到新科目 → 加到 active_subjects
      - 检测到卡住/不会 → 加到 stuck_on
      - 检测到进步 → 加到 recent_improvements
      - 统计连续天数 → 更新 consecutive_days
      - 每次对话更新 last_studied / last_subject
    """

    def __init__(self, call_model=None):
        self.call_model = call_model

    def analyze_conversation(self, messages: list, session_id="") -> dict:
        """
        分析一轮对话,返回画像更新建议。

        messages: [{"role":"user","content":"..."}, ...]
        """
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        assistant_messages = [m["content"] for m in messages
                            if m.get("role") == "assistant"]

        if not user_messages:
            return {}

        # 本地规则提取
        updates = {"current": {}}

        # 检测科目
        subject = self._detect_subject(" ".join(user_messages[-3:]))
        if subject:
            updates["current"]["last_subject"] = subject

        # 检测情绪/状态
        last_user = user_messages[-1].lower()
        stuck_keywords = ["不会", "不懂", "不明白", "卡住了", "怎么算", "做错了", "错了"]
        if any(kw in last_user for kw in stuck_keywords):
            topic = last_user[:80]
            updates["current"] = {"stuck_on_topic": topic}

        # 更新时间
        updates["current"]["last_studied"] = date.today().isoformat()

        # 连续天数
        profile = load_profile()
        last = profile["current"].get("last_studied", "")
        today = date.today()
        if last and last != str(today):
            last_date = date.fromisoformat(last) if last else today
            if (today - last_date).days == 1:
                updates["behavior"] = {
                    "consecutive_days": profile["behavior"]["consecutive_days"] + 1}
                if updates["behavior"]["consecutive_days"] > profile["stats"]["longest_streak"]:
                    updates["stats"] = {
                        "longest_streak": updates["behavior"]["consecutive_days"]}
            elif (today - last_date).days > 1:
                updates["behavior"] = {"consecutive_days": 1}

        return updates

    def update_from_conversation(self, messages: list, session_id=""):
        """从对话更新画像。"""
        updates = self.analyze_conversation(messages, session_id)
        if updates:
            update_profile(**updates)

    def add_learning_memory(self, user_text: str, assistant_reply: str):
        """从对话中提取关键信息,存入持久记忆。"""
        # 简单规则: 用户明确表达的信息
        indicators = {
            "goal": ["我要考", "我的目标是", "我想学", "准备"],
            "preference": ["我喜欢", "我习惯", "我一般"],
            "struggle": ["我老是错", "总是搞混", "记不住"],
            "progress": ["我学会了", "终于懂了", "掌握了"],
        }
        user_lower = user_text.lower()
        for category, keywords in indicators.items():
            if any(kw in user_lower for kw in keywords):
                add_memory(category, user_text[:300], importance=3,
                           source="conversation")
                break

    @staticmethod
    def _detect_subject(text: str) -> str:
        from subject_experts import detect_subject
        return detect_subject(text)



# 画像 → System Prompt 注入


def build_persona_prompt() -> str:
    """
    将学习者画像转为 system prompt 注入片段。
    类似 Claude 的记忆系统: 每次对话开始时加载。
    """
    profile = load_profile()
    memories = get_recent_memories(14, 10)

    parts = ["\n\n[学习者档案 — 这是你正在辅导的学生]\n"]

    # 基本信息
    if profile.get("name"):
        parts.append(f"学生称呼: {profile['name']}")
    parts.append(f"学习阶段: {profile['level']}")

    # 目标
    goals = profile.get("goals", [])
    if goals:
        parts.append(f"目标: {', '.join(goals)}")

    # 强弱项
    strong = profile.get("strong_subjects", [])
    weak = profile.get("weak_subjects", [])
    if strong:
        parts.append(f"擅长: {', '.join(strong)}")
    if weak:
        parts.append(f"薄弱: {', '.join(weak)}")

    # 学习风格
    style = profile.get("style", {})
    style_parts = []
    if style.get("prefers_quick"):
        style_parts.append("喜欢简短回复")
    if style.get("prefers_examples"):
        style_parts.append("喜欢看例题")
    if style.get("prefers_voice"):
        style_parts.append("常用语音交互")
    if style.get("pace"):
        pace_map = {"slow": "需要慢慢讲", "normal": "正常节奏",
                     "fast": "喜欢快节奏"}
        style_parts.append(pace_map.get(style["pace"], ""))
    if style_parts:
        parts.append(f"学习风格: {', '.join(style_parts)}")

    # 当前状态
    cur = profile.get("current", {})
    if cur.get("last_studied"):
        parts.append(f"上次学习: {cur['last_studied']}")
    if cur.get("last_subject"):
        parts.append(f"最近在学: {cur['last_subject']}")
    if cur.get("stuck_on_topic"):
        parts.append(f"卡在: {cur['stuck_on_topic']}")

    # 行为
    behavior = profile.get("behavior", {})
    if behavior.get("consecutive_days", 0) >= 3:
        parts.append(f"连续学习 {behavior['consecutive_days']} 天")

    # 近期记忆(最近两周)
    if memories:
        parts.append("\n近期学习记忆:")
        for m in memories[:5]:
            parts.append(f"- {m['content'][:100]}")

    # 关键指令
    parts.append("""
## 辅导指引
- 你已经了解这个学生的背景,直接进入主题,不要每次重新自我介绍
- 根据学生的强弱项调整讲解深度。弱项多解释,强项可以快一点
- 学生卡住时主动帮TA找到根因,从更基础的知识点讲起
- 每次结束时给一个自然的学习建议,但不要机械重复
- 学生连续学了很多天时给予鼓励,但不要刻意
- 像老师记住学生一样,你记住TA的学习历程
""")

    return "\n".join(parts)



# 便捷函数


def _deep_update(target: dict, source: dict):
    """递归合并字典。"""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


_updater = None


def get_profile_updater(call_model=None):
    global _updater
    if not _updater:
        _updater = ProfileUpdater(call_model)
    return _updater


# 首次导入时初始化
_init_tables()

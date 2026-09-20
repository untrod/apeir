# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 智能课表 + 时间管理 + 学习方法指引。

课表系统:
  - 自然语言快速创建: "周一上午8-10点高数课"
  - 周循环固定安排(上课/固定活动)
  - 空闲时间检测
  - 智能学习任务分配(在空隙中安排复习/做题)

学习方法系统:
  - 8种科学学习方法,AI根据场景自动选择
  - 间隔重复、主动回忆、费曼技巧、刻意练习等
"""

import logging
from datetime import date
from collections import defaultdict

log = logging.getLogger("schedule")



# 8 种学习方法指引


LEARNING_METHODS = {
    "spaced_repetition": {
        "name": "间隔重复",
        "desc": "在遗忘临界点复习,不是反复看,而是隔几天测一次",
        "when": "公式记忆、单词背诵、概念巩固",
        "instruction": "不要今天学完就反复看。明天、3天后、7天后各测一次。"
    },
    "active_recall": {
        "name": "主动回忆",
        "desc": "合上书,自己说出来/写出来,比反复阅读有效3倍",
        "when": "复习任何内容时",
        "instruction": "不要看笔记！先自己回想。想不起来再看,这样记得更牢。"
    },
    "feynman": {
        "name": "费曼技巧",
        "desc": "用最简单的话解释给别人听,解释不清的地方就是没真懂",
        "when": "理解概念、攻克难点",
        "instruction": "假装你在教一个完全不懂的人。用大白话解释。卡住了说明你没真懂。"
    },
    "interleaving": {
        "name": "交错练习",
        "desc": "混合练习不同题型,而不是集中练同一种",
        "when": "刷题时",
        "instruction": "不要连续做5道导数题。混着来:1道导数+1道极限+1道积分。效果更好。"
    },
    "deliberate_practice": {
        "name": "刻意练习",
        "desc": "专攻弱点,不在已掌握的内容上浪费时间",
        "when": "时间有限时",
        "instruction": "已经会的不练。只练不会的。每次练习都要比上次难一点。"
    },
    "pomodoro": {
        "name": "番茄工作法",
        "desc": "25分钟专注学习 → 5分钟休息 → 循环",
        "when": "长时间学习",
        "instruction": "设25分钟计时器。这25分钟只做一件事。响了就休息5分钟。"
    },
    "scaffolding": {
        "name": "脚手架法",
        "desc": "从简单到复杂,每一步只增加一个难度",
        "when": "学新内容",
        "instruction": "先给最简单的情况→你做→稍难一点→你做→再难一点。逐步搭建。"
    },
    "metacognition": {
        "name": "元认知反思",
        "desc": "学完后问自己:我刚学了什么?怎么学的?哪里还不懂?",
        "when": "每次学习结束",
        "instruction": "用30秒总结:今天学了什么?哪里最困难?明天重点是什么?"
    },
}


def get_method_suggestion(subject="", topic="", mastery=0,
                          is_review=False, is_new=False) -> list:
    """根据场景推荐学习方法。"""
    methods = []
    if is_new:
        methods.extend(["scaffolding", "feynman"])
    if is_review:
        methods.extend(["spaced_repetition", "active_recall"])
    if mastery < 50:
        methods.append("deliberate_practice")
    if mastery >= 70:
        methods.append("interleaving")
    methods.append("metacognition")  # 每次都有
    if len(methods) > 3:
        methods = methods[:3]
    return methods



# 课表引擎


WEEKDAYS_CN = {
    "周一": 0, "星期一": 0, "Monday": 0, "mon": 0,
    "周二": 1, "星期二": 1, "Tuesday": 1, "tue": 1,
    "周三": 2, "星期三": 2, "Wednesday": 2, "wed": 2,
    "周四": 3, "星期四": 3, "Thursday": 3, "thu": 3,
    "周五": 4, "星期五": 4, "Friday": 4, "fri": 4,
    "周六": 5, "星期六": 5, "Saturday": 5, "sat": 5,
    "周日": 6, "星期天": 6, "星期日": 6, "Sunday": 6, "sun": 6,
}

TIME_PATTERNS = [
    (r"(\d{1,2})[:：](\d{2})\s*[-~到至]\s*(\d{1,2})[:：](\d{2})", "HH:MM-HH:MM"),
    (r"(\d{1,2})[-~到至](\d{1,2})点", "H-H点"),
    (r"上午\s*(\d{1,2})[-~到至]?\s*(\d{1,2})?", "上午"),
    (r"下午\s*(\d{1,2})[-~到至]?\s*(\d{1,2})?", "下午"),
]


def _init_timetable_db():
    """确保课表表存在。"""
    import sqlite3
    db = sqlite3.connect(
        __import__('learn_db')._db_path())
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            category TEXT DEFAULT 'class',
            location TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            recurring INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            estimated_minutes INTEGER DEFAULT 30,
            priority INTEGER DEFAULT 2,
            completed INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS study_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            subject TEXT DEFAULT '',
            task_type TEXT DEFAULT 'study',
            task_detail TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            source TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_tt_weekday ON timetable(weekday);
        CREATE INDEX IF NOT EXISTS idx_hw_due ON homework(due_date);
        CREATE INDEX IF NOT EXISTS idx_ss_date ON study_slots(date);
    """)
    db.commit()
    db.close()


class TimetableEngine:
    """课表管理 + 空闲检测 + 智能排课。"""

    def __init__(self):
        _init_timetable_db()

    def add_slot(self, name, weekday, start_time, end_time,
                 category="class", location="", recurring=True) -> int:
        """添加一个时间槽。weekday: 0=周一...6=周日。"""
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        try:
            c = db.execute(
                "INSERT INTO timetable (name,weekday,start_time,end_time,"
                "category,location,recurring) VALUES (?,?,?,?,?,?,?)",
                (name, weekday, start_time, end_time, category, location,
                 1 if recurring else 0))
            db.commit()
            return c.lastrowid
        finally:
            db.close()

    def parse_natural(self, text: str) -> dict:
        """
        从自然语言解析课表条目。

        支持:
          "周一上午8点到10点高数课在教3-101"
          "每周三下午2点到4点英语"
          "周二 8:00-9:40 计算机 在机房"
          "周四晚上7-9点自习"
        """
        import re
        text = text.strip()

        weekday = -1
        start_time = ""
        end_time = ""
        name = text
        location = ""

        # 检测星期
        for kw, wd in WEEKDAYS_CN.items():
            if kw.lower() in text.lower():
                weekday = wd
                break

        # 检测时间(先检查上午/下午以确定偏移)
        pm_offset = 0
        if "下午" in text or "晚上" in text:
            pm_offset = 12

        time_match = re.search(
            r"(\d{1,2})[:：](\d{2})\s*[-~到至]\s*(\d{1,2})[:：](\d{2})", text)
        if time_match:
            h1 = int(time_match.group(1))
            h2 = int(time_match.group(3))
            if pm_offset and h1 < 12:
                h1 += pm_offset
            if pm_offset and h2 < 12:
                h2 += pm_offset
            start_time = f"{h1:02d}:{time_match.group(2)}"
            end_time = f"{h2:02d}:{time_match.group(4)}"
        else:
            time_match2 = re.search(
                r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})\s*点", text)
            if time_match2:
                h1 = int(time_match2.group(1))
                h2 = int(time_match2.group(2))
                if pm_offset and h1 < 12:
                    h1 += pm_offset
                if pm_offset and h2 < 12:
                    h2 += pm_offset
                start_time = f"{h1:02d}:00"
                end_time = f"{h2:02d}:00"

        # 上午/下午(仅 HH:MM 模式未匹配时)
        if not start_time:
            if "上午" in text:
                hm = re.search(r"上午\s*(\d{1,2})", text)
                if hm:
                    h = int(hm.group(1))
                    start_time = f"{h:02d}:00"
                    end_time = f"{h+2:02d}:00"
            elif "下午" in text:
                hm = re.search(r"下午\s*(\d{1,2})", text)
                if hm:
                    h = int(hm.group(1))
                    h = h + 12 if h <= 12 else h
                    start_time = f"{h:02d}:00"
                    end_time = f"{h+2:02d}:00"
            elif "晚上" in text:
                hm = re.search(r"晚上\s*(\d{1,2})", text)
                if hm:
                    h = int(hm.group(1))
                    h = h + 12 if h < 12 else h
                    start_time = f"{h:02d}:00"
                    end_time = f"{h+2:02d}:00"

        if not start_time:
            start_time = "08:00"
            end_time = "10:00"

        # 检测地点
        loc_match = re.search(r"(?:在|教室|机房|实验室|图书馆)(\S+)", text)
        if loc_match:
            location = loc_match.group(0)

        # 提取课程名(去掉时间星期地点)
        name = re.sub(r"(周[一二三四五六日天]|星期[一二三四五六日天]|上午|下午|晚上"
                      r"|\d{1,2}[:：]\d{2}\s*[-~到至]\s*\d{1,2}[:：]\d{2}"
                      r"|\d{1,2}\s*[-~到至]\s*\d{1,2}\s*点|在\S+)", "", text)
        name = name.strip().strip("，,。. ")

        # 检测类型
        category = "class"
        type_keywords = {
            "自习": "self_study", "复习": "review", "考试": "exam",
            "实验": "lab", "实习": "internship", "社团": "club",
            "运动": "sport", "休息": "rest",
        }
        for kw, cat in type_keywords.items():
            if kw in text:
                category = cat
                break

        return {
            "name": name or "未命名",
            "weekday": max(0, weekday),
            "start_time": start_time or "08:00",
            "end_time": end_time or "10:00",
            "category": category,
            "location": location,
        }

    def get_week_schedule(self) -> dict:
        """获取一周课表(按星期分组)。"""
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute(
                "SELECT * FROM timetable WHERE active=1 ORDER BY weekday, start_time"
            ).fetchall()
        finally:
            db.close()

        week = defaultdict(list)
        for r in rows:
            d = dict(r)
            week[d["weekday"]].append(d)
        return dict(week)

    def get_today_schedule(self) -> list:
        """获取今日课表。"""
        today_wd = date.today().weekday()
        week = self.get_week_schedule()
        return week.get(today_wd, [])

    def get_free_slots(self, date_str="") -> list:
        """计算某天的空闲时间段。"""
        if not date_str:
            date_str = date.today().isoformat()
        wd = date.fromisoformat(date_str).weekday()
        week = self.get_week_schedule()
        occupied = week.get(wd, [])

        # 固定上课时间
        busy = [(s["start_time"], s["end_time"]) for s in occupied]

        # 已安排的学习槽
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        db.row_factory = sqlite3.Row
        try:
            study_rows = db.execute(
                "SELECT * FROM study_slots WHERE date=? AND completed=0",
                (date_str,)).fetchall()
        finally:
            db.close()
        for s in study_rows:
            busy.append((s["start_time"], s["end_time"]))

        busy.sort()

        # 默认可学习时间窗口: 8:00-22:00
        free = []
        cursor = "08:00"
        day_end = "22:00"
        for s, e in busy:
            if cursor < s:
                free.append({"start": cursor, "end": s,
                            "duration_min": _time_diff(cursor, s)})
            cursor = max(cursor, e)
        if cursor < day_end:
            free.append({"start": cursor, "end": day_end,
                        "duration_min": _time_diff(cursor, day_end)})

        return [f for f in free if f["duration_min"] >= 15]

    def auto_schedule_study(self, date_str="",
                            available_minutes=60) -> list:
        """在空闲时间自动安排学习任务。"""
        if not date_str:
            date_str = date.today().isoformat()
        free_slots = self.get_free_slots(date_str)

        # 获取待办
        import learn_db
        due_formulas = learn_db.get_due_formulas(limit=5)
        weak_kps = learn_db.get_weak_topics(top_n=5)
        homework = self.get_homework(due_only=True)

        tasks = []
        total_free = sum(f["duration_min"] for f in free_slots)

        if total_free < 15:
            return []

        # 分配策略: 40% 弱项复习, 30% 公式, 20% 作业, 10% 新学
        review_min = int(total_free * 0.4)
        formula_min = int(total_free * 0.3)
        hw_min = int(total_free * 0.2)

        current_slot = 0
        cursor_time = free_slots[0]["start"] if free_slots else "08:00"

        # 安排弱项复习
        for kp in weak_kps[:2]:
            if review_min <= 0 or current_slot >= len(free_slots):
                break
            dur = min(25, review_min)
            end_t = _add_minutes(cursor_time, dur)
            self._save_study_slot(date_str, cursor_time, end_t,
                                  kp.get("subject", ""), "review",
                                  f"复习 {kp['title']}")
            tasks.append({
                "time": f"{cursor_time}-{end_t}",
                "task": f"复习 {kp['title']}",
                "duration": dur, "type": "review",
                "method": ["active_recall", "spaced_repetition"],
            })
            cursor_time = end_t
            review_min -= dur

        # 安排公式复习
        for fm in due_formulas[:3]:
            if formula_min <= 0:
                break
            dur = min(15, formula_min)
            end_t = _add_minutes(cursor_time, dur)
            self._save_study_slot(date_str, cursor_time, end_t,
                                  fm.get("subject", ""), "formula",
                                  f"公式: {fm['name']}")
            tasks.append({
                "time": f"{cursor_time}-{end_t}",
                "task": f"公式: {fm['name']}",
                "duration": dur, "type": "formula",
                "method": ["spaced_repetition"],
            })
            cursor_time = end_t
            formula_min -= dur

        # 安排作业
        for hw in homework[:2]:
            if hw_min <= 0:
                break
            dur = min(hw.get("estimated_minutes", 30), hw_min)
            end_t = _add_minutes(cursor_time, dur)
            self._save_study_slot(date_str, cursor_time, end_t,
                                  hw.get("subject", ""), "homework",
                                  hw["title"])
            tasks.append({
                "time": f"{cursor_time}-{end_t}",
                "task": f"作业: {hw['title']}",
                "duration": dur, "type": "homework",
            })
            cursor_time = end_t
            hw_min -= dur

        return tasks

    def _save_study_slot(self, date_str, start, end, subject, task_type, detail):
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        try:
            db.execute(
                "INSERT INTO study_slots (date,start_time,end_time,subject,"
                "task_type,task_detail) VALUES (?,?,?,?,?,?)",
                (date_str, start, end, subject, task_type, detail))
            db.commit()
        finally:
            db.close()

    # 作业管理
    def add_homework(self, title, subject="", due_date="",
                     estimated_minutes=30, priority=2) -> int:
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        try:
            c = db.execute(
                "INSERT INTO homework (title,subject,due_date,"
                "estimated_minutes,priority) VALUES (?,?,?,?,?)",
                (title, subject, due_date, estimated_minutes, priority))
            db.commit()
            return c.lastrowid
        finally:
            db.close()

    def get_homework(self, due_only=False) -> list:
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        db.row_factory = sqlite3.Row
        try:
            if due_only:
                rows = db.execute(
                    "SELECT * FROM homework WHERE completed=0 "
                    "ORDER BY priority DESC, due_date ASC").fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM homework ORDER BY completed, priority DESC, "
                    "due_date ASC LIMIT 20").fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    def complete_homework(self, hw_id: int):
        import sqlite3
        db = sqlite3.connect(__import__('learn_db')._db_path())
        try:
            db.execute("UPDATE homework SET completed=1 WHERE id=?", (hw_id,))
            db.commit()
        finally:
            db.close()



# 辅助函数


def _time_diff(t1: str, t2: str) -> int:
    h1, m1 = map(int, t1.split(":"))
    h2, m2 = map(int, t2.split(":"))
    return (h2 - h1) * 60 + (m2 - m1)


def _add_minutes(t: str, minutes: int) -> str:
    h, m = map(int, t.split(":"))
    total = h * 60 + m + minutes
    return f"{total // 60 % 24:02d}:{total % 60:02d}"


_tt_engine = None


def get_timetable_engine():
    global _tt_engine
    if not _tt_engine:
        _tt_engine = TimetableEngine()
    return _tt_engine

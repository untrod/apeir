# -*- coding: utf-8 -*-
"""
Quick Capture + Closed-Loop Engine.

Three real closed loops:
  1. Quick Capture: text → classify → inbox → viewable
  2. Study Question: ask → weak points → review Job → evening notify
  3. PC Offline Task: create → WAITING_FOR_DEVICE → auto-claim → notify

Usage:
  from nous_core.capture import capture, get_inbox, process_study_question
"""

from __future__ import annotations

import json as _json
import logging as _logging
import re as _re
from typing import Any

from . import ids as _ids
from . import time as _time
from .db import connect as _connect

_log = _logging.getLogger("nous_core.capture")

# Quick classification keywords
_CLASSIFY_RULES: list[tuple[list[str], str]] = [
    (["学", "题", "练", "考", "复习", "背", "单词", "公式", "知识", "数学", "英语", "语文",
      "计算机", "高数", "政治", "真题", "错题", "笔记", "讲义", "课程"], "study"),
    (["做", "买", "购物", "提醒", "记得", "别忘了", "别忘了", "日程", "日历", "今天", "明天",
      "待办", "todo", "任务"], "todo"),
    (["想法", "创意", "思路", "灵感", "设计", "应该", "也许", "或许", "可以试试"], "idea"),
    (["提醒我", "叫我", "闹钟", "定时", "几点", "分钟后"], "reminder"),
    (["http", "www", "链接", "网址", "查看这个", "看这个"], "link"),
]


# Loop 1: Quick Capture

def capture(
    content: str,
    *,
    content_type: str = "text",
    source: str = "unknown",
    session_id: str = "",
    auto_classify: bool = True,
) -> dict[str, Any]:
    """
    Capture a piece of text/voice into the inbox. Auto-classifies by content.

    Returns the created inbox entry.
    """
    iid = _ids.make_id("inb")
    now = _time.utc_now()
    category = _classify(content) if auto_classify else "uncategorized"
    tags = _extract_tags(content, category)
    priority = _calc_priority(category, content)

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO inbox (id, content, content_type, source, category,
                   tags, priority, status, session_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
                (iid, content[:2000], content_type, source, category,
                 _json.dumps(tags, ensure_ascii=False), priority, session_id, now),
            )
        _log.debug("Captured: %s [%s] from %s", content[:40], category, source)
        return {
            "id": iid, "content": content[:2000], "content_type": content_type,
            "source": source, "category": category, "tags": tags,
            "priority": priority, "status": "new", "created_at": now,
        }
    except Exception as e:
        _log.error("capture failed: %s", e)
        return {"id": "", "error": str(e)}


def get_inbox(
    status: str = "new",
    category: str = "",
    source: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query inbox entries."""
    limit = max(1, min(limit, 200))
    conds: list[str] = []
    params: list[Any] = []

    if status:
        conds.append("status = ?"); params.append(status)
    if category:
        conds.append("category = ?"); params.append(category)
    if source:
        conds.append("source = ?"); params.append(source)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    query = f"SELECT * FROM inbox {where} ORDER BY priority DESC, created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with _connect(readonly=True) as db:
            return [_row_to_inbox(r) for r in db.execute(query, params).fetchall()]
    except Exception:
        return []


def mark_inbox(item_id: str, status: str = "reviewed") -> bool:
    """Mark an inbox item as reviewed/archived/deleted."""
    now = _time.utc_now()
    col = {"reviewed": "reviewed_at", "archived": "archived_at"}.get(status, "reviewed_at")
    try:
        with _connect() as db:
            db.execute(f"UPDATE inbox SET status = ?, {col} = ? WHERE id = ?",
                       (status, now, item_id))
        return True
    except Exception:
        return False


def inbox_counts(source: str = "") -> dict[str, int]:
    """Get counts by status and category for inbox overview."""
    try:
        with _connect(readonly=True) as db:
            conds: list[str] = []
            params: list[Any] = []
            if source:
                conds.append("source = ?"); params.append(source)

            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            new_where = ("WHERE " + " AND ".join(conds + ["status='new'"])) if conds else "WHERE status='new'"

            by_status = db.execute(
                f"SELECT status, COUNT(*) as n FROM inbox {where} GROUP BY status", params
            ).fetchall()
            by_cat = db.execute(
                f"SELECT category, COUNT(*) as n FROM inbox {new_where} GROUP BY category", params
            ).fetchall()
            return {
                "by_status": {r["status"]: r["n"] for r in by_status},
                "by_category": {r["category"]: r["n"] for r in by_cat},
                "total_new": sum(r["n"] for r in by_status if r["status"] == "new"),
            }
    except Exception:
        return {"by_status": {}, "by_category": {}, "total_new": 0}


# Loop 2: Study Question

_STUDY_KW = ["学", "题", "练", "考", "复习", "背", "单词", "公式", "知识", "数学", "英语",
             "语文", "计算机", "高数", "政治", "真题", "错题", "不会", "怎么", "如何",
             "解释", "讲解", "什么是", "定义", "概念", "原理", "推导", "证明", "计算"]


def is_study_question(text: str) -> bool:
    """Detect if a message is a study-related question."""
    return any(kw in text for kw in _STUDY_KW)


def detect_weak_subjects(text: str) -> list[str]:
    """Extract subject mentions from a study question."""
    subjects = []
    subject_kw = {
        "高数": ["高数", "数学", "微积分", "线性代数", "概率", "函数", "极限", "导数", "积分"],
        "英语": ["英语", "英文", "语法", "阅读", "翻译", "作文", "词汇", "单词"],
        "语文": ["语文", "文言文", "作文", "阅读", "诗词", "古文"],
        "计算机": ["计算机", "编程", "二进制", "网络", "操作系统", "数据库"],
        "政治": ["政治", "马原", "毛概", "思修"],
    }
    for subj, keywords in subject_kw.items():
        if any(kw in text for kw in keywords):
            subjects.append(subj)
    return subjects or ["unknown"]


def process_study_question(
    question: str,
    session_id: str = "",
    source: str = "phone",
) -> dict[str, Any]:
    """
    Process a study question through the closed loop:
      1. Capture to inbox (study category)
      2. Detect weak subjects
      3. Create a review job for tonight
      4. Create notification for evening review prompt

    Returns summary of what happened.
    """
    # 1. Capture
    entry = capture(question, content_type="text", source=source,
                    session_id=session_id)
    # 2. Detect weak subjects
    subjects = detect_weak_subjects(question)
    # 3. Create review job (scheduled for 21:00)
    jid = ""
    try:
        from .jobs import create_job as _create_job
        jid = _create_job(
            "review_study",
            source="study_loop",
            session_id=session_id,
            payload={
                "question": question[:400],
                "subjects": subjects,
                "scheduled_for": "21:00",
                "action": "generate_review_questions",
            },
            timeout_sec=600,
        )
    except Exception as e:
        _log.warning("Failed to create review job: %s", e)

    # 4. Create evening notification (won't fire until automation picks it up)
    nid = ""
    try:
        from .notifications import notify as _notify
        nid = _notify(
            "study.review_ready",
            title=f"📚 今晚复习: {', '.join(subjects[:2])}",
            body=f"基于你的提问「{question[:60]}...」，今晚安排了 {len(subjects)} 个科目的复习。",
            target_client=source,
            priority=1,
            data={"job_id": jid, "subjects": subjects},
        )
    except Exception as e:
        _log.warning("Failed to create notification: %s", e)

    _log.info("Study loop: captured=%s subjects=%s job=%s notify=%s",
              entry.get("id", "?"), subjects, jid or "?", nid or "?")

    return {
        "inbox_id": entry.get("id", ""),
        "subjects": subjects,
        "review_job_id": jid,
        "notification_id": nid,
    }


# Loop 3: PC Offline Task

def create_offline_task(
    task_type: str,
    command: str,
    *,
    session_id: str = "",
    source: str = "phone",
    target_device: str = "laptop",
) -> dict[str, Any]:
    """
    Create a task that waits for the PC to come online before executing.

    The task goes into WAITING_FOR_DEVICE status. When the device.online
    event fires for the target device, the automation engine picks it up
    and claims+executes the task.
    """
    try:
        from .jobs import create_job as _create_job
        jid = _create_job(
            task_type,
            source=source,
            session_id=session_id,
            device_id=target_device,
            payload={
                "command": command,
                "task_type": task_type,
                "status_note": "Waiting for device to come online",
            },
            timeout_sec=1800,
        )
        # Manually set to a custom status via raw SQL (job system only supports
        # pending→running→done/failed natively)
        with _connect() as db:
            db.execute(
                "UPDATE jobs SET status = 'pending' WHERE id = ?", (jid,)
            )

        # Create notification
        try:
            from .notifications import notify as _notify
            nid = _notify(
                "task.offline_queued",
                title="⏳ 离线任务已排队",
                body=f"任务「{task_type}」将在 {target_device} 上线后自动执行。",
                target_client=source,
                priority=1,
                data={"job_id": jid, "target_device": target_device},
            )
        except Exception:
            nid = ""

        _log.info("Offline task: job=%s type=%s device=%s", jid, task_type, target_device)
        return {"job_id": jid, "notification_id": nid, "target_device": target_device,
                "status": "queued"}

    except Exception as e:
        _log.error("create_offline_task failed: %s", e)
        return {"error": str(e)}


def try_claim_pending_device_tasks(device_id: str) -> int:
    """
    When a device comes online, claim all pending tasks for it.

    This is called by the automation engine when device.online fires.
    Returns the number of tasks claimed.
    """
    try:
        with _connect() as db:
            rows = db.execute(
                "SELECT id, payload FROM jobs WHERE device_id = ? AND status = 'pending' "
                "ORDER BY created_at ASC LIMIT 10",
                (device_id,),
            ).fetchall()

        claimed = 0
        for row in rows:
            # Claim and mark for execution
            db.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                (_time.utc_now(), row["id"]),
            )
            claimed += 1

        if claimed:
            _log.info("Auto-claimed %d pending tasks for device %s", claimed, device_id)
        return claimed
    except Exception as e:
        _log.error("try_claim_pending_device_tasks: %s", e)
        return 0


# Classifiers

def _classify(text: str) -> str:
    """Auto-classify text into a category based on keyword matching."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for keywords, cat in _CLASSIFY_RULES:
        scores[cat] = sum(1 for kw in keywords if kw in text_lower)
    if not scores or max(scores.values()) == 0:
        return "other"
    return max(scores, key=lambda k: scores[k])


def _extract_tags(text: str, category: str) -> list[str]:
    """Extract simple tags from text."""
    tags = [category]
    # Hashtag extraction
    for m in _re.findall(r'#(\w+)', text):
        if m not in tags:
            tags.append(m)
    # Date mentions
    if _re.search(r'(今天|明天|后天|周[一二三四五六日])', text):
        tags.append("has-date")
    # Urgency
    if _re.search(r'(紧急|马上|立刻|快|赶紧|重要)', text):
        tags.append("urgent")
    return tags[:8]


def _calc_priority(category: str, text: str) -> int:
    """Calculate priority 0-2 based on content signals."""
    if _re.search(r'(紧急|马上|立刻|快|赶紧)', text):
        return 2
    if category == "reminder":
        return 1
    if category == "todo":
        return 1
    return 0


def _row_to_inbox(row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["tags"] = _json.loads(d.get("tags", "[]"))
    except (_json.JSONDecodeError, TypeError):
        d["tags"] = []
    return d

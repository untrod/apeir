# -*- coding: utf-8 -*-
"""
Nous 自适应每日计划引擎。
读时计算(纯 DB,不调 LLM):按当前真实状态实时编排"今天该学什么"。
优先级:到期复习(知识点/公式/错题)→ 薄弱强化 → 按章节推进新知识。
按考试剩余天数 + 每日可用分钟做配额;冲刺期偏复习/真题,基础期偏新知识。
学一点掌握度就变,下次调用结果自动变 → 天然实时,跨设备一致。
"""
import json
import time

import learn_db


def _days_until(date_str):
    try:
        import datetime
        d = datetime.date.fromisoformat(str(date_str)[:10])
        return (d - datetime.date.today()).days
    except Exception:
        return None


def compute_today(minutes_budget=None) -> dict:
    learn_db.init()
    today = time.strftime("%Y-%m-%d")

    # 考试与阶段
    exams = learn_db.get_upcoming_exams(365)
    exam = exams[0] if exams else None
    days_left = _days_until(exam["exam_date"]) if exam else None
    sprint = days_left is not None and days_left <= 30  # 冲刺期

    # 优先科目(考试涉及的科目优先)
    pri_subjects = []
    if exam and exam.get("subjects"):
        try:
            pri_subjects = [s for s in json.loads(exam["subjects"]) if s]
        except Exception:
            pri_subjects = []

    budget = minutes_budget or 90
    tasks = []
    seen_kp = set()

    def add(kind, title, subject="", est=8, reason="", kp_id=None):
        if kp_id is not None:
            if kp_id in seen_kp:
                return
            seen_kp.add(kp_id)
        tasks.append({"kind": kind, "title": title, "subject": subject,
                      "est_min": est, "reason": reason, "kp_id": kp_id})

    # 1) 到期复习(最高优先)
    for k in learn_db.get_due_knowledge_points(limit=6):
        add("review", k["title"], k.get("subject", ""), 8,
            "到期复习(间隔记忆)", k["id"])
    try:
        for m in learn_db.get_mistakes(reviewed=False, limit=4):
            q = (m.get("question") or m.get("kp_title") or "错题").strip()
            add("mistake", q[:40], "", 8, "错题重做(还没攻克)")
    except Exception:
        pass
    for f in learn_db.get_due_formulas(limit=5):
        add("formula", f["name"], f.get("subject", ""), 5, "公式到期复习")

    # 2) 薄弱强化(只算"学过但掌握低"的;从没学过的算新知识,不算薄弱)
    cnt = 0
    for w in learn_db.get_weak_topics(top_n=8):
        m = round(w.get("mastery", 0))
        if m <= 0 or m >= 60:
            continue
        add("weak", w["title"], w.get("subject", ""), 10, f"薄弱({m}%)需强化", w["id"])
        cnt += 1
        if cnt >= 3:
            break

    # 3) 推进新知识(冲刺期少上新、多巩固)
    n_new = 2 if sprint else 5
    subj_list = pri_subjects or [""]
    per = max(1, n_new // len(subj_list))
    for s in subj_list:
        for k in learn_db.get_next_unlearned_kp(subject=s, limit=per):
            add("new", k["title"], k.get("subject", ""), 12,
                "按章节推进新知识", k["id"])

    # 单词:复习到期词 + 背新词(聚合成两条,点开由 learn_vocab 取具体词)
    try:
        nv_due = learn_db.count_cards(due_only=True)
        if nv_due:
            d = min(nv_due, 20)
            add("vocab_review", f"复习 {d} 个到期单词", "", max(2, round(d * 0.5)), "词汇间隔复习(到期)")
        nv_new = learn_db.count_cards(new_only=True)
        if nv_new:
            n = min(nv_new, 20 if sprint else 15)
            add("vocab_new", f"背 {n} 个新单词", "", n, "按计划推进词汇")
    except Exception:
        pass

    # 配额裁剪:累计时长超预算时砍尾部(复习类在前,优先保留)
    keep_always = ("review", "mistake", "formula", "vocab_review")
    kept, used = [], 0
    for t in tasks:
        if used + t["est_min"] <= budget or t["kind"] in keep_always:
            kept.append(t); used += t["est_min"]
    tasks = kept

    totals = {
        "review": sum(1 for t in tasks if t["kind"] in ("review", "formula", "mistake", "vocab_review")),
        "weak": sum(1 for t in tasks if t["kind"] == "weak"),
        "new": sum(1 for t in tasks if t["kind"] in ("new", "vocab_new")),
        "est_min": used,
    }
    return {
        "date": today,
        "exam": exam["name"] if exam else "",
        "exam_days": days_left if days_left is not None else -999,
        "budget_min": budget,
        "sprint": sprint,
        "tasks": tasks,
        "totals": totals,
    }


def render_text(plan: dict) -> str:
    """把今日计划渲染成简洁中文(给聊天/工具用)。"""
    if not plan.get("tasks"):
        return "今天暂无可排的任务。先上传资料/注册考试/建目标,我再为你编排。"
    head = "📋 今日计划"
    if plan.get("exam_days", -999) in range(0, 3650):
        head += f"(距「{plan['exam']}」{plan['exam_days']}天{'·冲刺期' if plan.get('sprint') else ''})"
    head += f" 约{plan['totals']['est_min']}分钟"
    icon = {"review": "🔁", "mistake": "❌", "formula": "📐", "weak": "⚠️", "new": "📘",
            "vocab_review": "🔤", "vocab_new": "🆕"}
    lines = [head, ""]
    for i, t in enumerate(plan["tasks"], 1):
        tag = icon.get(t["kind"], "•")
        sub = f"[{t['subject']}]" if t.get("subject") else ""
        lines.append(f"{i}. {tag} {sub}{t['title']} —— {t['reason']}({t['est_min']}min)")
    return "\n".join(lines)



# P2-2: Enhanced Daily Plan with Learning State integration


def get_enhanced_daily_plan(
    available_minutes: int = 120,
    subjects: list[str] | None = None,
    include_new: bool = True,
) -> dict:
    """
    Enhanced daily plan that combines:
      - SM-2 review queue (expired items first)
      - Weakness-based suggestions from learning state
      - New knowledge progression by chapter
      - Time allocation with quotas
    """
    try:
        from nous_core.learning import get_review_queue, get_weakness_ranking, get_subject_summary
    except ImportError:
        return _fallback_plan(available_minutes, subjects, include_new)

    tasks = []
    time_left = available_minutes
    used_ids: set[str] = set()

    # 1. Review Queue (40% of time) — expired SM-2 items
    review_time = int(available_minutes * 0.4)
    review_items = get_review_queue(limit=30)
    for item in review_items:
        if time_left <= 0:
            break
        if item["id"] in used_ids:
            continue
        if subjects and item["subject"] not in subjects:
            continue
        est = 15 if item.get("type") == "formula" else 20
        if time_left >= est:
            tasks.append({
                "kind": "review",
                "subject": item["subject"],
                "title": item["title"][:60],
                "reason": f"{item['days_overdue']}天未复习",
                "est_min": est,
                "source_id": str(item["id"]),
            })
            used_ids.add(item["id"])
            time_left -= est

    # 2. Weakness Strengthening (35% of time)
    weak_time = int(available_minutes * 0.35)
    weak_items = get_weakness_ranking(limit=20)
    for w in weak_items:
        if time_left <= available_minutes - review_time - weak_time or time_left <= 0:
            break
        if subjects and w["subject"] not in subjects:
            continue
        if w["kp_id"] in used_ids:
            continue
        est = min(25, time_left)
        tasks.append({
            "kind": "weak",
            "subject": w["subject"],
            "title": f"{w['chapter']}·{w['title']}"[:60],
            "reason": f"薄弱点(掌握度{w['mastery']})",
            "est_min": est,
            "source_id": str(w["kp_id"]),
        })
        used_ids.add(w["kp_id"])
        time_left -= est

    # 3. New Knowledge (remaining 25% of time)
    if include_new and time_left > 0:
        subjects_list = subjects or _get_all_subjects()
        for subj in subjects_list:
            if time_left <= 0:
                break
            next_new = _get_next_new_kp(subj)
            if next_new and next_new["id"] not in used_ids:
                est = min(25, time_left)
                tasks.append({
                    "kind": "new",
                    "subject": subj,
                    "title": f"{next_new.get('chapter','')}·{next_new.get('title','')}"[:60],
                    "reason": "按章节推进新知识",
                    "est_min": est,
                    "source_id": str(next_new["id"]),
                })
                time_left -= est

    # Stats
    subj_summaries = get_subject_summary()
    return {
        "tasks": tasks,
        "total_est_min": available_minutes - time_left,
        "available_minutes": available_minutes,
        "review_count": sum(1 for t in tasks if t["kind"] == "review"),
        "weak_count": sum(1 for t in tasks if t["kind"] == "weak"),
        "new_count": sum(1 for t in tasks if t["kind"] == "new"),
        "subjects": subj_summaries,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _fallback_plan(available_minutes: int, subjects, include_new: bool) -> dict:
    """Fallback to the legacy plan_engine if nous_core.learning not available."""
    try:
        return make_today_plan(available_minutes, subjects, include_new)
    except Exception:
        return {"tasks": [], "error": "plan unavailable"}


def _get_all_subjects() -> list[str]:
    """Get all subjects from knowledge_points."""
    try:
        import learn_db
        conn = learn_db._conn()
        rows = conn.execute(
            "SELECT DISTINCT subject FROM knowledge_points WHERE subject != '' ORDER BY subject"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []  # Will be populated from knowledge_points table


def _get_next_new_kp(subject: str) -> dict | None:
    """Get the next unlearned knowledge point for a subject."""
    try:
        import learn_db
        kps = learn_db.get_next_unlearned_kp(subject=subject, limit=1, mastery_below=5)
        if kps:
            r = kps[0]
            return {
                "id": r.get("id", 0),
                "chapter": r.get("chapter", ""),
                "section": r.get("section", ""),
                "title": r.get("title", ""),
            }
    except Exception:
        pass
    return None

# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 效率提升模块。

功能:
  1. 专注模式 — 计时学习 + 番茄钟
  2. 快速笔记 — 语音一句话记笔记,自动归档
  3. 弱项预警 — 卡住超过3天的知识点自动提醒
  4. 冲刺模式 — 考前14天强化调度
  5. 微学习 — 5分钟碎片化学习片段
"""

import json
import logging
from datetime import date, datetime

import learn_db

log = logging.getLogger("efficiency")



# 1. 专注模式


class FocusMode:
    """番茄钟计时 + 学习会话追踪。"""

    @staticmethod
    def start_session(subject="", task="", duration_min=25) -> dict:
        """开始一个专注会话。返回会话信息和技巧。"""
        tips = [
            "📵 把手机放远一点",
            "🎯 这25分钟只做这一件事",
            "📝 想到了其他事?写下来,待会儿再处理",
            "⏰ 番茄钟响了就休息,别硬撑",
            "💡 做完一个番茄后,用30秒总结刚才学了什么",
        ]
        import random
        return {
            "subject": subject,
            "task": task,
            "duration": duration_min,
            "started_at": datetime.now().isoformat(),
            "tip": random.choice(tips),
            "method": "pomodoro" if duration_min <= 30 else "deep_work",
        }

    @staticmethod
    def end_session(subject="", duration_min=0, notes="") -> dict:
        """结束会话,记录到进度。"""
        learn_db.log_progress(subject=subject, study_minutes=duration_min,
                              notes=notes)
        total_today = sum(p.get("study_minutes", 0)
                         for p in learn_db.get_today_progress())
        return {
            "recorded": True,
            "today_total_minutes": total_today,
            "suggestion": ("🎉 做得很好！" if duration_min >= 25
                          else "哪怕只学5分钟也比不学好。"),
        }



# 2. 快速笔记


class QuickCapture:
    """一句话笔记,自动分词归档。"""

    @staticmethod
    def capture(text: str, subject="") -> dict:
        """归档一条快速笔记: 判断类型→存入对应表。"""
        text = text.strip()
        if not text:
            return {"error": "内容为空"}

        # 自动分类
        from subject_experts import detect_subject
        detected_subj = detect_subject(text) or subject

        # 判断笔记类型
        is_todo = any(kw in text for kw in ["作业","要做","交","截止","完成","写","做"])
        is_memo = any(kw in text for kw in ["记住","注意","重点","考点","考试"])
        is_question = any(kw in text for kw in ["为什么","怎么","什么是","?"])

        note_type = "todo" if is_todo else "memo" if is_memo else "question" if is_question else "note"

        # 如果是 todo,创建作业
        if is_todo:
            import schedule_engine
            tt = schedule_engine.get_timetable_engine()
            tt.add_homework(text[:200], detected_subj)

        # 存入记忆
        import learner_profile
        learner_profile.add_memory("note", text[:300], importance=2,
                                   source="quick_capture")

        return {
            "type": note_type,
            "subject": detected_subj,
            "archived": True,
            "suggestion": ("📝 已存为作业,查看: learn_my_homework" if is_todo
                          else "📝 已存入记忆,查看: learn_my_profile"),
        }



# 3. 弱项预警


class WeakPointMonitor:
    """监控长期薄弱点,主动提醒。"""

    @staticmethod
    def check() -> dict:
        """检查需要预警的弱项。"""
        # 知识库弱项
        weak_kps = learn_db.get_weak_topics(top_n=15)

        # 连续错误
        mistakes = learn_db.get_mistakes(reviewed=False, limit=20)
        mistake_topics = defaultdict(int)
        for m in mistakes:
            gap = m.get("knowledge_gap_id")
            if gap:
                mistake_topics[gap] += 1

        # 筛选: 掌握度<40% 或 连续错3次以上
        alerts = []
        for w in weak_kps:
            reason = ""
            if w["mastery"] < 30:
                reason = f"掌握度仅 {w['mastery']:.0f}%"
            if w["id"] in mistake_topics and mistake_topics[w["id"]] >= 3:
                reason = f"连续错 {mistake_topics[w['id']]} 次"
            if reason:
                last_reviewed = w.get("last_reviewed", "")
                days_stale = 999
                if last_reviewed:
                    try:
                        days_stale = (date.today() -
                                     date.fromisoformat(last_reviewed)).days
                    except Exception:
                        pass
                alerts.append({
                    "kp_id": w["id"],
                    "title": w["title"],
                    "subject": w.get("subject", ""),
                    "mastery": w["mastery"],
                    "reason": reason,
                    "days_since_review": days_stale,
                    "suggestion": ("🎯 今天就攻克这个！" if days_stale >= 3
                                  else "需要针对性练习"),
                })

        alerts.sort(key=lambda a: (-a["days_since_review"], a["mastery"]))

        # 冲刺检查: 是否有 upcoming 考试 + 弱项重叠
        sprint_alert = ""
        exams = learn_db.get_upcoming_exams(14)
        if exams and alerts:
            exam_subjects = set()
            for e in exams:
                subs = json.loads(e.get("subjects", "[]"))
                exam_subjects.update(subs)
            overlapping = [a for a in alerts if a.get("subject") in exam_subjects]
            if overlapping:
                sprint_alert = (f"⚠️ 冲刺预警: {len(overlapping)} 个弱项在 "
                               f"即将考试范围内！建议立即启动冲刺模式。")

        return {
            "alerts": alerts[:8],
            "total_weak": len(weak_kps),
            "critical_count": len(alerts),
            "sprint_alert": sprint_alert,
        }



# 4. 冲刺模式


class SprintMode:
    """考前强化: 密集训练 + 错题清零 + 模拟考。"""

    @staticmethod
    def activate(exam_id=None) -> dict:
        """激活冲刺模式,返回强化计划。"""
        if exam_id:
            exams = [learn_db.get_exam(exam_id)]
        else:
            exams = learn_db.get_upcoming_exams(14)
        if not exams:
            return {"error": "14天内没有考试,无需冲刺"}

        exam = exams[0]
        exam_date = date.fromisoformat(exam["exam_date"])
        days_left = (exam_date - date.today()).days
        if days_left <= 0:
            return {"error": "考试已过"}

        subjects = json.loads(exam.get("subjects", "[]"))

        # 收集所有弱项
        all_weak = []
        for subj in subjects:
            kps = learn_db.search_knowledge_points(subject=subj, limit=100)
            for kp in kps:
                if kp.get("mastery", 0) < 70:
                    all_weak.append(kp)

        # 收集错题
        mistakes = learn_db.get_mistakes(reviewed=False, limit=50)
        mistake_texts = []
        for m in mistakes[:10]:
            mistake_texts.append(m.get("question", "")[:80])

        # 冲刺策略
        daily_hours = 3 if days_left <= 7 else 2
        strategy = {
            "phase1": {
                "days": f"1-{max(1, days_left-3)}",
                "focus": "逐个攻克薄弱知识点",
                "daily": f"{daily_hours}h, 上午复习+下午刷题+晚上错题",
                "topics": [w["title"] for w in all_weak[:10]],
            },
            "phase2": {
                "days": f"{max(2, days_left-2)}-{days_left-1}",
                "focus": "综合模拟 + 错题清零",
                "daily": f"{daily_hours}h, 上午模拟考+下午分析+晚上速记",
            },
            "phase3": {
                "days": f"{days_left}",
                "focus": "考前冲刺: 公式速览+错题最后一遍",
                "daily": "2h, 快速过公式和错题,早睡",
            },
        }

        return {
            "exam": exam["name"],
            "days_left": days_left,
            "weak_count": len(all_weak),
            "mistake_count": len(mistakes),
            "strategy": strategy,
            "urgent_tasks": [
                f"今天: 攻克 {all_weak[0]['title'] if all_weak else '错题'}",
                "明天: 模拟考1次 + 分析",
                f"每天: {daily_hours}h 学习",
            ],
            "motivation": (
                f"🔥 冲刺模式已激活！{days_left} 天,每天 {daily_hours} 小时,"
                f"攻克 {len(all_weak)} 个弱项,你能做到！"
            ),
        }



# 5. 微学习


class MicroLearning:
    """5分钟碎片化学习片段。"""

    @staticmethod
    def generate(subject="", count=3) -> list:
        """生成微学习片段(适合排队/通勤)。"""
        snippets = []

        # 公式速览
        formulas = learn_db.get_due_formulas(subject, 3)
        for f in formulas:
            snippets.append({
                "type": "formula",
                "duration": "1分钟",
                "content": f"📐 {f['name']}: {f.get('plain_text','')[:60]}",
            })

        # 错题速看
        mistakes = learn_db.get_mistakes(reviewed=False, limit=3)
        for m in mistakes:
            snippets.append({
                "type": "mistake_review",
                "duration": "2分钟",
                "content": f"❌ {m.get('question','')[:80]} → {m.get('answer','')[:50]}",
            })

        # 知识点速记
        if not snippets:
            kps = learn_db.search_knowledge_points(subject=subject, limit=3)
            for kp in kps:
                snippets.append({
                    "type": "knowledge",
                    "duration": "1分钟",
                    "content": f"📖 {kp['title']}: {kp.get('content','')[:80]}",
                })

        return snippets[:count]

    @staticmethod
    def daily_tip() -> str:
        """每日学习技巧。"""
        tips = [
            "💡 学习后立刻回忆一遍,效果是反复阅读的3倍",
            "💡 把学到的内容讲给朋友听,讲不清楚的地方就是没真懂",
            "💡 睡前15分钟快速过一遍今天学的,睡眠会帮你巩固记忆",
            "💡 做错题比做新题更有价值,每道错题都是一个提升机会",
            "💡 25分钟专注+5分钟休息的节奏,比连续学习2小时效率高",
            "💡 用不同颜色的笔标注不同重要度,视觉记忆更强",
            "💡 学完一章后,自己出题考自己,比做别人的题效果好",
            "💡 交叉练习(混着做不同类型的题)比集中练习效果好",
        ]
        import random
        return random.choice(tips)



# 复习方法推荐(根据当前状态)


def recommend_method(subject="", mastery=0, is_new=False,
                     is_stuck=False) -> str:
    """根据学生当前状态推荐最佳学习方法。"""
    import schedule_engine
    methods = schedule_engine.LEARNING_METHODS

    if is_stuck and mastery < 40:
        # 卡住→回到基础
        return (
            f"💡 你在这个问题上卡住了。试试 **{methods['scaffolding']['name']}**: "
            f"{methods['scaffolding']['instruction']} "
            f"然后再用 **{methods['feynman']['name']}**: "
            f"{methods['feynman']['instruction']}")
    elif mastery < 50:
        return (
            f"💡 掌握度偏低。用 **{methods['deliberate_practice']['name']}**: "
            f"{methods['deliberate_practice']['instruction']}")
    elif is_new:
        return (
            f"💡 新内容。用 **{methods['scaffolding']['name']}**: "
            f"{methods['scaffolding']['instruction']}")
    elif mastery >= 70:
        return (
            f"💡 已比较熟练。用 **{methods['interleaving']['name']}**: "
            f"{methods['interleaving']['instruction']}")
    else:
        return (
            f"💡 用 **{methods['active_recall']['name']}**: "
            f"{methods['active_recall']['instruction']}")


from collections import defaultdict



# 6. 错题自动变式


class AutoVariant:
    """每次做错一道题,自动生成2-3道变式题巩固。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def generate_for_mistake(self, mistake_id: int, count=2, model=None) -> list:
        """为一道错题生成变式题。"""
        mistakes = learn_db.get_mistakes(reviewed=False, limit=50)
        target = None
        for m in mistakes:
            if m["id"] == mistake_id:
                target = m
                break
        if not target:
            return [{"error": f"错题 {mistake_id} 不存在"}]

        if not self.call_model:
            return [{"error": "LLM 未配置"}]

        q = target.get("question", "")
        a = target.get("answer", "")
        ua = target.get("user_answer", "")

        prompt = (
            f"学生做错了这道题:\n题目: {q[:500]}\n正确答案: {a[:300]}\n学生答案: {ua[:300]}\n\n"
            f"生成 {count} 道同类型变式题(改数据不改题型):\n"
            "输出 JSON: [{\"question\":\"...\",\"answer\":\"...\",\"difficulty\":2}]\n"
            "第1题最简单(热身),逐渐增加难度。"
        )
        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        try:
            variants = json.loads(content) if content.startswith("[") else []
        except Exception:
            return [{"error": f"生成失败: {content[:200]}"}]

        result = []
        for v in variants:
            ex_id = learn_db.add_exercise(
                knowledge_point_id=target.get("knowledge_gap_id"),
                question=v.get("question", ""),
                answer=v.get("answer", ""),
                difficulty=v.get("difficulty", 2),
                is_mistake=True)
            result.append({"exercise_id": ex_id, "question": v.get("question", "")[:100]})
        return result



# 7. 成就徽章


ACHIEVEMENTS = [
    {"id": "first_study", "name": "初次学习", "desc": "完成第一次学习", "check": lambda s: s["total_sessions"] >= 1},
    {"id": "streak_3", "name": "三天打鱼", "desc": "连续学习3天", "check": lambda s: s["streak"] >= 3},
    {"id": "streak_7", "name": "一周之星", "desc": "连续学习7天", "check": lambda s: s["streak"] >= 7},
    {"id": "streak_30", "name": "月度学霸", "desc": "连续学习30天", "check": lambda s: s["streak"] >= 30},
    {"id": "questions_50", "name": "刷题新手", "desc": "累计做对50题", "check": lambda s: s["total_correct"] >= 50},
    {"id": "questions_200", "name": "刷题达人", "desc": "累计做对200题", "check": lambda s: s["total_correct"] >= 200},
    {"id": "chapter_done", "name": "学完一章", "desc": "完成一个完整章节", "check": lambda s: s["chapters_done"] >= 1},
    {"id": "exam_registered", "name": "目标明确", "desc": "注册了第一场考试", "check": lambda s: s["exams_registered"] >= 1},
    {"id": "formula_50", "name": "公式达人", "desc": "掌握50个公式(mastery≥80)", "check": lambda s: s["formulas_mastered"] >= 50},
    {"id": "perfect_week", "name": "完美一周", "desc": "连续7天每天学习30分钟以上", "check": lambda s: s["perfect_week"]},
    {"id": "all_nighter", "name": "夜猫子", "desc": "在23:00后学习", "check": lambda s: s["night_owl"]},
    {"id": "early_bird", "name": "早起鸟", "desc": "在7:00前学习", "check": lambda s: s["early_bird"]},
    {"id": "exam_ready", "name": "备考就绪", "desc": "考试覆盖度达到80%", "check": lambda s: s["exam_readiness"] >= 80},
]


class AchievementSystem:
    """成就徽章检测和授予。"""

    @staticmethod
    def check_all() -> dict:
        """检测所有成就,返回已获得和未获得的。"""
        import learn_db
        import learner_profile

        # 收集统计数据
        profile = learner_profile.load_profile()
        summary = learn_db.get_progress_summary(365)
        stats = learn_db.get_stats()

        streak = profile.get("behavior", {}).get("consecutive_days", 0)
        total_correct = sum(s["accuracy"] * s["total_ex"] / 100
                           for s in summary if s["total_ex"] > 0)
        chapters_done = 0
        courses = learn_db.list_courses()
        for c in courses:
            chapters_done += c.get("completed_kps", 0) // 5  # 约5知识点=1章
        exams = learn_db.list_exams()
        formulas = learn_db.search_formulas(limit=500)
        formulas_mastered = sum(1 for f in formulas if f.get("mastery", 0) >= 80)

        # 考试准备度
        exam_readiness = 0
        for e in exams:
            cov = learn_db.get_exam_coverage(e["id"])
            exam_readiness = max(exam_readiness, cov.get("coverage_pct", 0))

        # 完美一周
        perfect_week = False
        if len(summary) >= 7:
            last7 = summary[-7:]
            perfect_week = all(s["total_minutes"] >= 30 for s in last7)

        # 时间检测
        import datetime
        now = datetime.datetime.now()
        night_owl = now.hour >= 23
        early_bird = now.hour < 7

        check_data = {
            "total_sessions": len(summary),
            "streak": streak,
            "total_correct": int(total_correct),
            "chapters_done": chapters_done,
            "exams_registered": len(exams),
            "formulas_mastered": formulas_mastered,
            "perfect_week": perfect_week,
            "night_owl": night_owl,
            "early_bird": early_bird,
            "exam_readiness": exam_readiness,
        }

        earned = []
        locked = []
        for ach in ACHIEVEMENTS:
            if ach["check"](check_data):
                earned.append(ach)
            else:
                locked.append(ach)

        return {
            "earned": earned,
            "locked": locked[:8],
            "total": len(ACHIEVEMENTS),
            "progress_pct": round(100 * len(earned) / len(ACHIEVEMENTS), 1),
        }



# 8. 周报生成


class WeeklyReport:
    """自动生成学习周报。"""

    @staticmethod
    def generate(call_model=None, model=None) -> str:
        """生成本周学习报告。"""
        import learn_db
        summary = learn_db.get_progress_summary(7)
        if not summary:
            return "本周尚无学习记录。开始你的第一次学习吧！"

        total_min = sum(s["total_minutes"] for s in summary)
        total_ex = sum(s["total_ex"] for s in summary)
        total_ok = sum(s["accuracy"] * s["total_ex"] / 100
                       for s in summary if s["total_ex"] > 0 and s.get("accuracy"))
        acc = round(100 * total_ok / max(1, total_ex), 1)
        weak = learn_db.get_weak_topics(top_n=5)
        stats = learn_db.get_stats()
        ach = AchievementSystem.check_all()

        data = (
            f"本周学习 {total_min} 分钟, {total_ex} 题, 正确率 {acc}%\n"
            f"知识库: {stats['total_knowledge_points']} 知识点, "
            f"{stats['total_formulas']} 公式, {stats['total_exercises']} 题\n"
            f"未复习错题: {stats['unreviewed_mistakes']}\n"
            f"成就: {len(ach['earned'])}/{ach['total']} 已解锁\n"
        )

        if not call_model:
            return data

        prompt = (
            "你是学习周报生成器。生成简洁的一周学习总结(适合手表屏幕):\n"
            + data + "\n"
            "输出格式:\n"
            "**📊 本周**: [3句话总结]\n"
            "**🎯 亮点**: [1句话]\n"
            "**⚠️ 需改进**: [1句话]\n"
            "**💡 下周建议**: [1句话]"
        )
        content = (call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        return content or data

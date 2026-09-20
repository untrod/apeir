# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 考试管理 + 自适应规划 + 内容分析。

核心能力:
  1. 考试注册 — 考试名称/日期/科目/范围
  2. 倒计时仪表盘 — 距考试 N 天, 每科准备进度
  3. 自适应学习计划 — 基于考试日期 + 知识缺口的每日计划
  4. 考纲分析 — 对比考纲范围与已有知识库,找出缺口
  5. 学习建议 — AI 根据弱项 + 考试优先级给出建议

设计原则:
  - LLM 调用通过回调注入
  - 所有数据持久化到 learn_db
"""

import json
import logging
from datetime import date

import learn_db

log = logging.getLogger("study_planner")



# 考试管理器


class ExamManager:
    """考试注册 + 倒计时 + 准备度追踪。"""

    def add_exam(self, name, exam_date, subjects=None,
                 scope="", target_score="", notes="") -> int:
        """注册一场考试,返回 exam_id。"""
        return learn_db.add_exam(name, exam_date, subjects, scope, target_score, notes)

    def get_dashboard(self) -> dict:
        """考试仪表盘: 所有 upcoming 考试 + 倒计时 + 准备度。"""
        exams = learn_db.get_upcoming_exams(365)
        dashboard = []
        today = date.today()
        for e in exams:
            exam_date = date.fromisoformat(e["exam_date"])
            days_left = (exam_date - today).days
            coverage = learn_db.get_exam_coverage(e["id"])
            # 紧急度
            if days_left <= 7:
                urgency = "🔴 紧急"
            elif days_left <= 30:
                urgency = "🟡 注意"
            elif days_left <= 90:
                urgency = "🟢 正常"
            else:
                urgency = "🔵 远期"

            subjects = json.loads(e.get("subjects", "[]"))
            dashboard.append({
                "id": e["id"],
                "name": e["name"],
                "date": e["exam_date"],
                "days_left": days_left,
                "urgency": urgency,
                "subjects": subjects,
                "target_score": e.get("target_score", ""),
                "coverage": coverage["coverage_pct"],
                "topics_covered": coverage["covered"],
                "topics_total": coverage["total_topics"],
                "status": e.get("status", "upcoming"),
            })
        return {
            "exams": sorted(dashboard, key=lambda x: x["days_left"]),
            "total": len(dashboard),
            "urgent_count": sum(1 for d in dashboard if d["days_left"] <= 7),
        }

    def get_exam_detail(self, exam_id: int) -> dict:
        """单个考试的详细状态。"""
        e = learn_db.get_exam(exam_id)
        if not e:
            return {"error": f"考试 ID {exam_id} 不存在"}
        today = date.today()
        exam_date = date.fromisoformat(e["exam_date"])
        days_left = (exam_date - today).days
        coverage = learn_db.get_exam_coverage(exam_id)
        subjects = json.loads(e.get("subjects", "[]"))
        gaps = learn_db.list_content_gaps(exam_id, covered=False)
        plans = learn_db.get_active_plans()

        # 每科的准备度
        subject_progress = {}
        for subj in (subjects if subjects else [e.get("scope", "")]):
            kps = learn_db.search_knowledge_points(subject=subj, limit=1000)
            if kps:
                avg_m = sum(kp.get("mastery", 0) for kp in kps) / len(kps)
                subject_progress[subj] = {
                    "kps": len(kps),
                    "avg_mastery": round(avg_m, 1),
                    "weak_count": sum(1 for kp in kps if kp.get("mastery", 0) < 60),
                }

        # 每日建议学习量
        if days_left > 0 and gaps:
            daily_topics = max(1, len(gaps) // days_left)
            daily_exercises = daily_topics * 3
        else:
            daily_topics = 0
            daily_exercises = 0

        return {
            "id": e["id"],
            "name": e["name"],
            "date": e["exam_date"],
            "days_left": days_left,
            "subjects": subjects,
            "scope": e.get("scope", ""),
            "target_score": e.get("target_score", ""),
            "coverage": coverage,
            "subject_progress": subject_progress,
            "uncovered_gaps": [g for g in gaps[:10]],
            "daily_recommendation": {
                "topics_per_day": daily_topics,
                "exercises_per_day": daily_exercises,
                "total_gaps": len(gaps),
            },
            "active_plans": plans[:5],
        }



# 自适应规划器


class AdaptivePlanner:
    """
    根据考试日期 + 知识缺口 + 掌握度, 生成自适应学习计划。

    算法:
      1. 找最近的 upcoming 考试
      2. 计算剩余天数
      3. 列出所有未掌握的知识点(按 priority 排序)
      4. 分配: 弱项优先, 每天 N 个知识点
      5. 留 buffer: 考前 3 天只复习
    """

    def __init__(self, call_model=None):
        self.call_model = call_model

    def generate(self, exam_id=None, available_days=30,
                 minutes_per_day=60, model=None) -> dict:
        """
        生成自适应学习计划。

        如果指定 exam_id, 以该考试为目标。
        否则以最早 upcoming 考试为目标。
        """
        if exam_id:
            exams = [learn_db.get_exam(exam_id)]
        else:
            exams = learn_db.get_upcoming_exams(365)

        if not exams:
            return {"error": "没有 upcoming 考试。先用 learn_add_exam 注册考试。"}

        exam = exams[0]
        today = date.today()
        exam_date = date.fromisoformat(exam["exam_date"])
        total_days = (exam_date - today).days
        if total_days <= 0:
            return {"error": f"考试 {exam['name']} 已过期或就在今天"}

        days = min(total_days, available_days)
        subjects = json.loads(exam.get("subjects", "[]"))
        gaps = learn_db.list_content_gaps(exam["id"], covered=False)

        # 如果没有 gap 记录,从知识库中找薄弱项
        if not gaps:
            for subj in subjects:
                weak = learn_db.get_weak_topics(subj, 10)
                for w in weak:
                    gaps.append({
                        "id": w.get("id"), "topic": w.get("title"),
                        "subject": subj, "priority": max(1, 5 - int(w.get("mastery", 0) / 20)),
                        "mastery": w.get("mastery", 0),
                    })

        if not gaps:
            # 完全没有数据: 建议先学基础知识
            return {
                "name": f"{exam['name']} 备考计划",
                "total_days": days,
                "exam_date": exam["exam_date"],
                "tasks": [{
                    "day": 1, "task": "上传教材并提取知识点",
                    "type": "setup", "duration": 15,
                }],
                "focus": "请先上传相关科目的课本/讲义",
            }

        # 按 priority 降序排序(缺口越急越先学)
        gaps.sort(key=lambda x: (-x.get("priority", 3), x.get("mastery", 0)))

        # 分配: 前 N-3 天学新内容, 后 3 天复习
        learn_days = max(1, days - 3)
        review_days = min(3, days)
        topics_per_day = max(1, len(gaps) // learn_days)

        tasks = []
        for day in range(1, days + 1):
            if day <= learn_days:
                start_idx = (day - 1) * topics_per_day
                day_gaps = gaps[start_idx:start_idx + topics_per_day]
                for g in day_gaps:
                    tasks.append({
                        "day": day,
                        "task": f"学习 {g.get('topic','')}",
                        "type": "learn",
                        "subject": g.get("subject", ""),
                        "duration": minutes_per_day // max(1, len(day_gaps)),
                        "gap_id": g.get("id"),
                        "priority": g.get("priority", 3),
                    })
                # 每日练习题
                tasks.append({
                    "day": day,
                    "task": f"做 {len(day_gaps)*3} 道练习题",
                    "type": "practice",
                    "duration": 20,
                })
            else:
                tasks.append({
                    "day": day,
                    "task": "综合复习 + 错题重做",
                    "type": "review",
                    "duration": 30,
                })
                tasks.append({
                    "day": day,
                    "task": "模拟考试(限时)",
                    "type": "mock_exam",
                    "duration": 60,
                })

        # 保存计划
        plan_id = learn_db.add_study_plan(
            name=f"{exam['name']} 备考计划",
            plan_type="exam_prep",
            start_date=today.isoformat(),
            end_date=exam_date.isoformat(),
            exam_id=exam["id"],
            tasks=tasks,
            auto_generated=True)

        # 计算每日时间分配
        daily_breakdown = {}
        for t in tasks:
            d = t["day"]
            if d not in daily_breakdown:
                daily_breakdown[d] = 0
            daily_breakdown[d] += t.get("duration", 0)

        return {
            "plan_id": plan_id,
            "name": f"{exam['name']} 备考计划",
            "total_days": days,
            "exam_date": exam["exam_date"],
            "topics_count": len(gaps),
            "daily_breakdown": daily_breakdown,
            "tasks": tasks[:30],  # 返回前30项概要
            "focus": f"距离考试 {days} 天, 每天约 {minutes_per_day} 分钟",
            "strategy": (
                f"前 {learn_days} 天系统学习({topics_per_day} 个知识点/天), "
                f"后 {review_days} 天集中复习和模拟考试"),
        }



# 考纲分析器


class SyllabusAnalyzer:
    """
    对比考纲范围与已有知识库, 找出缺口。

    输入: 考纲文本(考试范围描述)
    输出: 缺口清单(哪些考纲内容在知识库中缺失/薄弱)
    """

    def __init__(self, call_model=None):
        self.call_model = call_model

    def analyze(self, exam_id: int, syllabus_text="", model=None) -> dict:
        """
        分析考纲 vs 知识库的差距。

        如果 syllabus_text 为空, 从 exam.scope 读取。
        """
        exam = learn_db.get_exam(exam_id)
        if not exam:
            return {"error": f"考试 ID {exam_id} 不存在"}

        scope = syllabus_text or exam.get("scope", "")
        if not scope:
            return {"error": "考试未设定范围(scope)。请先填写考纲范围。"}

        subjects = json.loads(exam.get("subjects", "[]"))

        # 收集已有知识库
        existing = []
        for subj in (subjects if subjects else exam.get("scope", "").split(",")):
            kps = learn_db.search_knowledge_points(subject=subj.strip(), limit=200)
            for kp in kps:
                existing.append({
                    "title": kp["title"],
                    "subject": kp["subject"],
                    "mastery": kp["mastery"],
                    "chapter": kp.get("chapter", ""),
                })

        existing_text = "\n".join(
            f"- [{e['subject']}] {e['chapter']}/{e['title']} (掌握{e['mastery']:.0f}%)"
            for e in existing[:50])

        prompt = (
            f"你是考纲分析专家。对比考纲范围和已有知识库,找出缺口。\n\n"
            f"**考试**: {exam['name']}\n"
            f"**日期**: {exam['exam_date']}\n"
            f"**考纲范围**:\n{scope[:2000]}\n\n"
            f"**已有知识库**:\n{existing_text or '(空)'}\n\n"
            "请分析并输出 JSON(不要 markdown 代码块):\n"
            '{\n'
            '  "gap_analysis": "总体分析(1-2句)",\n'
            '  "gaps": [\n'
            '    {"topic": "缺失的知识点","subject": "科目","priority": 3,"reason": "为什么重要"}\n'
            '  ],\n'
            '  "strengths": ["已有优势领域"],\n'
            '  "recommendation": "备考建议(1-2句)"\n'
            '}\n\n'
            "priority: 1边缘 2一般 3重要 4核心 5必考\n"
            "最多列15个缺口,按 priority 降序。"
        )

        if not self.call_model:
            return {"error": "LLM 未配置"}

        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        result = self._parse_json(content)

        # 入库缺口
        gaps_added = 0
        for g in result.get("gaps", []):
            learn_db.add_content_gap(
                exam_id=exam_id,
                subject=g.get("subject", exam.get("scope", "")),
                topic=g.get("topic", ""),
                priority=g.get("priority", 3),
                notes=g.get("reason", ""))
            gaps_added += 1

        return {
            "analysis": result.get("gap_analysis", ""),
            "gaps_added": gaps_added,
            "gaps": result.get("gaps", [])[:10],
            "strengths": result.get("strengths", []),
            "recommendation": result.get("recommendation", ""),
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            for part in text.split("```"):
                part = part.strip()
                if part.startswith("{") or part.startswith("json"):
                    if part.startswith("json"):
                        part = part[4:]
                    try:
                        return json.loads(part)
                    except Exception:
                        pass
        try:
            return json.loads(text)
        except Exception:
            pass
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                pass
        return {}



# AI 学习建议引擎


class StudyAdvisor:
    """综合当前状态, 给用户 AI 学习建议。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def advise(self, model=None) -> str:
        """综合建议: 考试优先 + 弱项 + 每日可执行的动作。"""
        exams = learn_db.get_upcoming_exams(90)
        weak = learn_db.get_weak_topics(top_n=8)
        stats = learn_db.get_stats()
        today_progress = learn_db.get_today_progress()
        summary = learn_db.get_progress_summary(7)

        data = []
        # 考试
        if exams:
            data.append("## 即将考试")
            for e in exams[:3]:
                days = (date.fromisoformat(e["exam_date"]) - date.today()).days
                cov = learn_db.get_exam_coverage(e["id"])
                data.append(f"- {e['name']}: {e['exam_date']} (倒计时 {days} 天)")
                data.append(f"  覆盖度: {cov['coverage_pct']}%, 缺口: {cov['uncovered']} 个")
        else:
            data.append("## 无 upcoming 考试")

        # 弱项
        if weak:
            data.append("\n## 薄弱环节")
            for w in weak[:5]:
                data.append(f"- {w['title']} ({w['subject']}) — 掌握 {w['mastery']:.0f}%")

        # 今日
        today_min = sum(p.get("study_minutes", 0) for p in today_progress)
        today_ex = sum(p.get("exercises_done", 0) for p in today_progress)
        data.append(f"\n## 今日进度: {today_min}分钟, {today_ex}题")

        # 7天趋势
        if len(summary) > 1:
            data.append(f"7天趋势: {summary[0]['total_ex']}→{summary[-1]['total_ex']} 题/天")

        prompt = (
            "你是学习顾问。基于用户数据,给出一个简洁的建议报告。\n\n"
            + "\n".join(data) + "\n\n"
            "输出格式:\n"
            "**🎯 优先级**: [一句话 - 今天最该做什么]\n"
            "**📋 建议任务**:\n"
            "1. [具体任务 含时长]\n"
            "2. ...\n"
            "**💡 备考提示**: [如果有即将考试,给针对建议]\n"
            "**📊 趋势**: [一句话评价学习趋势]\n\n"
            "直接输出,不要 JSON,不要寒暄。"
        )

        if not self.call_model:
            return "\n".join(data)
        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        return content or "\n".join(data)



# 便捷函数


_exam_mgr = None
_planner = None
_syllabus_analyzer = None
_advisor = None


def get_exam_manager():
    global _exam_mgr
    if not _exam_mgr:
        _exam_mgr = ExamManager()
    return _exam_mgr


def get_planner(call_model=None):
    global _planner
    if not _planner:
        _planner = AdaptivePlanner(call_model)
    return _planner


def get_syllabus_analyzer(call_model=None):
    global _syllabus_analyzer
    if not _syllabus_analyzer:
        _syllabus_analyzer = SyllabusAnalyzer(call_model)
    return _syllabus_analyzer


def get_advisor(call_model=None):
    global _advisor
    if not _advisor:
        _advisor = StudyAdvisor(call_model)
    return _advisor

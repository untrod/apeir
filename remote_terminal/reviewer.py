# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — AI 每日复盘 + 进度分析 + 计划生成。

核心功能:
  1. 每日复盘 — 总结今日学了什么、弱项在哪、给出建议
  2. 进度趋势 — N 天内的掌握度变化、做题量/正确率曲线
  3. 计划生成 — 基于弱项自动生成明天的学习任务
  4. 知识断点诊断 — 分析错题找出根因知识点

设计原则:
  - LLM 调用通过回调注入
  - 输出可直接用于手表消息推送
"""

import json
import logging
import time

import learn_db

log = logging.getLogger("reviewer")



# 每日复盘引擎


_REVIEW_PROMPT = (
    "你是学习复盘专家。根据以下数据,生成一份简洁的学习总结。\n\n"
    "## 数据\n"
    "{data}\n\n"
    "## 要求\n"
    "用简洁中文输出,分为5个区块(每块1-2句话):\n"
    "1. **今日回顾**: 学了什么,做了多少题,正确率\n"
    "2. **薄弱环节**: 哪些知识点/公式掌握不牢(具体到名字)\n"
    "3. **进步亮点**: 相比之前有没有进步(如果数据显示)\n"
    "4. **明日建议**: 明天重点复习什么,建议做多少题\n"
    "5. **一句话**: 给用户一句鼓励或提醒\n\n"
    "直接输出,不要 JSON,不要寒暄。"
)


class DailyReviewer:
    """生成每日学习复盘。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def review(self, model=None) -> str:
        """
        生成今日复盘。
        包含: 学习量、正确率、弱项 Top5、进步趋势、明日建议。
        """
        today = time.strftime("%Y-%m-%d")
        stats = learn_db.get_stats()
        today_progress = learn_db.get_today_progress()
        weak = learn_db.get_weak_topics(top_n=8)
        summary = learn_db.get_progress_summary(7)  # 最近7天

        # 构建数据
        data_parts = [f"日期: {today}"]

        # 今日数据
        today_min = sum(p.get("study_minutes", 0) for p in today_progress)
        today_ex = sum(p.get("exercises_done", 0) for p in today_progress)
        today_ok = sum(p.get("exercises_correct", 0) for p in today_progress)
        today_acc = f"{100 * today_ok / today_ex:.1f}%" if today_ex > 0 else "N/A"
        data_parts.append(
            f"今日: {today_min}分钟, {today_ex}题, 正确率{today_acc}")

        # 总数据
        data_parts.append(
            f"知识库: {stats['total_knowledge_points']}知识点, "
            f"{stats['total_formulas']}公式, {stats['total_exercises']}题")

        # 薄弱项
        if weak:
            data_parts.append("薄弱知识点:")
            for w in weak:
                data_parts.append(
                    f"  - [{w['id']}] {w['title']} ({w['subject']}) "
                    f"掌握{w['mastery']:.0f}% 复习{w['review_count']}次 "
                    f"上次:{w['last_reviewed'] or '从未'}")

        # 7天趋势
        if len(summary) > 1:
            early = summary[0]
            late = summary[-1]
            data_parts.append(
                f"7天趋势: {early['total_ex']}→{late['total_ex']}题/天, "
                f"正确率 {early['accuracy']}%→{late['accuracy']}%")

        # 未复习错题
        from learn_db import get_mistakes
        mistakes = get_mistakes(reviewed=False, limit=5)
        if mistakes:
            data_parts.append("未复习错题:")
            for m in mistakes:
                data_parts.append(
                    f"  - [{m.get('exercise_id','')}] {m.get('question','')[:80]} "
                    f"→ {m.get('kp_title','')}")

        if not self.call_model:
            return "\n".join(data_parts)

        prompt = _REVIEW_PROMPT.format(data="\n".join(data_parts))
        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        return content or "\n".join(data_parts)

    def review_weekly(self, model=None) -> str:
        """生成周报(7天汇总+趋势)。"""
        summary = learn_db.get_progress_summary(7)
        if not summary:
            return "本周尚无学习记录。"

        total_min = sum(s["total_minutes"] for s in summary)
        total_ex = sum(s["total_ex"] for s in summary)
        total_ok = sum(s["total_ex"] * s["accuracy"] / 100 for s in summary
                       if s["total_ex"] > 0 and s.get("accuracy"))
        avg_acc = f"{100 * total_ok / total_ex:.1f}%" if total_ex > 0 else "N/A"

        weak = learn_db.get_weak_topics(top_n=10)
        stats = learn_db.get_stats()

        data = (
            f"本周学习 {total_min} 分钟, {total_ex} 题, 平均正确率 {avg_acc}\n"
            f"知识库总量: {stats['total_knowledge_points']} 知识点, "
            f"{stats['total_formulas']} 公式\n"
            f"未复习错题: {stats['unreviewed_mistakes']}\n\n"
            f"薄弱项 Top 10:\n" +
            "\n".join(f"  [{w['id']}] {w['title']} ({w['subject']}) "
                      f"掌握{w['mastery']:.0f}%" for w in weak)
        )

        prompt = (
            "你是学习周报专家。生成一份简洁的每周学习总结。\n"
            "包含: 总览、薄弱趋势、亮点、下周建议、一句鼓励。\n\n"
            f"{data}"
        )

        if not self.call_model:
            return data
        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        return content or data



# 计划生成器


class PlanGenerator:
    """根据进度和弱项,自动生成明日学习计划。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def generate_tomorrow_plan(self, available_minutes=60, model=None) -> dict:
        """
        生成明日计划。
        available_minutes: 用户可用时间
        返回: {"tasks": [...], "focus": "...", "tip": "..."}
        """
        today = time.strftime("%Y-%m-%d")
        weak = learn_db.get_weak_topics(top_n=10)
        due_fm = learn_db.get_due_formulas(limit=10)
        mistakes = learn_db.get_mistakes(reviewed=False, limit=10)
        summary = learn_db.get_progress_summary(14)

        if not weak:
            return {
                "tasks": [{"task": "查看文档库", "duration": 15, "type": "explore"}],
                "focus": "知识库尚无数据,请先上传课本或讲义",
                "tip": "用 learn_upload_doc 上传教材开始学习之旅"
            }

        # 策略: 60% 时间给弱项, 25% 复习公式, 15% 新学
        review_time = int(available_minutes * 0.6)
        formula_time = int(available_minutes * 0.25)
        new_time = available_minutes - review_time - formula_time

        tasks = []

        # 弱项复习(每个约15分钟)
        review_slots = max(1, review_time // 15)
        for w in weak[:review_slots]:
            tasks.append({
                "task": f"复习 {w['title']}",
                "kp_id": w["id"],
                "subject": w.get("subject", ""),
                "duration": 15,
                "type": "review",
                "reason": f"掌握度仅 {w['mastery']:.0f}%",
            })

        # 公式复习(每个约5分钟)
        fm_slots = min(len(due_fm), formula_time // 5)
        for f in due_fm[:fm_slots]:
            tasks.append({
                "task": f"公式复习: {f['name']}",
                "formula_id": f["id"],
                "duration": 5,
                "type": "formula_review",
                "reason": "到期复习",
            })

        # 新学建议
        if new_time >= 10:
            tasks.append({
                "task": "学习新章节(根据当前进度)",
                "duration": new_time,
                "type": "new_learn",
            })

        focus = f"重点攻克 {weak[0]['title']}({weak[0]['subject']})"
        tip = ("先复习再做题。做对的题可以加快进度,做错的题建议分析原因"
               if mistakes else "今天先完成复习任务,有余力再继续推进新内容")

        return {
            "tasks": tasks,
            "focus": focus,
            "tip": tip,
            "weak_count": len(weak),
            "mistake_count": len(mistakes),
            "generated_at": today,
        }



# 知识断点诊断


class GapDiagnoser:
    """
    分析错题,找出根因知识断点。

    不是简单说"这个知识点没掌握",而是追溯前置依赖:
    如果链式法则总是错,可能是基本求导法则没掌握。
    """

    def __init__(self, call_model=None):
        self.call_model = call_model

    def diagnose(self, mistake_id: int, model=None) -> dict:
        """诊断一个错题,返回根因分析和建议。"""
        from learn_db import get_mistakes as gm
        mistakes = gm(reviewed=False, limit=50)
        target = None
        for m in mistakes:
            if m["id"] == mistake_id:
                target = m
                break
        if not target:
            return {"error": f"错题 ID {mistake_id} 不存在"}

        # 获取关联知识点的前置依赖
        gap_id = target.get("knowledge_gap_id")
        prereqs = []
        if gap_id:
            kp = learn_db.get_knowledge_point(gap_id)
            if kp:
                prereqs = json.loads(kp.get("prerequisites", "[]"))
                title = kp["title"]
        else:
            title = "未知知识点"

        prompt = (
            f"你是学习诊断专家。分析以下错题,找出根因:\n\n"
            f"题目: {target.get('question','')[:300]}\n"
            f"正确答案: {target.get('answer','')[:200]}\n"
            f"用户答案: {target.get('user_answer','')[:200]}\n"
            f"关联知识点: {title}\n"
            f"前置依赖: {prereqs}\n\n"
            "输出 JSON:\n"
            '{\n'
            '  "root_cause": "根因(一句话)",\n'
            '  "gap_type": "concept_gap|calculation_error|misread|prerequisite_gap",\n'
            '  "should_review": ["建议复习的知识点(具体到名)"],\n'
            '  "advice": "给用户的建议(1-2句)"\n'
            '}'
        )

        if not self.call_model:
            return {"error": "LLM 未配置"}

        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        try:
            from doc_engine import _extract_json as _ej
            return _ej(content)
        except Exception:
            return {"raw": content[:500]}



# 进度趋势分析


class TrendAnalyzer:
    """分析掌握度趋势,生成可视化数据。"""

    @staticmethod
    def mastery_curve(days=30) -> dict:
        """返回 N 天内的平均 mastery 变化。"""
        summary = learn_db.get_progress_summary(days)
        dates = []
        accuracy_vals = []
        ex_counts = []
        for s in summary:
            dates.append(s["date"])
            accuracy_vals.append(s.get("accuracy", 0))
            ex_counts.append(s.get("total_ex", 0))
        return {
            "dates": dates,
            "accuracy": accuracy_vals,
            "exercise_counts": ex_counts,
            "trend": "up" if len(accuracy_vals) > 1 and accuracy_vals[-1] > accuracy_vals[0]
                     else "down" if len(accuracy_vals) > 1 else "flat",
        }

    @staticmethod
    def subject_breakdown() -> list:
        """按科目统计掌握度分布。"""
        from learn_db import search_knowledge_points as skp
        subjects = {}
        all_kps = skp(limit=1000)
        for kp in all_kps:
            subj = kp.get("subject", "other")
            if subj not in subjects:
                subjects[subj] = {"count": 0, "total_mastery": 0, "high": 0, "low": 0}
            m = kp.get("mastery", 0)
            subjects[subj]["count"] += 1
            subjects[subj]["total_mastery"] += m
            if m >= 70:
                subjects[subj]["high"] += 1
            else:
                subjects[subj]["low"] += 1
        result = []
        for subj, data in subjects.items():
            result.append({
                "subject": subj,
                "count": data["count"],
                "avg_mastery": round(data["total_mastery"] / max(1, data["count"]), 1),
                "mastered": data["high"],
                "weak": data["low"],
            })
        return sorted(result, key=lambda x: x["avg_mastery"])



# 便捷函数


_reviewer = None
_plan_gen = None
_diagnoser = None


def get_reviewer(call_model=None):
    global _reviewer
    if not _reviewer:
        _reviewer = DailyReviewer(call_model)
    return _reviewer


def get_plan_generator(call_model=None):
    global _plan_gen
    if not _plan_gen:
        _plan_gen = PlanGenerator(call_model)
    return _plan_gen


def get_diagnoser(call_model=None):
    global _diagnoser
    if not _diagnoser:
        _diagnoser = GapDiagnoser(call_model)
    return _diagnoser

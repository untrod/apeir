# -*- coding: utf-8 -*-
"""
学习计划管理 —— 备考规划 / 每日任务 / 打卡 / 出题 / 学习总结。

设计原则:
  - 计划与记录落盘 study_plans.json + study_logs/YYYY-MM-DD.md,brain 重启不丢。
  - LLM 调用由 brain.py 注入(call_model 回调),本模块不直接依赖 brain,避免循环引用。
  - 一个用户一个 active 计划;支持多科目、每日分配、定时提醒。

数据结构(study_plans.json):
  {
    "active": {
      "goal": "Example Study Goal",
      "deadline": "2026-12-31",
      "start_date": "2026-01-01",
      "subjects": ["Subject A","Subject B","Subject C","Subject D"],
      "daily_plan": {"英语": "每天背50词+1篇阅读", ...},
      "reminders": [{"time":"20:00","text":"刷单词","subject":"英语"}],
      "checkins": {"2026-06-21": {"done": [...], "note": "..."}},
      "created": 1750000000
    }
  }
"""

import json
import os
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
_PLANS_FILE = os.path.join(_DIR, "study_plans.json")
_LOGS_DIR = os.path.join(_DIR, "study_logs")


# 持久化
def _load() -> dict:
    try:
        with open(_PLANS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data: dict):
    with open(_PLANS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_plan() -> dict:
    """获取当前激活的学习计划。无则返回 {}。"""
    return _load().get("active", {})


# 创建计划
def create_plan(goal: str, deadline: str, subjects: list, extra: str, call_model) -> dict:
    """
    用 LLM 根据目标+截止日期+科目生成每日分配 + 提醒。
    call_model(convo, model, use_tools) -> assistant message dict。
    返回创建好的计划 dict。
    """
    start = time.strftime("%Y-%m-%d")
    days_left = _days_between(start, deadline)
    subjects_str = "、".join(subjects) if subjects else "(未指定)"

    prompt = (
        "你是备考规划专家。根据用户的目标,生成一份可执行的每日学习计划。\n"
        f"目标: {goal}\n"
        f"开始日期: {start}\n"
        f"截止日期: {deadline}(还剩约 {days_left} 天)\n"
        f"科目: {subjects_str}\n"
        f"补充说明: {extra or '无'}\n\n"
        "请只输出 JSON,格式严格如下(不要 markdown 代码块,不要多余文字):\n"
        '{\n'
        '  "daily_plan": {"科目名": "每天具体任务量,如:背50词+1篇阅读", ...},\n'
        '  "reminders": [{"time": "20:00", "text": "提醒内容", "subject": "科目"}, ...],\n'
        '  "milestones": ["阶段目标1", "阶段目标2"],\n'
        '  "advice": "一段简短备考建议"\n'
        '}\n'
        "要求:任务量要符合剩余天数,科学分配(前期打基础、后期刷题冲刺);"
        "提醒时间贴合学生作息(晚上为主);milestones 给 2-4 个阶段性检查点。"
    )
    convo = [{"role": "user", "content": prompt}]
    content = (call_model(convo, None, False).get("content") or "").strip()
    parsed = _parse_json(content)

    plan = {
        "goal": goal,
        "deadline": deadline,
        "start_date": start,
        "subjects": subjects,
        "daily_plan": parsed.get("daily_plan", {}),
        "reminders": parsed.get("reminders", []),
        "milestones": parsed.get("milestones", []),
        "advice": parsed.get("advice", ""),
        "checkins": {},
        "created": time.time(),
    }
    data = _load()
    data["active"] = plan
    _save(data)
    return plan


# 打卡
def checkin(done: list, note: str) -> dict:
    """记录今日完成项。done 是完成的任务列表,note 是备注。"""
    data = _load()
    plan = data.get("active")
    if not plan:
        return {"ok": False, "error": "尚无学习计划,请先创建"}
    today = time.strftime("%Y-%m-%d")
    plan.setdefault("checkins", {})[today] = {
        "done": done, "note": note, "ts": time.time(),
    }
    _save(data)
    return {"ok": True, "date": today, "done": done}


def get_today_tasks() -> dict:
    """获取今日任务 + 完成状态。"""
    plan = get_plan()
    if not plan:
        return {"has_plan": False}
    today = time.strftime("%Y-%m-%d")
    checkin_today = plan.get("checkins", {}).get(today, {})
    return {
        "has_plan": True,
        "goal": plan.get("goal", ""),
        "deadline": plan.get("deadline", ""),
        "days_left": _days_between(today, plan.get("deadline", today)),
        "daily_plan": plan.get("daily_plan", {}),
        "reminders": plan.get("reminders", []),
        "done_today": checkin_today.get("done", []),
        "checked_in": bool(checkin_today),
    }


# 出题
def quiz(subject: str, qtype: str, count: int, call_model) -> str:
    """根据科目出题。qtype 如 '单词'/'选择题'/'例句'/'概念'。"""
    plan = get_plan()
    goal = plan.get("goal", "Study Plan") if plan else "Study Plan"
    count = max(1, min(count or 5, 20))
    prompt = (
        f"你是 {goal} 的辅导老师。请就科目「{subject}」出 {count} 道「{qtype}」类型的练习题。\n"
        "每题给出题目,并在最后统一附上参考答案与简要解析。\n"
        "用 Markdown 格式,题目编号清晰。难度适应用户当前水平。"
    )
    convo = [{"role": "user", "content": prompt}]
    return (call_model(convo, None, False).get("content") or "").strip()


# 学习总结
def daily_summary(date: str, conversation_text: str, call_model) -> str:
    """
    用 LLM 对当天的对话内容生成学习总结,并追加到 study_logs/YYYY-MM-DD.md。
    conversation_text 是当天与助手的问答合并文本。
    """
    plan = get_plan()
    goal = plan.get("goal", "") if plan else ""
    today_checkin = plan.get("checkins", {}).get(date, {}) if plan else {}

    prompt = (
        "你在为一名备考学生整理当天的学习总结。基于以下材料,用简洁中文输出:\n"
        "1. 今天学了什么(知识点清单)\n"
        "2. 掌握情况 / 易错点\n"
        "3. 明日建议\n"
        "不要寒暄,直接给要点。\n\n"
        f"【备考目标】{goal}\n"
        f"【今日打卡】完成: {today_checkin.get('done', [])};备注: {today_checkin.get('note', '')}\n"
        f"【今日问答记录】\n{conversation_text[:6000] or '(无对话记录)'}"
    )
    convo = [{"role": "user", "content": prompt}]
    summary = (call_model(convo, None, False).get("content") or "").strip()

    # 落盘
    os.makedirs(_LOGS_DIR, exist_ok=True)
    path = os.path.join(_LOGS_DIR, f"{date}.md")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 学习总结 {date}\n\n{summary}\n")
    except Exception:
        pass
    return summary


def list_summaries(limit: int = 30) -> list:
    """列出历史学习总结文件(按日期倒序)。"""
    if not os.path.isdir(_LOGS_DIR):
        return []
    files = [f for f in os.listdir(_LOGS_DIR) if f.endswith(".md")]
    files.sort(reverse=True)
    out = []
    for fn in files[:limit]:
        try:
            with open(os.path.join(_LOGS_DIR, fn), encoding="utf-8") as f:
                out.append({"date": fn[:-3], "content": f.read()})
        except Exception:
            pass
    return out


# 提醒
def due_reminders(last_check_minute: str) -> list:
    """
    返回当前分钟应触发的提醒。last_check_minute 是上次检查的 "HH:MM",
    避免同一分钟重复触发。
    """
    plan = get_plan()
    if not plan:
        return []
    now = time.strftime("%H:%M")
    if now == last_check_minute:
        return []
    due = []
    for r in plan.get("reminders", []):
        if r.get("time") == now:
            due.append(r)
    return due


# 工具函数
def _days_between(start: str, end: str) -> int:
    """计算两个 YYYY-MM-DD 之间的天数。"""
    try:
        import datetime
        d1 = datetime.date.fromisoformat(start)
        d2 = datetime.date.fromisoformat(end)
        return max(0, (d2 - d1).days)
    except Exception:
        return 0

def _parse_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON(容错:去掉可能的 markdown 代码块)。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 包裹
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        # 尝试截取第一个 { 到最后一个 }
        try:
            s, e = text.find("{"), text.rfind("}")
            if s != -1 and e != -1:
                return json.loads(text[s:e + 1])
        except Exception:
            pass
    return {}

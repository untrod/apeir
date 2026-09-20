# -*- coding: utf-8 -*-
"""
Skill Runtime v1.

This layer groups existing tools into task-level skills. It is intentionally
low-risk: skills only add routing metadata, prompt guidance, permissions, and
tool filtering. Actual execution still goes through the existing tool dispatch
and safety gates.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

log = logging.getLogger("brain")

SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


DEFAULT_SKILLS: list[dict[str, Any]] = [
    {
        "id": "desktop_operator",
        "name": "桌面操作员",
        "description": "观察和操作 Windows 桌面应用,完成点击、输入、截图、窗口切换等任务。",
        "tool_profile": "system",
        "triggers": ["点击", "鼠标", "窗口", "屏幕", "截图", "桌面", "打开软件", "输入到", "快捷键", "滚动"],
        "permissions": ["screen.screenshot", "desktop.click", "desktop.type", "desktop.hotkey", "shell.exec"],
        "tools": ["desktop_observe", "desktop_act", "screenshot", "gui_control", "image_analyze", "open_app", "get_system_info"],
        "success_criteria": ["执行后确认屏幕状态", "高危点击或破坏性命令必须走安全闸"],
        "instruction": (
            "当前 Skill: 桌面操作员。优先用 desktop_observe 观察窗口/鼠标/截图,必要时用 image_analyze 判断位置,"
            "再用 desktop_act 执行点击/输入/快捷键。每次 GUI 操作后必须再次观察验证结果。不要猜测坐标。"
        ),
    },
    {
        "id": "phone_operator",
        "name": "手机操作员",
        "description": "通过已有手机联动能力查看手机状态、应用和截图。后续可接 AccessibilityService。",
        "tool_profile": "system",
        "triggers": ["手机", "手表", "安卓", "微信", "通知", "手机截图", "打开手机", "手机应用"],
        "permissions": ["phone.info", "phone.screenshot", "phone.app_list", "phone.observe", "phone.act"],
        "tools": ["phone_observe", "phone_act", "phone_info", "phone_app_list", "phone_screenshot", "image_analyze"],
        "success_criteria": ["先确认目标设备在线", "涉及手机屏幕操作时先获取截图或状态"],
        "instruction": (
            "当前 Skill: 手机操作员。先确认手机/手表状态和可用能力;当前版本优先使用 phone_info、"
            "phone_app_list、phone_screenshot。需要点击/输入时说明当前还需要 AccessibilityService 能力。"
        ),
    },
    {
        "id": "code_engineer",
        "name": "专业工程师",
        "description": "Analyzes projects, modifies code, runs tests, reviews changes, and explains deployments like a coding agent.",
        "tool_profile": "full",
        "triggers": ["代码", "项目", "bug", "报错", "实现", "重构", "测试", "构建", "review", "codex", "claude code"],
        "permissions": ["files.read", "files.write", "shell.exec", "code.delegate"],
        "tools": [
            "file_read", "file_write", "search_files", "search_content", "run_command",
            "delegate_to_claude", "code_review", "project_summary", "git_status"
        ],
        "success_criteria": ["先读项目上下文", "修改前说明计划", "修改后运行可行的校验", "总结改动和风险"],
        "instruction": (
            "当前 Skill: 专业工程师。先理解项目结构和相关文件,再给出小步计划;改动要集中且可验证。"
            "能运行测试/语法检查就运行;不能运行要说明原因。不要覆盖用户未要求的文件。"
        ),
    },
    {
        "id": "study_tutor",
        "name": "学习导师",
        "description": "Study tutor: planning, explanation, practice, review, error diagnosis, and mastery tracking with spaced repetition.",
        "tool_profile": "learn",
        "triggers": ["学习", "复习", "出题", "刷题", "单词", "错题", "掌握", "今日计划", "知识点"],
        "permissions": ["learn.read", "learn.write", "rag.search"],
        "tools": [
            "learn_today_plan", "learn_today_tasks", "learn_catalog", "learn_get",
            "learn_search_semantic", "learn_ask_document", "learn_practice", "learn_generate_quiz",
            "learn_record_exercise", "learn_diagnose_mistake", "learn_vocab", "learn_coverage",
            "learn_checkin", "learn_phase_summary"
        ],
        "success_criteria": ["先定位知识点或计划", "讲解后给练习", "练习后记录结果或给复习建议"],
        "instruction": (
            "当前 Skill: 学习导师。目标是提高掌握度,不是只回答一次。优先结合学情快照、今日计划、"
            "知识库/RAG、题库和错题;讲解后安排练习,练习后给反馈和下一步。"
        ),
    },
    {
        "id": "workflow_assistant",
        "name": "工作流助理",
        "description": "处理搜索、写作、日程、文件、二维码、密码等通用工作流。",
        "tool_profile": "full",
        "triggers": ["搜索", "查一下", "写邮件", "通知", "日程", "提醒", "文件", "二维码", "密码", "总结"],
        "permissions": ["web.search", "files.read", "files.write", "calendar.write"],
        "tools": [
            "web_search", "web_fetch", "file_read", "file_write", "search_files",
            "password_generate", "qr_generate", "add_calendar_event", "add_reminder"
        ],
        "success_criteria": ["纯写作不调用系统工具", "联网结果要给来源或说明不确定性", "写文件前确认路径"],
        "instruction": (
            "当前 Skill: 工作流助理。先判断是否真的需要工具;纯写作直接完成。涉及文件、日程、提醒、"
            "外部搜索时再调用对应工具,并说明关键结果。"
        ),
    },
]


def _normalize_skill(raw: dict[str, Any]) -> dict[str, Any]:
    skill = dict(raw)
    skill["id"] = str(skill.get("id") or "").strip()
    skill["name"] = str(skill.get("name") or skill["id"]).strip()
    skill["description"] = str(skill.get("description") or "").strip()
    skill["tool_profile"] = str(skill.get("tool_profile") or "full").strip()
    for key in ("triggers", "permissions", "tools", "success_criteria"):
        vals = skill.get(key) or []
        skill[key] = [str(x).strip() for x in vals if str(x).strip()]
    skill["instruction"] = str(skill.get("instruction") or "").strip()
    return skill


@lru_cache(maxsize=1)
def load_skills() -> list[dict[str, Any]]:
    skills = {_normalize_skill(s)["id"]: _normalize_skill(s) for s in DEFAULT_SKILLS}
    if os.path.isdir(SKILL_DIR):
        for name in sorted(os.listdir(SKILL_DIR)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(SKILL_DIR, name)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        skill = _normalize_skill(item)
                        if skill["id"]:
                            skills[skill["id"]] = skill
            except Exception as e:
                log.warning("加载 skill 失败 %s: %s", path, e)
    return list(skills.values())


def get_skill(skill_id: str) -> dict[str, Any] | None:
    for skill in load_skills():
        if skill.get("id") == skill_id:
            return skill
    return None


def detect_skill(user_text: str) -> dict[str, Any] | None:
    if not isinstance(user_text, str) or not user_text.strip():
        return None
    text = user_text.lower()
    best = None
    best_score = 0
    for skill in load_skills():
        score = 0
        if f"#{skill['id']}" in text:
            score += 100
        for trigger in skill.get("triggers", []):
            t = trigger.lower()
            if t and t in text:
                score += 1
        if score > best_score:
            best = skill
            best_score = score
    return best if best_score > 0 else None


def build_skill_prompt(skill: dict[str, Any]) -> str:
    if not skill:
        return ""
    lines = [
        "\n[Skill Runtime]",
        f"当前技能: {skill.get('name', skill.get('id', ''))}",
        f"技能目标: {skill.get('description', '')}",
    ]
    if skill.get("permissions"):
        lines.append("权限边界: " + ", ".join(skill["permissions"]))
    if skill.get("success_criteria"):
        lines.append("完成标准: " + "；".join(skill["success_criteria"]))
    if skill.get("instruction"):
        lines.append(skill["instruction"])
    return "\n".join(lines) + "\n"


def apply_skill(session: dict, user_text: str) -> dict[str, Any] | None:
    skill = detect_skill(user_text)
    if not skill:
        session.pop("_active_skill", None)
        session.pop("_skill_instruction", None)
        session.pop("_skill_permissions", None)
        return None
    session["_active_skill"] = skill["id"]
    session["_skill_instruction"] = build_skill_prompt(skill)
    session["_skill_permissions"] = skill.get("permissions", [])
    return skill


def _tool_name(tool_def: dict[str, Any]) -> str:
    return str((tool_def.get("function") or {}).get("name") or "")


def tool_defs_for_skill(skill_id: str, fallback_defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    skill = get_skill(skill_id)
    if not skill:
        return fallback_defs
    names = set(skill.get("tools") or [])
    if not names:
        return fallback_defs
    try:
        import tools
        all_defs = tools.get_tool_defs()
    except Exception:
        all_defs = fallback_defs
    selected = [td for td in all_defs if _tool_name(td) in names]
    return selected or fallback_defs



# Skill Runtime v2 — hooks, context, verification, chaining


# Skill chaining map: which skill to suggest after success
_CHAIN_MAP: dict[str, list[str]] = {
    "desktop_operator": ["code_engineer", "workflow_assistant"],
    "code_engineer": ["workflow_assistant"],
    "study_tutor": ["workflow_assistant"],
    "phone_operator": ["desktop_operator", "workflow_assistant"],
    "watch_operator": ["phone_operator"],
    "workflow_assistant": [],
}

# Registered hooks: {skill_id: {"pre": [fn, ...], "post": [fn, ...]}}
_HOOKS: dict[str, dict[str, list]] = {}


def register_hook(skill_id: str, hook_type: str, fn) -> bool:
    """
    Register a pre_execute or post_execute hook for a skill.

    hook_type: "pre" or "post"
    fn: callable(skill, session, context) -> dict | None
        - pre hooks can modify session (e.g. set up context)
        - post hooks receive result dict, can emit events or chain

    Use skill_id="*" for global hooks (run for all skills).
    """
    if hook_type not in ("pre", "post"):
        return False
    _HOOKS.setdefault(skill_id, {}).setdefault(hook_type, []).append(fn)
    log.debug("Registered %s hook for skill '%s': %s", hook_type, skill_id,
              getattr(fn, "__name__", str(fn)))
    return True


def _run_hooks(skill_id: str, hook_type: str, skill: dict, session: dict,
               context: dict | None = None, result: dict | None = None):
    """Run all matching hooks for a skill. Global hooks (*) run first."""
    for sid in ("*", skill_id):
        for fn in _HOOKS.get(sid, {}).get(hook_type, []):
            try:
                if hook_type == "pre":
                    fn(skill, session, context or {})
                else:
                    fn(skill, session, context or {}, result or {})
            except Exception as e:
                log.warning("Hook %s/%s for %s failed: %s", sid, hook_type, skill_id, e)


# Skill Context (cross-skill state within a session)

def get_skill_context(session: dict) -> dict[str, Any]:
    """Get or create the cross-skill context dict for this session."""
    ctx = session.get("_skill_context")
    if not isinstance(ctx, dict):
        ctx = {}
        session["_skill_context"] = ctx
    return ctx


def set_skill_context(session: dict, key: str, value: Any):
    """Set a value in the cross-skill context."""
    ctx = get_skill_context(session)
    ctx[key] = value


def clear_skill_context(session: dict):
    """Clear the cross-skill context (e.g. when skill chain completes)."""
    session.pop("_skill_context", None)


# Enhanced apply_skill v2

def apply_skill_v2(session: dict, user_text: str) -> dict[str, Any] | None:
    """
    Enhanced skill activation with hooks, context, and events.

    Differences from v1 apply_skill():
      - Runs pre_execute hooks before activation
      - Initializes _skill_context for cross-skill state
      - Emits skill.activated event via nous_core
      - Tracks skill activation history in _skill_history
    """
    # Detect target skill
    skill = detect_skill(user_text)
    prev_skill = session.get("_active_skill", "")

    if not skill:
        # Skill deactivation — run post hooks for previous skill
        if prev_skill:
            prev = get_skill(prev_skill)
            if prev:
                _run_hooks(prev_skill, "post", prev, session,
                          context=get_skill_context(session),
                          result={"reason": "deactivated", "next_skill": None})
        session.pop("_active_skill", None)
        session.pop("_skill_instruction", None)
        session.pop("_skill_permissions", None)
        return None

    skill_id = skill["id"]

    # If switching skills, run post hooks on the old skill first
    if prev_skill and prev_skill != skill_id:
        prev = get_skill(prev_skill)
        if prev:
            _run_hooks(prev_skill, "post", prev, session,
                      context=get_skill_context(session),
                      result={"reason": "switched", "next_skill": skill_id})

    # Initialize context if this is a new skill chain
    if not prev_skill or prev_skill != skill_id:
        if "_skill_context" not in session:
            session["_skill_context"] = {}

    # Track activation history
    history = session.setdefault("_skill_history", [])
    history.append({"skill": skill_id, "name": skill["name"], "at": _time_now()})
    # Keep last 20 entries
    if len(history) > 20:
        session["_skill_history"] = history[-20:]

    # Run pre hooks
    _run_hooks(skill_id, "pre", skill, session, context=get_skill_context(session))

    # Set session state
    session["_active_skill"] = skill_id
    session["_skill_instruction"] = build_skill_prompt(skill)
    session["_skill_permissions"] = skill.get("permissions", [])

    # Emit event
    _emit_skill_event("skill.activated",
                     skill_id=skill_id, skill_name=skill["name"],
                     previous_skill=prev_skill, session=session)

    return skill


# Completion verification

def verify_skill_completion(skill_id: str, session: dict,
                            tool_results: list[dict] | None = None) -> dict[str, Any]:
    """
    Check if a skill's success criteria have been met.

    Returns: {
      "complete": bool,
      "criteria_met": [...],
      "criteria_unmet": [...],
      "suggestion": str  # human-readable next-step suggestion
    }
    """
    skill = get_skill(skill_id)
    criteria = skill.get("success_criteria", []) if skill else []
    tool_results = tool_results or []

    if not criteria:
        return {"complete": True, "criteria_met": [], "criteria_unmet": [],
                "suggestion": ""}

    met = []
    unmet = list(criteria)

    # Simple heuristic: if tools were called that match criteria keywords
    tools_used = {r.get("tool_name", "") or r.get("command", "") or ""
                  for r in tool_results}
    outputs = " ".join(str(r.get("output", "") or "") for r in tool_results).lower()

    for c in list(unmet):
        c_lower = c.lower()
        # Check if relevant tools were called
        if any(kw in c_lower for kw in ["观察", "observe", "截图", "screenshot"]) and \
           any(t in str(tools_used) for t in ["observe", "screenshot", "image"]):
            met.append(c); unmet.remove(c)
        elif any(kw in c_lower for kw in ["确认", "验证", "verify", "confirm"]) and \
             "observe" in str(tools_used):
            met.append(c); unmet.remove(c)
        elif any(kw in c_lower for kw in ["计划", "说明", "plan", "explain"]) and \
             len(outputs) > 100:
            met.append(c); unmet.remove(c)
        elif any(kw in c_lower for kw in ["不猜", "不要猜测", "known"]) and \
             "image_analyze" in str(tools_used):
            met.append(c); unmet.remove(c)

    complete = len(unmet) == 0

    suggestion = ""
    if unmet:
        suggestion = "建议: " + "；".join(unmet)

    return {"complete": complete, "criteria_met": met, "criteria_unmet": unmet,
            "suggestion": suggestion}


# Skill chaining

def suggest_next_skill(skill_id: str, session: dict) -> dict[str, Any] | None:
    """
    After a skill completes, suggest a logical follow-up skill.
    Returns the suggested skill dict or None.
    """
    candidates = _CHAIN_MAP.get(skill_id, [])
    history = session.get("_skill_history", [])
    recent = {h.get("skill", "") for h in history[-5:]}

    for cid in candidates:
        if cid not in recent:  # Don't suggest skills we just used
            return get_skill(cid)
    return None


def complete_skill(skill_id: str, session: dict,
                   result: dict | None = None) -> dict[str, Any]:
    """
    Mark a skill as completed. Runs post hooks, emits event,
    and returns verification + chaining suggestion.
    """
    skill = get_skill(skill_id)
    ctx = get_skill_context(session)

    # Run post hooks
    if skill:
        _run_hooks(skill_id, "post", skill, session, context=ctx,
                   result=result or {"reason": "completed"})

    # Verify completion
    verification = verify_skill_completion(skill_id, session)

    # Get chaining suggestion
    next_skill = suggest_next_skill(skill_id, session)

    # Emit event
    _emit_skill_event("skill.completed",
                     skill_id=skill_id,
                     skill_name=skill.get("name", skill_id) if skill else skill_id,
                     verification=verification,
                     next_skill=next_skill.get("id") if next_skill else None,
                     session=session)

    return {
        "skill_id": skill_id,
        "verification": verification,
        "next_skill": next_skill,
    }


# Event emission helper

def _emit_skill_event(event_type: str, session: dict, **payload):
    """Emit a skill lifecycle event (best-effort, never throws)."""
    try:
        from nous_core.events import emit_event
        emit_event(
            event_type,
            source=payload.pop("skill_id", "skill_engine"),
            session_id=session.get("_transcript_sid", ""),
            payload=payload,
        )
    except Exception:
        pass


def _time_now() -> str:
    """Return current UTC timestamp string."""
    try:
        from datetime import datetime, timezone
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


# Built-in hooks (registered at import time)

def _builtin_pre_context_init(skill: dict, session: dict, context: dict):
    """Pre-hook: ensure skill context has standard fields."""
    ctx = get_skill_context(session)
    ctx.setdefault("activated_skills", [])
    if skill["id"] not in ctx["activated_skills"]:
        ctx["activated_skills"].append(skill["id"])
    ctx.setdefault("step_count", 0)


def _builtin_post_log_completion(skill: dict, session: dict, context: dict,
                                 result: dict):
    """Post-hook: log skill completion at debug level."""
    log.debug("Skill '%s' completed: %s", skill.get("name", skill["id"]),
              result.get("reason", "unknown"))


# Register built-in hooks
register_hook("*", "pre", _builtin_pre_context_init)
register_hook("*", "post", _builtin_post_log_completion)

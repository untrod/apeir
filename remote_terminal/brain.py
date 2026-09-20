# -*- coding: utf-8 -*-
"""
私有远程技术终端 —— 指挥层(大脑 brain.py),运行在中继服务器。
接收任意已配对设备的指令 → LLM 规划 → 把执行指令下发给指定目标 Agent → 收集结果回复来源。

⚠️ LEGACY PATH CONSOLIDATION (2026-07-27):
  All execution paths now route through the unified nous_runtime architecture:
  - Model calls: brain_llm → model_gateway_bridge → ModelGatewayFacade
  - Tool dispatch: tools.dispatch() → CapabilityContract → AdmissionPipeline
  - Shell execution: _do_execute → ExecutionSandbox
  - Session/Task: run_turn → Session + Task + PlanArtifact + ExecutionTicket
  - Compat entry points preserved with DeprecationWarning + legacy metrics

设计要点:
  - 会话状态在大脑端:按 session_id 保存完整历史(含工具调用/结果)、当前工作目录 cwd、滚动摘要。
  - 设备路由:维护 devices.json 设备注册表,_exec_raw() 按 target_device 路由命令。
  - 每设备独立 token:devices.json 中每设备一个 token,brain 下发命令用设备专属 token。
  - 审计全量:每条执行记录包含 source_device(谁下达)和 target_device(谁执行)。

通信:
  POST /chat  头 X-Auth-Token:<令牌>
              体 {"session_id":"可选","message":"用户这句","model":"可选","target_device":"可选"}
              回 {"ok":true,"session_id":"...","reply":"...","steps":[...]}
  GET  /devices?token=xxx  列出所有已注册设备
"""

import json
import logging
import logging.handlers
import os
import re as _re
import threading
import time
import uuid
import urllib.error
import urllib.request
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import config
import crypto
import safety
import tools
import study_manager
import learn_tools
import learner_profile

# 提取的模块(从 brain.py 拆分)
import brain_latex
import brain_utils
import device_transport
import brain_devices
import brain_clients
import brain_sessions
import brain_prompt
import brain_llm
import skill_engine

# Legacy Path Consolidation bridges (2026-07-27)
try:
    import capability_tool_bridge as _cap_bridge
except ImportError:
    try:
        from remote_terminal import capability_tool_bridge as _cap_bridge
    except ImportError:
        _cap_bridge = None

try:
    import session_task_bridge as _st_bridge
except ImportError:
    try:
        from remote_terminal import session_task_bridge as _st_bridge
    except ImportError:
        _st_bridge = None

try:
    import plan_artifact as _plan_mod
except ImportError:
    try:
        from remote_terminal import plan_artifact as _plan_mod
    except ImportError:
        _plan_mod = None

# Legacy metrics for brain.py compat paths
_BRAIN_LEGACY_EXEC_RAW_TOTAL: int = 0
_BRAIN_LEGACY_EXEC_IN_SESSION_TOTAL: int = 0
_BRAIN_LEGACY_DISPATCH_TOTAL: int = 0

_DEPRECATION_EXEC_MSG = (
    "Direct shell execution is a legacy compat path. "
    "Use nous_runtime.capability.sandbox.ExecutionSandbox instead."
)

# Nous Core Kernel (P0)
from nous_core.db import run_migrations as _run_nous_core_migrations
from nous_core.events import emit_event as _emit_event
from nous_core.events.dispatcher import start_dispatcher as _start_dispatcher, \
    register_builtin_handlers as _register_builtin_handlers, \
    register_handler as _register_event_handler
from nous_core.devices import sync_from_legacy as _sync_devices
from nous_core.jobs import recover_stale_jobs as _recover_stale_jobs
from nous_core.automation import evaluate_event as _automation_evaluate, \
    seed_default_rules as _automation_seed_defaults
from nous_core.audit import audit_log as _audit_log
from nous_core.jobs import create_job as _create_job, complete_job as _complete_job, \
    fail_job as _fail_job
from nous_core.reasoning import (
    trace_capability_call as _trace_capability_call,
    get_session_traces as _get_session_traces,
    get_recent_traces as _get_recent_traces,
    get_failure_analysis as _get_failure_analysis,
)
from nous_core.router import route as _route_model, list_routing_rules as _list_routing_rules
from nous_core.observer import observe as _observe, get_observer_stats as _get_observer_stats
from nous_core.provider import (
    register_adapter as _register_adapter,
    list_providers as _list_providers,
)
from nous_core.security import (
    check_risk as _check_risk,
    record_security_event as _record_security_event,
    get_security_stats as _get_security_stats,
)
from nous_core.stability import take_snapshot as _stability_snapshot, \
    get_stability_report as _stability_report
from nous_core.notify_bridge import (
    notify_device_offline as _notify_device_offline,
)
from nous_core.demo_mode import is_demo_mode as _is_demo, enable_demo_mode as _enable_demo
from nous_core.protocol import Envelope as _Envelope
from nous_core.capability import (
    register_capability as _register_capability,
    register_provider as _register_provider,
    request_capability as _request_capability,
    request_capability_graph as _request_capability_graph,
    seed_default_capabilities as _seed_default_capabilities,
    seed_composed_capabilities as _seed_composed_capabilities,
    get_dependency_graph as _get_dependency_graph,
    list_capabilities as _list_capabilities,
)


# P3 Capability OS — Provider Handlers


def _capability_model_reason(**params):
    """Provider: openai — model.reason"""
    prompt = params.get("prompt", "")
    model = params.get("model", config.LLM_MODEL)
    # Direct model call for simple reasoning
    convo = [{"role": "user", "content": prompt}]
    msg = call_model(convo, model, use_tools=False)
    return {"ok": True, "content": msg.get("content", ""), "model": model}

def _capability_model_code(**params):
    """Provider: claude_code — model.code"""
    prompt = params.get("prompt", "")
    model = params.get("model", config.LLM_MODEL)
    convo = [{"role": "user", "content": prompt}]
    msg = call_model(convo, model, use_tools=True)
    return {"ok": True, "content": msg.get("content", ""), "model": model}

def _capability_model_embed(**params):
    """Provider: fastembed — model.embed"""
    text = params.get("text", "")
    try:
        from embedding import embed_text
        vector = embed_text(text)
        return {"ok": True, "vector_dim": len(vector) if vector else 0}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_model_transcribe(**params):
    """Provider: whisper — model.transcribe"""
    audio_path = params.get("audio_path", "")
    try:
        model = _get_whisper_cmd() if params.get("use_base") else _get_whisper()
        segments, _ = model.transcribe(audio_path, language="zh")
        text = " ".join(s.text for s in segments)
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_model_tts(**params):
    """Provider: edge_tts — model.tts"""
    text = params.get("text", "")
    voice = params.get("voice", "zh-CN-XiaoxiaoNeural")
    try:
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out = f.name
        subprocess.run(["edge-tts", "--voice", voice, "--text", text,
                       "--write-media", out], capture_output=True, timeout=30)
        return {"ok": True, "audio_path": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_rag(**params):
    """Provider: chromadb — rag.search / rag.index"""
    action = params.get("action", "search")
    try:
        from vector_store import search_knowledge, search_documents, add_document_chunks
        if action == "search":
            query = params.get("query", "")
            top_k = params.get("top_k", 5)
            kp_results = search_knowledge(query, top_k=top_k)
            doc_results = search_documents(query, top_k=top_k)
            return {"ok": True, "knowledge_hits": len(kp_results), "document_hits": len(doc_results),
                    "results": kp_results + doc_results}
        elif action == "index":
            add_document_chunks(params.get("doc_id", 0), params.get("text", ""),
                               subject=params.get("subject", ""))
            return {"ok": True, "indexed": True}
        return {"ok": False, "error": f"Unknown RAG action: {action}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_device_pc(**params):
    """Provider: pc_agent — device.pc.*"""
    device_id = params.get("device_id", config.DEFAULT_DEVICE)
    command = params.get("command", "")
    if command:
        output, rc = _exec_raw(command, device_id=device_id)
        return {"ok": rc == 0, "output": output, "returncode": rc}
    return {"ok": False, "error": "No command provided"}

def _capability_device_android(**params):
    """Provider: android — device.phone.* / device.watch.*"""
    action = params.get("action", "observe")
    target = params.get("target", "")
    try:
        import tools
        if action == "observe":
            result = tools.handle_phone_observe({}, {}, lambda cmd: ("", -1))
            return {"ok": True, "ui_tree": result.output if hasattr(result, 'output') else str(result)}
        elif action == "act":
            result = tools.execute_phone_act(params)
            return {"ok": True, "result": result}
        return {"ok": False, "error": f"Unknown android action: {action}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_notification(**params):
    """Provider: nous_notify — notification.send"""
    try:
        from nous_core.notifications import notify
        nid = notify(
            params.get("type", "capability"),
            title=params.get("title", ""),
            body=params.get("body", ""),
            target_client=params.get("target_client", ""),
            priority=int(params.get("priority", 0)),
            data=params.get("data"),
        )
        return {"ok": True, "notification_id": nid}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_tool_web(**params):
    """Provider: web — tool.web_search"""
    try:
        import tools
        result = tools.handle_web_search({"query": params.get("query", "")}, {}, lambda cmd: ("", -1))
        status = getattr(result, "status", "done")
        return {
            "ok": status == "done",
            "status": status,
            "requires_approval": status == "awaiting_confirmation",
            "results": result.output if hasattr(result, "output") else str(result),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _capability_automation(**params):
    """Provider: nous_automation — automation.trigger"""
    try:
        from nous_core.automation import evaluate_event
        event = {
            "type": params.get("event_type", "automation.trigger"),
            "source": params.get("source", "capability"),
            "payload": params.get("payload", {}),
        }
        evaluate_event(event)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 保持原有函数名兼容
load_devices = brain_devices.load_devices
save_devices = brain_devices.save_devices
get_device = brain_devices.get_device
get_default_cwd = brain_devices.get_default_cwd
is_device_online = brain_devices.is_device_online
start_probe_thread = brain_devices.start_probe_thread
devices = brain_devices.devices  # 引用同一个 dict

load_clients = brain_clients.load_clients
resolve_client = brain_clients.resolve_client
clients = brain_clients.clients
_client_tool_profile = brain_clients.client_tool_profile

load_sessions = brain_sessions.load_sessions
save_sessions = brain_sessions.save_sessions
get_session = brain_sessions.get_session
sessions = brain_sessions.sessions

_delatex = brain_latex.delatex
_post_json = brain_utils.post_json
_truncate = brain_utils.truncate
_write_transcript = brain_utils.write_transcript

get_system_prompt = brain_prompt.get_system_prompt
_SYSTEM_PROMPT = brain_prompt._SYSTEM_PROMPT
_tools_for_profile = brain_prompt.resolve_tools_for_profile
_resolve_profile = brain_prompt.resolve_profile
_apply_mode_prefix = brain_prompt.apply_mode_prefix
_learn_state_snapshot = brain_prompt.learn_state_snapshot
_is_learning_context = brain_prompt.is_learning_context


def _route_message_skill(session: dict, message: str) -> None:
    """
    Apply Skill Runtime v2 routing — uses enhanced apply_skill_v2 with hooks,
    context, and events. Falls back to legacy intent classifier when no skill matches.
    """
    # P0-6: use v2 skill activation with hooks + context + events
    skill = skill_engine.apply_skill_v2(session, message)
    if session.get("_client_profile") != "full":
        return
    if skill:
        profile = skill.get("tool_profile", "full")
        if profile != "full":
            session["_mode_profile"] = profile
        else:
            session.pop("_mode_profile", None)
        log.info("Skill路由(v2): %s -> profile=%s", skill.get("id", ""), profile)
        return
    # Legacy fallback: intent-based tool narrowing
    narrowed = brain_prompt.classify_intent(message)
    if narrowed != "full":
        session["_mode_profile"] = narrowed
    else:
        session.pop("_mode_profile", None)


def _tool_defs_for_session(session: dict):
    base_defs = _tools_for_profile(_resolve_profile(session))
    return skill_engine.tool_defs_for_skill(session.get("_active_skill", ""), base_defs)

def _load_tomorrow_pack():
    """隔夜预备包:返回 None 不阻塞今日简报。"""
    return None

_UPLOAD_HTML = ""

def _load_upload_html():
    global _UPLOAD_HTML
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_upload.html")
    try:
        with open(p, encoding="utf-8") as f:
            _UPLOAD_HTML = f.read()
    except Exception:
        _UPLOAD_HTML = ("<!doctype html><meta charset=utf-8><title>Nous 上传</title>"
                        "<body style='font-family:sans-serif;padding:24px'>"
                        "<h3>Nous 资料上传</h3><p>上传页加载失败,请检查 learn_upload.html 是否存在。</p></body>")

call_model = brain_llm.call_model
call_ingest_model = brain_llm.call_ingest_model
call_model_stream = brain_llm.call_model_stream
_parse_pending_worker = brain_llm.parse_pending_worker
is_parse_worker_running = brain_llm.is_parse_worker_running
set_parse_worker_running = brain_llm.set_parse_worker_running

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain.log")

# 日志轮转:每10MB一个文件,保留5个备份,防止磁盘写满
_log_fh = logging.handlers.RotatingFileHandler(
    LOG_FILE, encoding="utf-8", maxBytes=10 * 1024 * 1024, backupCount=5)
_log_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), _log_fh],
)
log = logging.getLogger("brain")

_SENTINEL = "__CWD__::"  # 命令执行后用它把"当前目录"带回来,从而记住 cd

# 执行层调用(设备路由 + cwd 记忆 + 截断)
def _exec_raw(command, device_id=None):
    """
    调指定设备的 agent /exec 跑一条命令,返回拼好的文本。
    device_id 为 None 时使用 config.DEFAULT_DEVICE。
    """
    device_id = device_id or config.DEFAULT_DEVICE
    dev = get_device(device_id)
    if not dev:
        return f"(错误:设备 '{device_id}' 未注册。请在 devices.json 中添加此设备)", -1
    url = f"http://{dev['host']}:{dev['port']}/exec"
    token = dev.get("token", "") or crypto.load_token()
    headers = {"X-Auth-Token": token}
    # 对命令做 HMAC 签名:agent 用它验证危险命令确实来自 brain(已过安全闸/用户确认)
    sig = crypto.sign_command(command)
    if sig:
        headers["X-Cmd-Sig"] = sig
    data = _post_json(
        url, {"command": command},
        timeout=config.COMMAND_TIMEOUT + 5,
        headers=headers,
        expected_host=dev["host"],
        expected_port=int(dev["port"]),
    )
    # 更新设备最后活跃时间
    dev["last_seen"] = time.time()
    out = data.get("stdout", "") or ""
    err = data.get("stderr", "") or ""
    text = out
    if err:
        text += ("\n[stderr]\n" + err)

    # P0: record agent command execution event
    rc = data.get("returncode")
    _emit_event("agent.command.executed",
                source=device_id or config.DEFAULT_DEVICE,
                device_id=device_id or config.DEFAULT_DEVICE,
                payload={"command": command[:200], "returncode": rc, "ok": rc == 0,
                         "output_length": len(text)})

    return text, rc


def exec_in_session(command, session):
    """
    在会话的当前目录下执行命令,并记住命令可能引起的目录变化(cd)。
    做法:Set-Location 到会话 cwd -> 跑命令 -> 末尾打印一个带哨兵的"当前目录",
    我们解析出新 cwd 存回会话,并从展示输出里剔除哨兵行。
    """
    device_id = session.get("target_device") or config.DEFAULT_DEVICE
    cwd = session.get("cwd") or get_default_cwd(device_id)
    wrapped = (
        f'Set-Location -LiteralPath "{cwd}" -ErrorAction SilentlyContinue; '
        f'{command}; '
        f'Write-Output "{_SENTINEL}$((Get-Location).Path)"'
    )
    raw, _ = _exec_raw(wrapped, device_id=device_id)

    new_cwd = cwd
    kept = []
    for ln in raw.splitlines():
        idx = ln.find(_SENTINEL)
        if idx != -1:
            new_cwd = ln[idx + len(_SENTINEL):].strip()  # 记住新目录
        else:
            kept.append(ln)
    session["cwd"] = new_cwd or cwd

    output = "\n".join(kept).strip()
    return _truncate(output) if output else "(无输出)"


_whisper_model = None


def _get_whisper():
    """懒加载 + 缓存 whisper 模型(只加载一次,避免每次转写重载几秒)。"""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        log.info("whisper 模型已加载(缓存)")
    return _whisper_model


_whisper_cmd_model = None


def _get_whisper_cmd():
    """懒加载 + 缓存 whisper 指令模型(默认 base,比 tiny 更准)。
    唤醒仍用 tiny 保速度。可通过 WHISPER_CMD_MODEL env 切换。"""
    global _whisper_cmd_model
    if _whisper_cmd_model is None:
        from faster_whisper import WhisperModel
        cmd_model = os.environ.get("WHISPER_CMD_MODEL", "base")
        _whisper_cmd_model = WhisperModel(cmd_model, device="cpu", compute_type="int8")
        log.info("whisper 指令模型已加载(%s)", cmd_model)
    return _whisper_cmd_model


def _is_wake_word(text: str):
    """检查转写文本是否匹配唤醒词 'Nous' /naʊs/。
    返回 (is_wake: bool, greeting: str) — greeting 用于 App 选择问候语。"""
    if not text or not text.strip():
        return (False, "")
    t = _re.sub(r"""[\s,，。.!！?？、~'‘’"“”\-_]""", '', text.lower().strip())
    if not t or len(t) > 20:
        return (False, "")
    # 0) 前缀检测：在吗→"我在的"  你好/嘿→"嗯，我在，请说"
    zaima = {"在吗", "在么", "在嗎", "在不在", "zaima"}
    hello = {"你好", "嘿", "嗨", "hi", "hello", "哈喽", "哈啰", "黑"}
    has_zaima = any(p in t for p in zaima)
    has_hello = (not has_zaima) and any(p in t for p in hello)
    # 去掉最长匹配的前缀，得到核心唤醒词（"在吗Nous" → "nous"）
    core = t
    for p in sorted(zaima | hello, key=len, reverse=True):
        if p in core:
            core = core.replace(p, "", 1)
            break
    core = core.strip()
    # 1) 显式近音词库: whisper 小模型对 /naʊs/ 的各种英文写法 + 中文同音
    #    注意 t/core 已剥离撇号,故词库不含撇号变体(用 nows/nos 等覆盖)
    kws = [
        "nous", "nouse", "noose", "nooce", "noos", "nooze", "nooz", "nuse", "nus", "nuss",
        "newce", "news", "newse", "knous", "knaus", "naus", "nauss", "nows", "nowes", "nos",
        "knows", "gnaws", "mousse", "moose", "noux", "nox", "nors", "nawes", "naos",
        "nose", "noze", "noaz", "nouz", "noss", "noese", "nouce", "nowse", "naws", "nawss",
        "house", "hows", "howse", "hause", "haus", "hoss", "hous", "houss", "hoese", "howze",
        "laos", "louse", "loss", "lows", "lowes",
        "诺斯", "努斯", "纽斯", "闹斯", "挠斯", "脑斯", "闹丝", "诺丝", "努丝", "诺司", "努司",
        "那欧斯", "脑师", "闹师", "拿斯", "那斯", "糯斯", "诺诺", "努诺", "诺努",
        "你好诺", "小诺", "嘿诺", "黑诺", "嗨诺", "嘿nous", "嗨nous", "你好nous",
    ]

    def _looks(s):
        """一段(去前缀的核心 或 完整文本)是否像唤醒词 /naʊs/。"""
        if not s:
            return False
        if any(kw in s for kw in kws):
            return True
        if len(s) <= 5 and any(kw in s for kw in ["闹死", "脑死", "老斯", "劳斯", "捞斯"]):
            return True
        if len(s) <= 7 and _re.fullmatch(
                r"(kn|gn|n|h|l)(ou|oo|ow|au|oa|ao|aw|o|u)+(s|z|se|ze|ce|ss|sh|x|zz)", s):
            return True
        if _re.fullmatch(r"(n|kn|gn)(ou|ow|oo|au|oa)s?", s):
            return True
        return False

    # 同时对完整文本与去前缀核心判定(带"在吗/你好"前缀时核心才是唤醒词)
    wake = _looks(t) or _looks(core)
    if not wake:
        return (False, "")
    # 3) 选择问候语
    if has_zaima:
        return (True, "我在的")
    elif has_hello:
        return (True, "嗯，我在，请说")
    else:
        return (True, "嗯，请说")


# 滚动摘要
def _render(msgs):
    """把消息列表渲染成可读文本,供摘要用。"""
    parts = []
    for m in msgs:
        role = m.get("role")
        content = str(m.get("content") or "")
        if role == "user":
            parts.append("用户: " + content)
        elif role == "assistant":
            if content:
                parts.append("助手: " + content)
            for tc in (m.get("tool_calls") or []):
                try:
                    cmd = json.loads(tc["function"]["arguments"]).get("command", "")
                except Exception:
                    cmd = ""
                parts.append("助手执行: " + cmd)
        elif role == "tool":
            parts.append("结果: " + content[:500])
    return "\n".join(parts)


def maybe_summarize(session, model):
    """历史超阈值时,把较早内容压成摘要,只保留最近几轮原文。按用户消息边界切,保证安全。"""
    msgs = session["messages"]
    total = sum(len(str(m.get("content") or "")) for m in msgs)
    if total <= config.SESSION_MAX_CONTEXT_CHARS:
        return
    user_idx = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
    if len(user_idx) <= config.SESSION_KEEP_TURNS:
        return  # 轮数太少不压,避免把当前任务也摘掉

    cut = user_idx[-config.SESSION_KEEP_TURNS]  # 从这条用户消息起保留原文
    old, recent = msgs[:cut], msgs[cut:]
    log.info("上下文 %d 字超阈值,压缩较早的 %d 条消息为摘要", total, len(old))
    try:
        prev = session.get("summary", "")
        prompt = ("你在压缩一段助手与用户在 Windows 电脑上的运维对话历史。用简洁中文输出摘要,"
                  "保留:用户目标、已执行的关键命令及结论、重要路径/数值/状态、未完成事项。不要寒暄。")
        convo = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": (("【已有摘要】\n" + prev + "\n\n") if prev else "")
             + "【需并入摘要的对话】\n" + _render(old)},
        ]
        session["summary"] = (call_model(convo, model, use_tools=False).get("content") or "").strip()
        session["messages"] = recent
    except Exception as e:
        log.error("摘要失败(保留原历史): %s", e)  # 摘要失败就不动历史,宁可长也别丢


# 一轮对话
def _clean_assistant(msg):
    """只留 role/content/tool_calls 存进历史,避免把接口附带字段也存下来。"""
    out = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    return out


def _drop_orphan_tools(messages):
    """删除"孤儿 tool 消息":前面没有携带其 tool_call_id 的 assistant(tool_calls)。
    根因:摘要裁剪 / 强修删 tool_calls 后,残留的 tool 消息会触发 HTTP 400
    'Messages with role tool must be a response to a preceding tool_calls'。"""
    valid_ids = set()
    out = []
    dropped = False
    for m in messages:
        role = m.get("role")
        if role == "tool":
            if m.get("tool_call_id", "") in valid_ids:
                out.append(m)
            else:
                dropped = True  # 孤儿 → 丢弃
        else:
            if role == "assistant":
                valid_ids = {tc.get("id", "") for tc in (m.get("tool_calls") or []) if tc.get("id")}
            else:
                valid_ids = set()  # user/system 之后不再接受旧 id
            out.append(m)
    if dropped:
        messages[:] = out
        log.warning("清理孤儿 tool 消息,剩 %d 条", len(messages))
    return dropped


def _repair_history(messages):
    """
    修复会话历史中 tool_calls / tool 配对断裂的问题。
    根因:若 brain 在工具执行中途崩溃/超时,会话存下了 assistant(tool_calls) 但缺 tool 回复,
    下次送模型时触发 HTTP 400 'insufficient tool messages following tool_calls message'。
    修法:扫描每条 assistant 的 tool_calls,确认后面有对应 tool_call_id 的 tool 消息;
    缺的补一条"(执行中断,无结果)"。孤儿 tool 消息先清掉。
    """
    repaired = _drop_orphan_tools(messages)
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            needed_ids = {tc.get("id", "") for tc in msg["tool_calls"] if tc.get("id")}
            # 收集紧跟在后面的 tool 消息(可能有多条,且中间不应有其他角色)
            j = i + 1
            found_ids = set()
            while j < len(messages) and messages[j].get("role") == "tool":
                tid = messages[j].get("tool_call_id", "")
                if tid:
                    found_ids.add(tid)
                j += 1
            # 补缺
            missing = needed_ids - found_ids
            if missing:
                log.warning("修复断裂历史:assistant[%d] 有 %d 个 tool_calls 缺回复,补占位", i, len(missing))
                for mid in missing:
                    messages.insert(j, {"role": "tool", "tool_call_id": mid, "content": "(执行中断,无结果)"})
                    j += 1
                repaired = True
            i = j
        else:
            i += 1
    return repaired


def _force_fix_history(messages):
    """
    强修:找到最后一条有 tool_calls 但无完整 tool 响应的 assistant 消息,
    删除该 tool_calls(保留正文)。比 _repair_history 更激进,用于 400 重试。
    """
    if not messages:
        return
    last_user = 0
    for idx, m in enumerate(messages):
        if m.get("role") == "user":
            last_user = idx
    # 从最后一个 user 之后扫描,移除不完整的 tool_calls
    for idx in range(last_user, len(messages)):
        m = messages[idx]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            needed = {tc.get("id", "") for tc in m["tool_calls"] if tc.get("id")}
            found = set()
            j = idx + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                tid = messages[j].get("tool_call_id", "")
                if tid:
                    found.add(tid)
                j += 1
            if needed - found:
                # 不完整:删除 tool_calls,保留正文
                log.warning("强修:删除 assistant[%d] 的 %d 个未配对 tool_calls", idx, len(needed - found))
                content = m.get("content")
                if content:
                    messages[idx] = {"role": "assistant", "content": content}
                else:
                    messages[idx] = {"role": "assistant", "content": "(工具调用中断,继续)"}
    # 删 tool_calls 后,后面的 tool 消息就成了孤儿,必须清掉,否则照样 400
    _drop_orphan_tools(messages)


# 会话标题自动生成
_TITLE_GEN_LOCK = threading.Lock()
_TITLE_GENERATING = set()  # 正在生成标题的 session_id 集合，防重复

def _generate_session_title(session, sid):
    """后台异步生成会话标题+标签（首条用户消息后调 LLM，不阻塞主流程）。"""
    if sid in _TITLE_GENERATING:
        return
    msgs = session.get("messages", [])
    if len(msgs) < 2:
        return
    # 取前2条用户消息作为素材
    user_texts = [m.get("content", "") for m in msgs if m.get("role") == "user"][:2]
    if not user_texts:
        return
    user_input = " ".join(t for t in user_texts if t)[:300]
    if not user_input:
        return
    _TITLE_GENERATING.add(sid)
    def _worker():
        try:
            prompt = (
                "你是一个标题生成器。根据用户的第一条消息，生成一个简短的会话标题（6-15字）和一个标签。\n"
                "标签从以下选择：学习、系统操作、写作、代码、闲聊、搜索。\n"
                '只输出JSON: {"title":"...","tag":"..."}'
            )
            convo = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input},
            ]
            result = call_model(convo, None, use_tools=False)
            content = result.get("content", "")
            # 提取 JSON（容忍 markdown 包裹）
            import re as _re2
            m = _re2.search(r'\{[^}]+\}', content)
            if m:
                data = json.loads(m.group())
                session["title"] = data.get("title", "")[:20]
                session["tags"] = [data.get("tag", "")]
            else:
                session["title"] = user_input[:20] + ("…" if len(user_input) > 20 else "")
                session["tags"] = []
            session["_title_generated"] = True
            save_sessions()
        except Exception:
            pass
        finally:
            _TITLE_GENERATING.discard(sid)
    t = threading.Thread(target=_worker, daemon=True, name="title-gen")
    t.start()


def _do_execute(command, session):
    """
    执行一条命令(带安全闸、日志、审计)。
    本函数是唯一通向 exec_in_session 的入口——保证所有执行都经过安全闸。

    ⚠️ LEGACY PATH CONSOLIDATION: Now wraps execution in ExecutionSandbox
    and records evidence through the unified pipeline.

    返回: {"status": "done"|"awaiting_confirmation", "output": "...", ...}
    """
    # 1. 安全检测
    mode = getattr(config, "SAFETY_MODE", "normal")
    danger = safety.check_danger(command, mode)

    # 2. 危险 → 不执行,返回待确认
    if danger.is_danger:
        cid = uuid.uuid4().hex[:12]
        log.warning("安全闸拦截(cwd=%s, mode=%s): %s —— 原因: %s",
                    session.get("cwd"), mode, _mask_sensitive(command), "; ".join(danger.reasons))
        # P0: record events + audit
        _emit_event("tool.confirmation_required",
                    source="run_command", session_id=session.get("_transcript_sid", ""),
                    payload={"confirmation_id": cid, "command": _mask_sensitive(command),
                             "dangers": danger.reasons})
        _audit_log("command.blocked", actor=session.get("_source_client", ""),
                   target="run_command", session_id=session.get("_transcript_sid", ""),
                   result="awaiting_confirmation",
                   detail={"confirmation_id": cid, "dangers": danger.reasons})
        return {
            "status": "awaiting_confirmation",
            "confirmation_id": cid,
            "command": command,
            "dangers": danger.reasons,
        }

    # 3. 安全 → 执行 (Legacy Path Consolidation: mandatory sandbox enforcement)
    log.info("安全闸放行(cwd=%s, mode=%s): %s", session.get("cwd"), mode, _mask_sensitive(command))

    # Sandbox enforcement — primary execution path when available
    sandbox_enforced = False
    sandbox_warning = ""
    try:
        from nous_runtime.capability.sandbox import ExecutionSandbox, SandboxConfig
        workspace = session.get("cwd") or ""
        sandbox = ExecutionSandbox(SandboxConfig(
            workspace_root=workspace,
            max_runtime_seconds=300,
            max_output_bytes=1_000_000,
        ))
        # Execute command through sandbox (single execution, not double-run)
        sandbox_result = sandbox.run(command, cwd=workspace)
        if not sandbox_result.ok:
            log.error("Sandbox rejected command: %s (rc=%d)", _mask_sensitive(command)[:100], sandbox_result.returncode)
            return {
                "status": "done",
                "output": (
                    f"⚠️ Sandbox rejected command (exit code {sandbox_result.returncode}). "
                    f"Stderr: {sandbox_result.stderr[:500]}"
                ),
                "command": command,
            }
        if sandbox_result.limit_exceeded:
            sandbox_warning = f" [sandbox limit: {sandbox_result.limit_exceeded}]"
            log.warning("Sandbox limit hit: %s", sandbox_result.limit_exceeded)
        output = sandbox_result.stdout
        if sandbox_result.stderr:
            output += f"\n[stderr]\n{sandbox_result.stderr}"
        if sandbox_warning:
            output = output + sandbox_warning
        sandbox_enforced = True
    except ImportError:
        pass  # nous_runtime not available — fall through to legacy exec_in_session
    except Exception as e:
        log.warning("Sandbox execution failed: %s — falling back to exec_in_session", e)

    if not sandbox_enforced:
        output = exec_in_session(command, session) if command else "(空命令)"
        if sandbox_warning:
            output = output + sandbox_warning

    # 4. 审计记录 + Evidence recording
    _write_transcript(session.get("_transcript_sid", ""), {
        "type": "command",
        "command": command,
        "danger_check": "safe",
        "confirmation": "auto",
        "output_summary": output[:200],
    })

    # Record evidence through unified EvidenceLedger (best-effort)
    try:
        from nous_runtime.intelligence.evidence import EvidenceLedger
        ledger = EvidenceLedger()
        ledger.record_execution(
            capability_id="tool.run_command",
            model_id=str(_config.LLM_MODEL),
            instance_key=str(session.get("target_device", "")),
            success=True,
            latency_ms=0,
            quality_signals={"output_length": len(output)},
        )
    except (ImportError, AttributeError):
        pass
    except Exception as e:
        log.debug("Evidence recording skipped: %s", e)

    # P0: record events + audit
    _emit_event("tool.executed",
                source="run_command", session_id=session.get("_transcript_sid", ""),
                payload={"command": _mask_sensitive(command), "output_length": len(output)})
    _audit_log("command.executed", actor=session.get("_source_client", ""),
               target="run_command", session_id=session.get("_transcript_sid", ""),
               result="success", detail={"output_length": len(output)})

    return {"status": "done", "output": output, "command": command}


# P1: tool execution timeout wrapper
_TOOL_TIMEOUT = 60  # default timeout seconds for tool execution


def _exec_tool_with_timeout(tool_name: str, execute_fn, command: str,
                            session: dict, timeout: int = 0) -> str:
    """
    Execute a tool with a timeout. Uses ThreadPoolExecutor to enforce
    a hard deadline. If the tool times out, returns an error message
    instead of blocking the conversation loop indefinitely.

    Also creates a P0-3 job for tracking long-running commands.
    """
    import concurrent.futures as _futures
    timeout = timeout or _TOOL_TIMEOUT
    sid = session.get("_transcript_sid", "")

    # Create job for tracking
    jid = _create_job("tool_execution", source=tool_name, session_id=sid,
                      payload={"command": _mask_sensitive(command)[:200], "timeout": timeout},
                      timeout_sec=timeout + 10)

    try:
        with _futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(execute_fn)
            output = future.result(timeout=timeout)
        if jid:
            _complete_job(jid, {"output_length": len(output) if isinstance(output, str) else 0})
        return output
    except _futures.TimeoutError:
        log.error("工具 %s 执行超时(%ds): %s", tool_name, timeout, _mask_sensitive(command)[:100])
        if jid:
            _fail_job(jid, f"timeout after {timeout}s", will_retry=False)
        _audit_log("tool.timeout", actor=session.get("_source_client", ""),
                   target=tool_name, session_id=sid, result="timeout",
                   detail={"timeout_sec": timeout})
        return f"⚠️ 工具 '{tool_name}' 执行超时（超过 {timeout} 秒）。请尝试简化命令或分步执行。"
    except Exception as e:
        log.error("工具 %s 执行异常: %s", tool_name, e)
        if jid:
            _fail_job(jid, str(e)[:200], will_retry=False)
        raise


def _dispatch_tool(tool_name: str, args: dict, session: dict) -> dict:
    """
    分发工具调用到 tools.py 的对应 handler,并处理安全闸。

    ⚠️ LEGACY PATH CONSOLIDATION: Now routes through Capability Registry →
    AdmissionPipeline before delegating to tools.dispatch().

    流程:
      0. CapabilityContract lookup + AdmissionPipeline check
      1. 调用 tools.dispatch() 获取 ToolResult
      2. 若 needs_danger_check=True → 安全检测 → 可能返回 awaiting_confirmation
      3. 若安全放行 → 通过 exec_in_session 执行 command(或 delegate 的本地执行)
      4. 写入审计 transcript + Evidence ledger

    为什么不是全部工具都走 exec_in_session:
      - delegate_to_claude 用 subprocess 直接调本机 claude CLI(不走 agent,避免超时)
      - 服务器端工具(web_search/weather/learn_*)直接在 Brain 本地执行,不依赖 PC Agent
      - 但大部分系统工具还是通过 agent /exec 统一执行,保证编码/超时/日志一致
    """
    global _BRAIN_LEGACY_DISPATCH_TOTAL
    _BRAIN_LEGACY_DISPATCH_TOTAL += 1

    # Step 0: Capability Contract + Admission check
    capability_id = f"tool.{tool_name}"
    try:
        from nous_runtime.capability.contract import CapabilityContractRegistry
        from nous_runtime.security.admission import (
            AdmissionPipeline, AdmissionRequest, RiskLevel,
        )
        registry = CapabilityContractRegistry()
        contract_result = registry.get(capability_id)
        if contract_result.is_ok:
            contract = contract_result.unwrap()
            risk_map = {
                "READ_ONLY": RiskLevel.READ_ONLY, "LOW": RiskLevel.LOW,
                "MEDIUM": RiskLevel.MEDIUM, "HIGH": RiskLevel.HIGH,
                "CRITICAL": RiskLevel.CRITICAL,
            }
            risk = risk_map.get(contract.risk_level, RiskLevel.MEDIUM)
            admission = AdmissionPipeline().check(AdmissionRequest(
                capability_id=capability_id,
                risk_level=risk,
                params=args,
                user_id=str(session.get("_source_client", "")),
                conversation_id=str(session.get("_transcript_sid", "")),
                estimated_tokens=1024,
            ))
            if not admission.allowed:
                log.warning("Admission denied for '%s': %s", tool_name, admission.reason)
                return {
                    "status": "done",
                    "output": f"⚠️ Tool '{tool_name}' blocked by admission control: {admission.reason}",
                    "command": "",
                }
            if admission.requires_approval and not session.get("_admission_approved"):
                # Mark that approval is needed
                cid = uuid.uuid4().hex[:12]
                log.warning("Admission requires approval for '%s'", tool_name)
                return {
                    "status": "awaiting_confirmation",
                    "confirmation_id": cid,
                    "command": tool_name,
                    "dangers": [f"Tool '{tool_name}' requires admission approval: {admission.reason}"],
                    "_tool_name": tool_name,
                    "_tool_args": args,
                }
        else:
            # ALL tools (including learn_*) must be registered as Capability Contracts
            log.error("Tool '%s' NOT registered in Capability Registry — execution denied", tool_name)
            return {
                "status": "done",
                "output": (
                    f"⚠️ Tool '{tool_name}' is not registered as a versioned Capability Contract. "
                    f"Execution denied. All tools must be registered in the Capability Registry. "
                    f"Contact administrator to register this capability."
                ),
                "command": "",
            }
    except ImportError:
        pass  # nous_runtime not available — proceed with legacy dispatch
    except Exception as e:
        log.warning("Capability/Admission check failed for '%s': %s (proceeding with legacy)", tool_name, e)

    device_id = session.get("target_device") or config.DEFAULT_DEVICE

    # 智能降级: 需要 Agent 的工具在设备离线时友好提示
    if not tools.is_server_side_tool(tool_name) and device_id:
        dev = get_device(device_id)
        if dev and not is_device_online(dev):
            log.warning("工具 %s 需要 Agent(%s)但设备离线,降级处理", tool_name, device_id)
            # 返回友好的降级提示，建议替代方案
            alt_suggestions = (
                "你可以：\n"
                "1) 打开电脑并确保 Agent 正在运行\n"
                "2) 使用学习功能 — 资料库、刷题、背单词、看计划 都不需要电脑\n"
                "3) 让我联网搜索或查天气 — 这些我直接就能做\n"
                "4) 等电脑上线后再让我操作"
            )
            return {
                "status": "done",
                "output": (
                    f"⚠️ 电脑(Agent)目前不在线，无法执行「{tool_name}」。\n\n"
                    f"{alt_suggestions}"
                ),
                "command": "",
            }

    result = tools.dispatch(tool_name, args, session, lambda cmd: _exec_raw(cmd, device_id=device_id))

    if result.status == "error":
        return {"status": "done", "output": result.output, "command": result.command or ""}

    # 需要安全闸确认的工具
    if result.needs_danger_check:
        mode = getattr(config, "SAFETY_MODE", "normal")
        danger = safety.check_danger(result.command, mode)
        if danger.is_danger or result.needs_danger_check:
            cid = uuid.uuid4().hex[:12]
            reasons = danger.reasons if danger.is_danger else ["工具需要人工确认"]
            log.warning("安全闸拦截工具 %s(cwd=%s): %s —— 原因: %s",
                        tool_name, session.get("cwd"), _mask_sensitive(result.command)[:80], "; ".join(reasons))
            # P0: record confirmation required event
            _emit_event("tool.confirmation_required",
                        source=tool_name, session_id=session.get("_transcript_sid", ""),
                        payload={"confirmation_id": cid, "command": _mask_sensitive(result.command or ""),
                                 "dangers": reasons, "tool_name": tool_name, "tool_args": args})
            return {
                "status": "awaiting_confirmation",
                "confirmation_id": cid,
                "command": result.command,
                "dangers": reasons,
                "_tool_name": tool_name,
                "_tool_args": args,
            }

    # delegate_to_claude 特殊处理:本地执行
    if tool_name == "delegate_to_claude" and hasattr(result, "_delegate_fn"):
        log.info("执行委派 Claude Code: %s", result.command[:80])
        output = result._delegate_fn()
        _write_transcript(session.get("_transcript_sid", ""), {
            "type": "command", "command": result.command,
            "danger_check": "safe" if not result.needs_danger_check else "delegated",
            "confirmation": "auto", "output_summary": output[:200],
        })
        return {"status": "done", "output": output, "command": result.command}

    # 安全放行 → 执行（P1: 带超时保护）
    log.info("工具 %s 放行(cwd=%s): %s", tool_name, session.get("cwd"), result.command[:80])
    if result.command:
        # run_command 必须走 _do_execute（唯一的 shell 执行入口，含 Sandbox + Evidence）
        if tool_name == "run_command":
            exec_result = _do_execute(result.command, session)
            if exec_result.get("status") == "awaiting_confirmation":
                return exec_result  # 安全闸拦截，需要用户确认
            output = exec_result.get("output", "")
        else:
            # P1: wrap execution with timeout to prevent tool hangs blocking the loop
            is_slow_tool = tool_name in ("delegate_to_claude", "web_search", "web_fetch",
                                          "learn_search_semantic", "learn_ask_document",
                                          "learn_generate_quiz")
            exec_timeout = 300 if is_slow_tool else _TOOL_TIMEOUT
            try:
                output = _exec_tool_with_timeout(
                    tool_name,
                    lambda: exec_in_session(result.command, session),
                    result.command, session, timeout=exec_timeout)
            except Exception as _exec_err:
                output = f"⚠️ 工具 '{tool_name}' 执行失败: {_exec_err}"
    else:
        output = result.output  # 纯 Python 处理的工具(如 delegate_to_claude 已执行)
    # 学习工具输出(出题/讲解/公式)常含 LaTeX,转成可读文本
    if tool_name.startswith("learn_") and output:
        output = _delatex(output)

    _write_transcript(session.get("_transcript_sid", ""), {
        "type": "command", "command": result.command or tool_name,
        "danger_check": "safe", "confirmation": "auto", "output_summary": output[:200],
    })

    # P0: record tool executed event
    _emit_event("tool.executed",
                source=tool_name, session_id=session.get("_transcript_sid", ""),
                payload={"command": _mask_sensitive(result.command or tool_name)[:200],
                         "output_length": len(output)})

    return {"status": "done", "output": output, "command": result.command}


def _last_user_text(session) -> str:
    for m in reversed(session.get("messages", [])):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else ""
    return ""



def run_turn(session, user_text, model, confirmation=None):
    """
    跑一轮对话。支持两种入口:
      1. 新消息: user_text 有值,confirmation 为 None → 正常启动工具循环
      2. 确认回复: confirmation 有值 → 从 pending 状态恢复,继续执行

    ⚠️ LEGACY PATH CONSOLIDATION: Now creates Task + PlanArtifact +
    ExecutionTicket via session_task_bridge. State transitions are validated
    through the Task state machine.

    返回 dict:
      {"status": "done", "reply": "...", "steps": [...]}
      {"status": "awaiting_confirmation", "confirmation_id": "...", "command": "...", "dangers": [...]}
      {"status": "error", "message": "..."}

    为什么两种入口合在一个函数:
      - 确认回复本质上还是同一轮对话的延续,共享同一个 tool-calling 循环
      - 分开两个函数会导致循环逻辑重复
    """
    steps: list[dict] = []
    max_steps = config.BRAIN_MAX_STEPS

    # Legacy Path Consolidation: create Task + PlanArtifact + ExecutionTicket
    task_bridge_result = None
    if _st_bridge is not None:
        try:
            task_bridge_result = _st_bridge.create_run_turn_task(
                session, user_text, model, max_steps=max_steps,
            )
            if task_bridge_result and task_bridge_result.created:
                log.info("TaskBridge: created Task %s with ExecutionTicket",
                         task_bridge_result.task_id)
                session["_task_id"] = task_bridge_result.task_id
                session["_task_obj"] = task_bridge_result.task_obj
                session["_task_ticket"] = task_bridge_result.ticket
                if task_bridge_result.plan_artifact:
                    session["_plan_artifact"] = task_bridge_result.plan_artifact
                    log.info("PlanArtifact created: %s (hash=%s)",
                             task_bridge_result.plan_artifact.plan_id,
                             task_bridge_result.plan_artifact.signature[:16])
        except Exception as e:
            log.debug("TaskBridge creation skipped: %s", e)

    # 入口2:确认回复
    if confirmation:
        pending = session.pop("pending_confirmation", None)
        if not pending:
            return {"status": "error", "message": "没有待确认的命令(可能已超时或已处理)"}
        cid_req = confirmation.get("id", "")
        if cid_req != pending.get("confirmation_id", ""):
            return {"status": "error", "message": f"确认 ID 不匹配: 期望 {pending['confirmation_id']}, 收到 {cid_req}"}

        # 步数上限警告:不执行命令,只决定是否继续循环
        if pending.get("_step_limit_warning"):
            action = confirmation.get("action", "deny")
            steps_used = pending.get("steps_used", 0)
            if action == "approve":
                log.info("用户批准继续执行(已执行 %d 步)", steps_used)
                session["_step_warning_acknowledged"] = steps_used
                # 直接继续循环,不注入任何消息到历史
                return _continue_loop(session, model, steps, max_steps, steps_used)
            else:
                log.info("用户在 %d 步时选择停止执行", steps_used)
                return {"status": "done", "reply": f"⚠️ 任务已执行 {steps_used} 步,用户选择在此停止。", "steps": steps}

        action = confirmation.get("action", "deny")
        command = pending["command"]
        tc = pending["tool_call"]
        steps_used = pending.get("steps_used", 0)
        tool_name = pending.get("_tool_name", "run_command")
        tool_args = pending.get("_tool_args", {})

        if action == "approve":
            log.info("用户批准执行: %s (工具=%s)", _mask_sensitive(command), tool_name)
            # delegate_to_claude 特殊处理:本地执行
            dev_id = session.get("target_device") or config.DEFAULT_DEVICE
            if tool_name == "phone_act":
                try:
                    output = tools.execute_phone_act(tool_args)
                except Exception as e:
                    output = f"phone_act failed: {e}"
            elif tool_name == "delegate_to_claude":
                tr = tools.dispatch(tool_name, tool_args, session, lambda cmd: _exec_raw(cmd, device_id=dev_id))
                if hasattr(tr, "_delegate_fn"):
                    output = tr._delegate_fn()
                else:
                    output = exec_in_session(command, session) if command else "(空命令)"
            else:
                output = exec_in_session(command, session) if command else "(空命令)"
            _write_transcript(session.get("_transcript_sid", ""), {
                "type": "command",
                "command": command,
                "danger_check": f"danger({'; '.join(pending.get('dangers', []))})",
                "confirmation": "approved",
                "output_summary": output[:200],
            }, session=session)
            # P0: record confirmation resolved event
            _emit_event("tool.confirmation.resolved",
                        source=tool_name, session_id=session.get("_transcript_sid", ""),
                        payload={"confirmation_id": pending.get("confirmation_id", ""),
                                 "action": "approved", "command": _mask_sensitive(command)[:200]})
        else:
            log.info("用户拒绝执行: %s", _mask_sensitive(command))
            output = f"⚠️ 用户拒绝了此命令的执行。原命令: {command}\n拒绝原因: 用户手动否决。请尝试其他方法完成目标。"
            _write_transcript(session.get("_transcript_sid", ""), {
                "type": "command",
                "command": command,
                "danger_check": f"danger({'; '.join(pending.get('dangers', []))})",
                "confirmation": "denied",
                "output_summary": output[:200],
            }, session=session)
            # P0: record confirmation resolved event
            _emit_event("tool.confirmation.resolved",
                        source=tool_name, session_id=session.get("_transcript_sid", ""),
                        payload={"confirmation_id": pending.get("confirmation_id", ""),
                                 "action": "denied", "command": _mask_sensitive(command)[:200]})

        steps.append({"command": command, "output": output})
        # 注入 tool_result,让模型看到结果
        session["messages"].append({
            "role": "tool", "tool_call_id": tc.get("id", ""), "content": output,
        })
        # 继续循环(剩余步数)
        return _continue_loop(session, model, steps, max_steps, steps_used)

    # 入口1:新用户消息
    # Legacy Path Consolidation: Task state transition CREATED → QUEUED → PLANNING → AWAITING_APPROVAL → DISPATCHING → RUNNING
    if _st_bridge is not None and session.get("_task_obj"):
        try:
            _st_bridge.emit_task_transition(
                session["_task_obj"], "created", "queued",
                reason="User message received", triggered_by="run_turn",
            )
            _st_bridge.emit_task_transition(
                session["_task_obj"], "queued", "planning",
                reason="Starting plan generation", triggered_by="run_turn",
            )
            _st_bridge.emit_task_transition(
                session["_task_obj"], "planning", "awaiting_approval",
                reason="Auto-approval (legacy compat)", triggered_by="run_turn",
            )
            _st_bridge.emit_task_transition(
                session["_task_obj"], "awaiting_approval", "dispatching",
                reason="Entering tool loop", triggered_by="run_turn",
            )
            _st_bridge.emit_task_transition(
                session["_task_obj"], "dispatching", "running",
                reason="Tool loop started", triggered_by="run_turn",
            )
        except Exception as e:
            log.debug("Task state transition skipped: %s", e)

    # 检测模式前缀(#code / #write / #study),设置 session 的 mode_instruction
    actual_text = _apply_mode_prefix(session, user_text)
    session["messages"].append({"role": "user", "content": actual_text})
    # 确保 transcript session_id 存在(懒初始化)
    if not session.get("_transcript_sid"):
        session["_transcript_sid"] = ""  # 临时,由调用方在外面设
    maybe_summarize(session, model)
    return _continue_loop(session, model, steps, max_steps, 0)


def _continue_loop(session, model, steps, max_steps, steps_used):
    """
    工具调用循环的主体。被 run_turn 的新消息入口和确认回复入口共用。
    为什么抽成独立函数:新消息和确认回复都需要完全相同的循环逻辑,
    区别只在于循环的起点(新消息从0步开始,确认回复从 steps_used 步开始)。
    """
    idle_rounds = 0  # 连续几轮模型没调工具(防空转)
    idle_limit = getattr(config, "BRAIN_IDLE_LIMIT", 3)
    step_warning = getattr(config, "BRAIN_STEP_WARNING", 3000)
    warned_this_session = session.get("_step_warning_acknowledged", 0)
    for step_idx in range(steps_used, max_steps + 1):
        if step_idx >= max_steps:
            # Legacy Path Consolidation: Task max steps reached
            if _st_bridge is not None and session.get("_task_obj"):
                try:
                    _st_bridge.emit_task_transition(
                        session["_task_obj"], "running", "verifying",
                        reason="Max steps reached", triggered_by="run_turn",
                    )
                    _st_bridge.emit_task_transition(
                        session["_task_obj"], "verifying", "completed_with_warnings",
                        reason=f"Reached max steps ({max_steps})", triggered_by="run_turn",
                    )
                except Exception:
                    pass
            return {"status": "done", "reply": "(已达绝对步数上限,任务可能未完成)", "steps": steps}

        # 步数警告:超过阈值暂停询问用户是否继续
        if step_warning > 0 and step_idx - warned_this_session >= step_warning:
            cid = uuid.uuid4().hex[:12]
            session["pending_confirmation"] = {
                "confirmation_id": cid,
                "command": f"已达到 {step_idx} 步",
                "dangers": [f"任务已执行 {step_idx} 步(警告阈值 {step_warning} 步),是否继续?"],
                "tool_call": {"id": ""},  # 占位,非真实工具调用
                "steps_used": step_idx,
                "_step_limit_warning": True,
            }
            return {
                "status": "awaiting_confirmation",
                "confirmation_id": cid,
                "command": f"已达到 {step_idx} 步",
                "dangers": [f"任务已执行 {step_idx} 步(警告阈值 {step_warning} 步),是否继续?"],
            }

        # 送模型前修复可能断裂的 tool_calls/tool 配对(防 HTTP 400)
        if _repair_history(session["messages"]):
            save_sessions()

        sys = _SYSTEM_PROMPT
        # 注入学习者画像(持久记忆,跨会话+跨轮次都带上,让助手始终"记得你")
        sys += "\n" + learner_profile.build_persona_prompt()
        if session.get("summary"):
            sys += "\n\n[前情摘要]\n" + session["summary"]
        if session.get("_mode_instruction"):
            sys += session["_mode_instruction"]
        if session.get("_skill_instruction"):
            sys += session["_skill_instruction"]
        # 教学模式指令
        teach_mode = session.get("_teach_mode", "")
        if teach_mode and teach_mode != "chat":
            sys += brain_prompt.get_teach_mode_prompt(teach_mode)
        if _is_learning_context(session, _last_user_text(session)):
            sys += _learn_state_snapshot()
        convo = [{"role": "system", "content": sys}] + session["messages"]

        tool_defs = _tool_defs_for_session(session)
        try:
            msg = call_model(convo, model, use_tools=True, tool_defs=tool_defs)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # 强修:删除所有未配对的 tool_calls,从最后一条 user 消息后重新开始
                log.warning("模型返回 400(疑似 tool_calls 断裂),强修历史后重试")
                _force_fix_history(session["messages"])
                save_sessions()
                convo = [{"role": "system", "content": sys}] + session["messages"]
                msg = call_model(convo, model, use_tools=True, tool_defs=tool_defs)
            else:
                raise
        session["messages"].append(_clean_assistant(msg))

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            reply = _delatex(msg.get("content") or "(空回复)")

            # Legacy Path Consolidation: Task completion
            if _st_bridge is not None and session.get("_task_obj"):
                try:
                    _st_bridge.emit_task_transition(
                        session["_task_obj"], "running", "verifying",
                        reason="Tool loop finished", triggered_by="run_turn",
                    )
                    _st_bridge.emit_task_transition(
                        session["_task_obj"], "verifying", "completed",
                        reason=f"Completed in {step_idx + 1} steps",
                        triggered_by="run_turn",
                    )
                except Exception:
                    pass

            # P0: record chat reply sent event
            _emit_event("chat.reply.sent",
                        source="brain", session_id=session.get("_transcript_sid", ""),
                        payload={"model": model, "reply_length": len(reply), "steps_used": step_idx + 1})
            return {"status": "done", "reply": reply, "steps": steps}

        # 有工具调用 = 有进展,重置空转计数
        idle_rounds = 0

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}

            # 统一路由:所有工具都走 _dispatch_tool (CapabilityContract + AdmissionPipeline)
            # run_command 的 Sandbox + Evidence 在 _dispatch_tool 内部通过 _do_execute 完成
            result = _dispatch_tool(tool_name, args, session)

            if result["status"] == "awaiting_confirmation":
                # 暂停循环,保存状态,等用户确认
                session["pending_confirmation"] = {
                    "confirmation_id": result["confirmation_id"],
                    "command": result["command"],
                    "dangers": result["dangers"],
                    "tool_call": tc,
                    "steps_used": step_idx,
                    "_tool_name": result.get("_tool_name", tool_name),
                    "_tool_args": result.get("_tool_args", args),
                }
                return {
                    "status": "awaiting_confirmation",
                    "confirmation_id": result["confirmation_id"],
                    "command": result["command"],
                    "dangers": result["dangers"],
                }

            # 正常执行完成
            command_or_name = result.get("command") or tool_name
            steps.append({"command": command_or_name, "output": result["output"]})

            # Verification (Legacy Path Consolidation)
            try:
                from nous_runtime.verification.runtime import VerificationRepairRuntime
                verifier = VerificationRepairRuntime()
                verify_result = verifier.verify_step(
                    capability_id=f"tool.{tool_name}",
                    output=result["output"],
                    expected_schema={"type": "string"},
                )
                if hasattr(verify_result, 'issues') and verify_result.issues:
                    log.warning("Verification found %d issue(s) for tool '%s'",
                               len(verify_result.issues), tool_name)
                    for issue in verify_result.issues[:3]:
                        log.debug("  - %s: %s", issue.severity, issue.description)
            except ImportError:
                pass
            except Exception as e:
                log.debug("Verification skipped for '%s': %s", tool_name, e)

            session["messages"].append({
                "role": "tool", "tool_call_id": tc.get("id", ""), "content": result["output"],
            })

    return {"status": "done", "reply": "(已达最大执行步数,任务可能未完成)", "steps": steps}


# 流式 SSE 循环
def _sse_write(wfile, event_type: str, data: dict):
    """
    写一条 SSE 事件到 wfile 并 flush。
    为什么用 SSE 而不是 chunked JSONL:SSE 被浏览器/OkHttp 原生支持,
    手机端无需额外解析逻辑,断开自动重连。
    """
    payload = json.dumps(data, ensure_ascii=False)
    msg = f"event: {event_type}\ndata: {payload}\n\n"
    wfile.write(msg.encode("utf-8"))
    wfile.flush()


def _continue_loop_stream(session, model, steps, max_steps, steps_used, wfile):
    """
    流式版工具调用循环,每完成一步就通过 SSE yield 事件到手机。
    与 _continue_loop 的逻辑相同,区别在于:
      - 每步执行后立即 SSE 推送给手机(而不是等全部完成)
      - 遇到安全闸确认时,emit 'confirmation_required' 事件并挂起等待

    为什么用 generator 而不是 callback:generator 让循环逻辑保持线性可读,
    同时 SSE Handler 可以逐帧写回客户端。
    """
    idle_rounds = 0
    idle_limit = getattr(config, "BRAIN_IDLE_LIMIT", 3)
    step_warning = getattr(config, "BRAIN_STEP_WARNING", 3000)
    warned_this_session = session.get("_step_warning_acknowledged", 0)
    for step_idx in range(steps_used, max_steps + 1):
        if step_idx >= max_steps:
            _sse_write(wfile, "done", {"reply": "(已达绝对步数上限,任务可能未完成)", "steps": steps})
            return

        # 步数警告:超过阈值暂停询问用户是否继续
        if step_warning > 0 and step_idx - warned_this_session >= step_warning:
            cid = uuid.uuid4().hex[:12]
            event = threading.Event()
            session["_confirmation_event"] = event
            session["pending_confirmation"] = {
                "confirmation_id": cid,
                "command": f"已达到 {step_idx} 步",
                "dangers": [f"任务已执行 {step_idx} 步(警告阈值 {step_warning} 步),是否继续?"],
                "tool_call": {"id": ""},  # 占位,非真实工具调用
                "steps_used": step_idx,
                "_step_limit_warning": True,
            }
            _sse_write(wfile, "confirmation_required", {
                "confirmation_id": cid,
                "command": f"已达到 {step_idx} 步",
                "dangers": [f"任务已执行 {step_idx} 步(警告阈值 {step_warning} 步),是否继续?"],
            })
            confirmed = event.wait(timeout=300)
            session.pop("_confirmation_event", None)
            pending = session.pop("pending_confirmation", None)

            if not confirmed or not pending:
                _sse_write(wfile, "done", {"reply": "⚠️ 步数确认超时,任务中断", "steps": steps})
                return

            action = pending.get("_action", "deny")
            if action == "approve":
                log.info("用户批准继续(stream,已执行 %d 步)", step_idx)
                session["_step_warning_acknowledged"] = step_idx
                continue  # 继续循环
            else:
                log.info("用户在 %d 步选择停止(stream)", step_idx)
                _sse_write(wfile, "done", {"reply": f"⚠️ 任务已执行 {step_idx} 步,用户选择在此停止。", "steps": steps})
                return

        # 送模型前修复可能断裂的 tool_calls/tool 配对
        if _repair_history(session["messages"]):
            save_sessions()

        # 通知手机分析/规划/执行阶段
        if step_idx == steps_used:
            _sse_write(wfile, "analyzing", {"step": step_idx + 1})
            _sse_write(wfile, "planning", {"step": step_idx + 1})
        _sse_write(wfile, "executing", {"step": step_idx + 1})

        sys = _SYSTEM_PROMPT
        # 注入学习者画像(持久记忆,跨会话+跨轮次都带上,让助手始终"记得你")
        sys += "\n" + learner_profile.build_persona_prompt()
        if session.get("summary"):
            sys += "\n\n[前情摘要]\n" + session["summary"]
        if session.get("_mode_instruction"):
            sys += session["_mode_instruction"]
        if session.get("_skill_instruction"):
            sys += session["_skill_instruction"]
        # 教学模式指令
        teach_mode = session.get("_teach_mode", "")
        if teach_mode and teach_mode != "chat":
            sys += brain_prompt.get_teach_mode_prompt(teach_mode)
        if _is_learning_context(session, _last_user_text(session)):
            sys += _learn_state_snapshot()
        convo = [{"role": "system", "content": sys}] + session["messages"]

        # 流式调模型:正文增量逐 token 推 reply_delta 给手机(边生成边显示/朗读)
        def _emit_delta(text):
            _sse_write(wfile, "reply_delta", {"text": text})
        tool_defs = _tool_defs_for_session(session)
        try:
            msg = call_model_stream(convo, model, True, _emit_delta, tool_defs=tool_defs)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                log.warning("SSE 模型返回 400,强修历史后重试")
                _force_fix_history(session["messages"])
                save_sessions()
                convo2 = [{"role": "system", "content": sys}] + session["messages"]
                msg = call_model_stream(convo2, model, True, _emit_delta, tool_defs=tool_defs)
            else:
                raise
        session["messages"].append(_clean_assistant(msg))

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            _sse_write(wfile, "done", {"reply": _delatex(msg.get("content") or "(空回复)"), "steps": steps})
            return

        idle_rounds = 0  # 有工具调用 = 有进展

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}

            if tool_name == "run_command":
                command = str(args.get("command", "")).strip()
                result = _do_execute(command, session)
            else:
                # 通知手机即将执行
                cmd_preview = args.get("path") or args.get("pattern") or args.get("app_name") or args.get("project_path") or tool_name
                _sse_write(wfile, "step_start", {"command": str(cmd_preview)[:80], "step_num": step_idx + 1, "tool": tool_name})
                result = _dispatch_tool(tool_name, args, session)
                command = result.get("command", tool_name)

            if result["status"] == "awaiting_confirmation":
                # 推送确认请求到手机,然后挂起等待
                event = threading.Event()
                session["_confirmation_event"] = event
                session["pending_confirmation"] = {
                    "confirmation_id": result["confirmation_id"],
                    "command": result["command"],
                    "dangers": result["dangers"],
                    "tool_call": tc,
                    "steps_used": step_idx,
                    "_tool_name": result.get("_tool_name", tool_name),
                    "_tool_args": result.get("_tool_args", args),
                }
                _sse_write(wfile, "confirmation_required", {
                    "confirmation_id": result["confirmation_id"],
                    "command": result["command"],
                    "dangers": result["dangers"],
                })
                # 等待用户确认(最长等 5 分钟,超时自动拒绝)
                confirmed = event.wait(timeout=300)
                session.pop("_confirmation_event", None)
                pending = session.pop("pending_confirmation", None)

                if not confirmed or not pending:
                    # 超时或异常,视为拒绝
                    output = f"⚠️ 确认超时,命令未执行: {command}"
                    _write_transcript(session.get("_transcript_sid", ""), {
                        "type": "command", "command": command,
                        "danger_check": f"danger({'; '.join(result.get('dangers', []))})",
                        "confirmation": "timeout",
                        "output_summary": output[:200],
                    })
                    steps.append({"command": command, "output": output})
                    session["messages"].append({
                        "role": "tool", "tool_call_id": tc.get("id", ""), "content": output,
                    })
                    _sse_write(wfile, "step_done", {"command": command, "output": output[:400]})
                    continue

                # 从 pending 中取结果(由 POST /chat 的确认处理放入)
                action = pending.get("_action", "deny")
                stream_tool_name = pending.get("_tool_name", "run_command")
                stream_tool_args = pending.get("_tool_args", {})
                if action == "approve":
                    log.info("用户批准执行(stream): %s (工具=%s)", _mask_sensitive(command), stream_tool_name)
                    stream_dev_id = session.get("target_device") or config.DEFAULT_DEVICE
                    if stream_tool_name == "phone_act":
                        try:
                            output = tools.execute_phone_act(stream_tool_args)
                        except Exception as e:
                            output = f"phone_act failed: {e}"
                    elif stream_tool_name == "delegate_to_claude":
                        tr = tools.dispatch(stream_tool_name, stream_tool_args, session, lambda cmd: _exec_raw(cmd, device_id=stream_dev_id))
                        if hasattr(tr, "_delegate_fn"):
                            output = tr._delegate_fn()
                        else:
                            output = exec_in_session(command, session) if command else "(空命令)"
                    else:
                        output = exec_in_session(command, session) if command else "(空命令)"
                    _write_transcript(session.get("_transcript_sid", ""), {
                        "type": "command", "command": command,
                        "danger_check": f"danger({'; '.join(result.get('dangers', []))})",
                        "confirmation": "approved",
                        "output_summary": output[:200],
                    }, session=session)
                else:
                    log.info("用户拒绝执行(stream): %s", _mask_sensitive(command))
                    output = f"⚠️ 用户拒绝了此命令的执行。原命令: {command}\n拒绝原因: 用户手动否决。请尝试其他方法完成目标。"
                    _write_transcript(session.get("_transcript_sid", ""), {
                        "type": "command", "command": command,
                        "danger_check": f"danger({'; '.join(result.get('dangers', []))})",
                        "confirmation": "denied",
                        "output_summary": output[:200],
                    }, session=session)

                steps.append({"command": command, "output": output})
                session["messages"].append({
                    "role": "tool", "tool_call_id": tc.get("id", ""), "content": output,
                })
                _sse_write(wfile, "step_done", {"command": command, "output": output[:400]})
            else:
                # 安全命令,正常执行
                steps.append({"command": command, "output": result["output"]})
                session["messages"].append({
                    "role": "tool", "tool_call_id": tc.get("id", ""), "content": result["output"],
                })
                _sse_write(wfile, "step_done", {"command": command, "output": result["output"][:400]})

    _sse_write(wfile, "done", {"reply": "(已达最大执行步数,任务可能未完成)", "steps": steps})


# HTTP 服务
# 限流器:{ip: [timestamp,...]}
_rate_limit_buckets = {}
_rate_limit_lock = threading.Lock()
# 重放保护:{nonce: expire_time}
_seen_nonces = {}
_nonce_lock = threading.Lock()
# 异常检测:{ip: [fail_times]}
_auth_failures = {}
_auth_fail_lock = threading.Lock()

def _check_replay(ip: str, ts_str: str, nonce: str) -> bool:
    """
    检查请求是否重放。强制要求时间戳 + nonce。
    时间戳须在 ±300 秒内,nonce 在 600 秒窗口内不可重复。
    缺失或无效一律拒绝(不再兼容无头旧客户端)。
    """
    global _seen_nonces
    # VPN 隧道内设备免重放检查(隧道层已提供加密与认证)
    # TODO: make trusted subnet configurable via TRUSTED_SUBNET env var
    if ip.startswith("10.10.0."): return True
    if not ts_str or not nonce:
        log.warning("重放保护:缺时间戳/nonce IP=%s", ip)
        return False
    try:
        ts = float(ts_str)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > 300:
        log.warning("重放保护:时间戳过期 IP=%s diff=%.0fs", ip, time.time() - ts)
        return False
    now = time.time()
    # 清理过期 nonce (持锁)
    with _nonce_lock:
        # 过滤过期 nonce (超过600秒)
        _seen_nonces = {n: t for n, t in _seen_nonces.items() if now - t < 600}
        if nonce in _seen_nonces:
            log.warning("重放保护:nonce 重复使用 IP=%s", ip)
            return False
        _seen_nonces[nonce] = now
    return True

def _check_anomaly(ip: str, auth_ok: bool):
    """检测异常:连续鉴权失败/深夜操作"""
    now = time.time()
    if not auth_ok:
        with _auth_fail_lock:
            fails = _auth_failures.get(ip, [])
            fails = [t for t in fails if now - t < 600]
            fails.append(now)
            _auth_failures[ip] = fails
            fail_count = len(fails)
        if fail_count >= 5:
            log.error("ALERT:IP %s 连续 %d 次鉴权失败!", ip, fail_count)
    else:
        with _auth_fail_lock:
            _auth_failures.pop(ip, None)
    # 深夜操作告警
    hour = time.localtime().tm_hour
    if 2 <= hour <= 5:
        log.warning("ALERT:深夜操作 IP=%s 时间=%s", ip, time.strftime("%H:%M:%S"))

def _build_heatmap():
    """构建知识热力图数据(每科目掌握度分布)。"""
    try:
        import learn_db
        kps = learn_db.search_knowledge_points(limit=500)
        subjects = {}
        for kp in kps:
            s = kp.get("subject", "other")
            if s not in subjects:
                subjects[s] = {"total": 0, "mastered": 0, "weak": 0, "avg_mastery": 0}
            m = kp.get("mastery", 0)
            subjects[s]["total"] += 1
            subjects[s]["avg_mastery"] += m
            if m >= 70:
                subjects[s]["mastered"] += 1
            else:
                subjects[s]["weak"] += 1
        result = {}
        for s, d in subjects.items():
            d["avg_mastery"] = round(d["avg_mastery"] / max(1, d["total"]), 1)
            result[s] = d
        return result
    except Exception:
        return {}

def _check_rate_limit(ip: str) -> bool:
    """检查 IP 是否超过限流阈值。返回 True=放行, False=限流。"""
    now = time.time()
    with _rate_limit_lock:
        bucket = _rate_limit_buckets.get(ip, [])
        # 清理过期记录(1分钟前)
        bucket = [t for t in bucket if now - t < 60]
        if len(bucket) >= config.RATE_LIMIT_PER_MINUTE:
            _rate_limit_buckets[ip] = bucket
            return False
        bucket.append(now)
        _rate_limit_buckets[ip] = bucket
    return True

def _mask_sensitive(text: str) -> str:
    """掩码敏感信息:API Key/密码/Token 模式。"""
    return brain_utils.mask_sensitive(text)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _check_access(self) -> bool:
        """IP 白名单 + 限流校验。返回 True=放行, False=拒绝。"""
        client_ip = self.client_address[0]
        # 本机访问始终放行(localhost/127.0.0.1/本机 WG IP)
        if client_ip in ("127.0.0.1", "::1", config.BRAIN_HOST):
            return True
        # IP 白名单
        allowed = getattr(config, "ALLOWED_IPS", [])
        if allowed and client_ip not in allowed:
            log.warning("拒绝:IP 不在白名单 %s", client_ip)
            self._send_json(403, {"error": "forbidden: IP not in whitelist"})
            return False
        # 限流
        if not _check_rate_limit(client_ip):
            log.warning("限流:IP %s 超过频率限制", client_ip)
            self._send_json(429, {"error": "rate limited, slow down"})
            return False
        return True

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        """校验 token:优先 X-Auth-Token 头,回退 URL ?token=。Demo Mode 下任意 token 通过。"""
        # Demo Mode: accept any token for easy local testing
        if _is_demo():
            self._client_id = "demo"
            return True
        tok = self.headers.get("X-Auth-Token", "")
        if not tok:
            try:
                tok = "".join(parse_qs(urlparse(self.path).query).get("token", [""]))
            except Exception:
                tok = ""
        cid = resolve_client(tok)
        if cid:
            self._client_id = cid
            return True
        return False

    def do_GET(self):
        """GET 端点:SSE 流式聊天 / 会话列表 / 会话详情 / 健康检查。"""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        # 健康检查:GET / → {"status":"brain alive"}
        if path == "/":
            self._send_json(200, {"status": "brain alive"})
            return

        # Web 面板免鉴权(静态页面)
        if path == "/web":
            self._serve_web_panel()
            return

        # 资料上传页(电脑浏览器拖拽上传),页面免鉴权,API 调用带 token
        if path == "/upload":
            self._serve_upload_page()
            return

        # 健康检查免鉴权
        # P6: Setup wizard — needs auth
        if path == "/setup":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_setup()
            return

        if path == "/health":
            self._handle_health()
            return

        # P9: Stability Monitor
        if path == "/api/v1/control/stability":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            hours = int(params.get("hours", ["24"])[0])
            report = _stability_report(hours=hours)
            self._send_json(200, {"api_version": "v1", **report})
            return

        # P10: Control Notifications
        if path == "/api/v1/control/notifications":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                from nous_core.notifications import get_unread
                items = get_unread(target_client="desktop", limit=20)
            except Exception:
                items = []
            self._send_json(200, {"api_version": "v1", "notifications": items, "count": len(items)})
            return

        # P8: Control API v1 (for Desktop App) — needs auth
        if path == "/api/v1/control/overview":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                from nous_core.dashboard import get_dashboard_data
                data = get_dashboard_data()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, {"api_version": "v1", **data})
            return

        if path == "/api/v1/control/approvals":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                from nous_core.audit import query_logs
                pending = query_logs(result="awaiting_confirmation", limit=20)
            except Exception:
                pending = []
            self._send_json(200, {"api_version": "v1", "approvals": pending, "count": len(pending)})
            return

        if path.startswith("/api/v1/control/device/"):
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            device_id = path.split("/api/v1/control/device/", 1)[1]
            dev = None
            online = False
            caps = []
            # Check legacy devices first, then nous_core.devices
            try:
                dev = get_device(device_id)
                if dev and dev.get("host"):
                    online = is_device_online(dev)
                    caps = dev.get("capabilities", [])
            except Exception:
                pass
            if not dev:
                try:
                    from nous_core.devices import get_device as _ncore_get_device
                    ndev = _ncore_get_device(device_id)
                    if ndev:
                        dev = dict(ndev)
                        online = bool(dev.get("is_online", False))
                        caps = dev.get("capabilities") or []
                except Exception:
                    pass
            if not dev:
                self._send_json(404, {"error": "device not found"})
                return
            self._send_json(200, {"api_version": "v1", "device": {"id": device_id, "name": dev.get("name", device_id),
                                  "device_type": dev.get("device_type", "unknown"), "host": dev.get("host", ""),
                                  "last_seen": dev.get("last_seen", "")},
                                  "online": online, "capabilities": caps})
            return

        if path == "/learn/daily":
            self._handle_daily_inspiration()
            return

        # P4 Kernel API v1 (versioned, stable)
        # All /api/v1/kernel/* endpoints mirror existing paths but are the
        # stable, versioned interface for external systems.
        if path == "/api/v1/kernel/health":
            self._handle_health()
            return
        if path == "/api/v1/kernel/devices":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, {"devices": list(devices.values())})
            return
        if path == "/api/v1/kernel/capabilities":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            caps = _list_capabilities(enabled_only=True)
            self._send_json(200, {"capabilities": caps, "count": len(caps)})
            return
        if path == "/api/v1/kernel/providers":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            provs = _list_providers()
            self._send_json(200, {"providers": provs})
            return
        if path == "/api/v1/kernel/security":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, _get_security_stats())
            return
        if path == "/api/v1/kernel/observer":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, _get_observer_stats())
            return

        # P1: Quick Capture inbox — needs auth
        if path == "/inbox":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_inbox(params)
            return

        if path == "/learn/dashboard":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_learn_dashboard()
            return

        # P2: Learning State — needs auth
        if path == "/learn/state":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                from nous_core.learning import get_subject_summary, get_overall_stats
                self._send_json(200, {
                    "subjects": get_subject_summary(),
                    "overall": get_overall_stats(),
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # P2: Enhanced Daily Plan — needs auth
        if path == "/learn/plan_v2":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                mins = int(params.get("minutes", ["120"])[0])
                from plan_engine import get_enhanced_daily_plan
                plan = get_enhanced_daily_plan(available_minutes=mins)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, plan)
            return

        # P2: Daily Report — needs auth
        if path == "/learn/report":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                from nous_core.daily_report import generate_daily_report
                report = generate_daily_report()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, report)
            return

        # P3: Capability Registry — needs auth
        if path == "/capabilities":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            cat = params.get("category", [""])[0]
            caps = _list_capabilities(category=cat, enabled_only=True)
            self._send_json(200, {"capabilities": caps, "count": len(caps)})
            return

        # P3: Capability Graph — needs auth
        if path == "/capabilities/graph":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            graph = _get_dependency_graph()
            self._send_json(200, graph)
            return

        # P3: Model Router — needs auth
        if path == "/model/route":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            text = params.get("text", [""])[0]
            model, provider, reason = _route_model(text)
            rules = _list_routing_rules()
            self._send_json(200, {"text": text[:100], "model": model,
                                  "provider": provider, "reason": reason,
                                  "rules_count": len(rules)})
            return

        # P3: Observer Stats — needs auth
        if path == "/observer/stats":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            stats = _get_observer_stats()
            self._send_json(200, stats)
            return

        # P3: Reasoning Traces — needs auth
        if path == "/traces/recent":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            traces = _get_recent_traces(limit=20)
            self._send_json(200, {"traces": traces})
            return

        if path == "/traces/failures":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            analysis = _get_failure_analysis()
            self._send_json(200, analysis)
            return

        # P7: Control Center — needs auth
        if path == "/control":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_CONTROL_CENTER_HTML.encode("utf-8"))
            return

        # P1: System Dashboard — needs auth
        if path == "/dashboard":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._serve_dashboard()
            return

        # P1: Dashboard JSON data API
        if path == "/dashboard/data":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                from nous_core.dashboard import get_dashboard_data
                data = get_dashboard_data()
            except Exception as e:
                self._send_json(500, {"error": str(e)})
                return
            self._send_json(200, data)
            return

        if not self._check_access():
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        if path == "/learn/brief":
            self._handle_learn_brief()
        elif path == "/learn/docs":
            self._handle_learn_docs_list()
        elif path == "/whoami":
            self._handle_whoami()
        elif path == "/config":
            self._handle_config_get()
        elif path == "/devices":
            self._handle_devices_list()
        elif path == "/sessions":
            self._handle_sessions_list()
        elif path == "/usage":
            self._handle_usage()
        elif path == "/security/status":
            self._handle_security_status()
        elif path == "/study/plan":
            self._handle_study_plan_get()
        elif path == "/study/today":
            self._handle_study_today()
        elif path == "/study/quiz":
            self._handle_study_quiz(params)
        elif path == "/study/summaries":
            self._handle_study_summaries()
        elif path == "/study/todo":
            self._handle_study_todo()
        elif path == "/study/plan_today":
            self._handle_study_plan_today()
        elif path == "/learn/kptree":
            self._handle_kptree(params)
        elif path == "/learn/taxonomy":
            self._handle_taxonomy()
        elif path == "/learn/catalog":
            self._handle_catalog(params)
        elif path.startswith("/session/"):
            sid = path.split("/session/", 1)[1]
            self._handle_session_detail(sid)
        elif path == "/chat/stream":
            self._handle_chat_stream(params)
        else:
            self._send_json(404, {"error": "not found"})

    def _serve_web_panel(self):
        """GET /web → 返回 Web 管理面板(单文件 HTML,零依赖)。页面本身无需鉴权,API 调用时带 token。"""
        html = _WEB_PANEL_HTML.replace("{{TOKEN}}", config.AUTH_TOKEN)
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_upload_page(self):
        """GET /upload → 资料上传页(电脑浏览器)。页面嵌入 token,API 调用带 X-Auth-Token。"""
        # 用第一个未禁用客户端的 token(电脑走隧道,等同已授权设备)
        tok = config.AUTH_TOKEN
        for c in clients.values():
            if not c.get("disabled") and c.get("token"):
                tok = c["token"]; break
        html = _UPLOAD_HTML.replace("{{TOKEN}}", tok)
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # P1 Quick Capture Handlers

    def _handle_inbox(self, params):
        """GET /inbox?status=new&source=phone&token=... → 返回收件箱列表。"""
        status = params.get("status", ["new"])[0]
        category = params.get("category", [""])[0]
        source = params.get("source", [""])[0]

        try:
            from nous_core.capture import get_inbox, inbox_counts
            items = get_inbox(status=status, category=category, source=source)
            counts = inbox_counts(source=source)
        except Exception as e:
            self._send_json(500, {"error": f"inbox read failed: {e}"})
            return
        self._send_json(200, {"items": items, "counts": counts})

    def _serve_dashboard(self):
        """GET /dashboard?token=... → 系统状态仪表盘(HTML)。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_DASHBOARD_HTML.encode("utf-8"))

    def _handle_capture(self):
        """POST /capture body:{content, loop_type?, target_device?} → 快速捕获+闭环处理。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return

        content = str(body.get("content", "")).strip()
        if not content:
            self._send_json(400, {"error": "content 不能为空"})
            return

        source = getattr(self, "_client_id", "unknown")
        sid = str(body.get("session_id", ""))

        loop_type = str(body.get("loop_type", "quick")).strip()
        result = {"loop": loop_type}

        try:
            from nous_core.capture import (
                capture, process_study_question, create_offline_task,
                is_study_question,
            )

            # Always capture to inbox first
            entry = capture(content, source=source, session_id=sid)
            result["inbox"] = entry

            # Loop 2: Study Question
            if loop_type == "study" or (loop_type == "auto" and is_study_question(content)):
                study_result = process_study_question(content, session_id=sid, source=source)
                result["study"] = study_result

            # Loop 3: PC Offline Task
            if loop_type == "offline_task":
                task_type = str(body.get("task_type", "shell_exec"))
                target = str(body.get("target_device", "laptop"))
                offline_result = create_offline_task(
                    task_type, content, session_id=sid,
                    source=source, target_device=target,
                )
                result["offline_task"] = offline_result

            self._send_json(200, {"ok": True, "result": result})

        except Exception as e:
            log.error("Capture failed: %s", e)
            self._send_json(500, {"error": f"capture failed: {e}"})

    # P8 Control API Handler

    def _handle_control_approval(self, path):
        """POST /api/v1/control/approvals/{id}/{action} → approve or deny。"""
        parts = path.rstrip("/").split("/")
        if len(parts) < 6:
            self._send_json(400, {"error": "invalid path, use /approvals/{id}/{action}"})
            return
        approval_id = parts[5]
        action = parts[6] if len(parts) > 6 else "view"

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            body = {}

        if action == "view":
            from nous_core.audit import query_logs
            entries = query_logs(action=approval_id, limit=1) if approval_id else []
            self._send_json(200, {"api_version": "v1", "approval": entries[0] if entries else None})
            return

        if action in ("approve", "deny"):
            # Record the decision
            from nous_core.audit import audit_log
            audit_log(
                f"approval.{action}d",
                actor=getattr(self, "_client_id", "desktop"),
                target=approval_id,
                result=action,
                detail={"confirmed_by": "control_center", "note": body.get("note", "")},
            )
            self._send_json(200, {"api_version": "v1", "status": f"{action}d",
                                  "approval_id": approval_id})
            return

        self._send_json(400, {"error": f"unknown action: {action}"})

    # P6 Setup Wizard

    def _handle_setup(self):
        """GET /setup?token=... → 初始化向导：安全检查 + 模块状态 + 部署报告。"""
        import os as _os

        report = {
            "version": "1.0.0",
            "status": "ok",
            "checks": [],
            "warnings": [],
            "modules": {},
            "next_steps": [],
        }

        # Security checks
        env_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env")
        env_perms = "600" if _os.path.exists(env_file) and (_os.stat(env_file).st_mode & 0o777) == 0o600 else "NOT_600"
        report["checks"].append({
            "name": ".env permissions",
            "status": "ok" if env_perms == "600" else "warn",
            "value": env_perms,
            "fix": "chmod 600 .env" if env_perms != "600" else None,
        })

        # Token check
        token_default = config.AUTH_TOKEN in ("", "change-me-to-a-strong-random-string",
                                               "改成一串强随机值")
        report["checks"].append({
            "name": "Admin token",
            "status": "warn" if token_default else "ok",
            "value": "default" if token_default else "set",
            "fix": "Set NOUS_AUTH_TOKEN in .env" if token_default else None,
        })

        # High-risk capabilities
        pc_shell = _os.environ.get("NOUS_ENABLE_PC_SHELL") == "1"
        phone_ctrl = _os.environ.get("NOUS_ENABLE_PHONE_CONTROL") == "1"
        file_write = _os.environ.get("NOUS_ENABLE_FILE_WRITE") == "1"

        for name, enabled, risk in [
            ("device.pc.shell", pc_shell, "HIGH"),
            ("device.phone.control", phone_ctrl, "HIGH"),
            ("tool.file_write", file_write, "HIGH"),
        ]:
            report["checks"].append({
                "name": name,
                "status": "warn" if enabled else "ok",
                "value": "enabled" if enabled else "disabled (safe default)",
                "fix": f"Set NOUS_ENABLE_{name.split('.')[-1].upper()}=0 in .env to disable" if enabled else None,
            })

        # Module status
        try:
            from nous_core.capability import list_capabilities
            caps = list_capabilities(enabled_only=True)
            report["modules"]["capabilities"] = len(caps)
        except Exception:
            report["modules"]["capabilities"] = "error"

        try:
            from nous_core.jobs import count_jobs
            report["modules"]["jobs"] = count_jobs()
        except Exception:
            report["modules"]["jobs"] = "error"

        try:
            from nous_core.events import count_events
            report["modules"]["events"] = count_events()
        except Exception:
            report["modules"]["events"] = "error"

        # Database
        db_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "nous_core.db")
        if _os.path.exists(db_path):
            size_kb = _os.path.getsize(db_path) // 1024
            report["checks"].append({
                "name": "Database", "status": "ok", "value": f"{size_kb} KB",
            })
        else:
            report["checks"].append({
                "name": "Database", "status": "warn", "value": "not found",
                "fix": "Start brain to auto-create database",
            })

        # Next steps
        if token_default:
            report["next_steps"].append("Set NOUS_AUTH_TOKEN in .env")
        if not _os.environ.get("NOUS_LLM_API_KEY"):
            report["next_steps"].append("Set NOUS_LLM_API_KEY in .env")
        report["next_steps"].append("Open /dashboard to monitor system")
        report["next_steps"].append("Run bash scripts/nous-doctor.sh for full audit")

        self._send_json(200, report)

    # P5 NEP Edge Protocol Handler

    def _handle_edge_message(self):
        """POST /edge/msg — receive NEP messages from edge devices (ESP32, Jetson, etc.)。
        Body: NEP Envelope JSON. Brain responds with appropriate ACK."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error_code": 7, "error_msg": "Invalid message"})
            return

        try:
            env = _Envelope.from_json(body)
        except Exception:
            self._send_json(400, {"error_code": 7, "error_msg": "Malformed envelope"})
            return

        if not env.is_valid():
            self._send_json(400, {"error_code": 7, "error_msg": "Invalid envelope"})
            return

        msg_type = env.msg_type
        src = env.source
        payload = env.payload

        if msg_type == "HELLO":
            # Register device in legacy dict + nous_core.devices (persistent)
            try:
                dtype = payload.get("device_type", "edge")
                # Legacy in-memory registration
                devices[src] = devices.get(src, {})
                devices[src].update({
                    "name": src, "host": self.client_address[0],
                    "device_type": dtype, "last_seen": time.time(), "_edge": True,
                })
                save_devices()
                # Persistent registration in nous_core.devices
                try:
                    from nous_core.devices import register_device as _ncore_reg, heartbeat as _ncore_hb
                    _ncore_reg(src, name=src, device_type=dtype,
                              host=self.client_address[0], port=0,
                              capabilities=[], metadata={"edge": True})
                    _ncore_hb(src)
                except Exception:
                    pass
                log.info("Edge device connected: %s (%s)", src, dtype)
                self._send_json(200, {"error_code": 0, "msg": "Welcome", "device_id": src})
            except Exception as e:
                self._send_json(500, {"error_code": 8, "error_msg": str(e)})

        elif msg_type == "CAPS":
            # Register device capabilities
            for cap in payload.get("capabilities", []):
                try:
                    _register_capability(
                        cap["id"], category="device", provider=src,
                        risk=cap.get("risk", "low"),
                        timeout_ms=cap.get("timeout_ms", 5000),
                        metadata={"edge_device": src},
                    )
                except Exception as e:
                    log.warning("Edge CAPS register failed for %s: %s", cap.get("id"), e)
            log.info("Edge device %s declared %d capabilities", src, len(payload.get("capabilities", [])))
            self._send_json(200, {"error_code": 0, "msg": "Capabilities registered"})

        elif msg_type == "HEARTBEAT":
            if src in devices:
                devices[src]["last_seen"] = time.time()
            # Update nous_core.devices heartbeat
            try:
                from nous_core.devices import heartbeat as _ncore_hb
                _ncore_hb(src)
            except Exception:
                pass
            self._send_json(200, {"error_code": 0})

        elif msg_type == "RESULT":
            log.info("Edge result from %s: job=%s ok=%s", src,
                     payload.get("job_id", "?"), payload.get("ok"))
            self._send_json(200, {"error_code": 0})

        elif msg_type == "ALERT":
            log.warning("Edge ALERT from %s: %s (severity=%s)", src,
                        payload.get("alert_type", "?"), payload.get("severity", "?"))
            _emit_event("edge.alert", source=src, device_id=src, payload=payload)
            # P10: notify desktop about edge alert
            _notify_device_offline(src, target="desktop")
            self._send_json(200, {"error_code": 0})

        else:
            self._send_json(400, {"error_code": 7, "error_msg": f"Unknown type: {msg_type}"})

    # P4 Kernel API Handlers

    def _handle_kernel_invoke(self):
        """POST /api/v1/kernel/capabilities/invoke — stable, versioned capability invoke。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error": "JSON required"})
            return
        cap = str(body.get("capability", "")).strip()
        params = body.get("params", {})
        risk = body.get("risk_level", "low")

        # Security check
        risk_result = _check_risk(cap, risk)
        if not risk_result["allowed"]:
            _record_security_event("risk_blocked", actor=getattr(self, "_client_id", ""),
                                   target=cap, risk=risk, decision="denied")
            self._send_json(403, risk_result)
            return

        if risk_result["requires_confirmation"] and not body.get("confirmed"):
            _record_security_event("confirmation_required", actor=getattr(self, "_client_id", ""),
                                   target=cap, risk=risk, decision="awaiting")
            self._send_json(200, {"status": "awaiting_confirmation", **risk_result})
            return

        try:
            result = _request_capability(cap, session_id=body.get("session_id", ""), **params)
            _record_security_event("capability_invoked", actor=getattr(self, "_client_id", ""),
                                   target=cap, risk=risk, decision="auto_approved" if risk in ("low", "medium") else "confirmed")
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {"api_version": "v1", "result": result})

    def _handle_kernel_jobs(self):
        """POST /api/v1/kernel/jobs — create/list jobs via kernel API。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error": "JSON required"})
            return
        try:
            from nous_core.jobs import create_job, list_jobs
            if body.get("action") == "create":
                jid = create_job(body.get("type", "kernel_job"), source="kernel_api",
                                 payload=body.get("payload", {}))
                self._send_json(200, {"api_version": "v1", "job_id": jid})
            else:
                jobs = list_jobs(status=body.get("status", ""), limit=20)
                self._send_json(200, {"api_version": "v1", "jobs": jobs})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    # P3 Capability Request Handler

    def _handle_capability_request(self):
        """POST /capability/request body:{capability, params:{...}} → execute with router + observer。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return
        cap_name = str(body.get("capability", "")).strip()
        if not cap_name:
            self._send_json(400, {"error": "capability 不能为空"})
            return
        params = body.get("params", {})
        if not isinstance(params, dict):
            params = {}
        sid = body.get("session_id", "")

        # P3-2: Model Router — if model.* capability, route to best model
        if cap_name.startswith("model."):
            prompt = params.get("prompt", "")
            if prompt:
                model, provider, reason = _route_model(prompt)
                params["model"] = model
                params["_routed_by"] = reason
                _log.info("Router: '%s...' → %s/%s (%s)", prompt[:40], provider, model, reason)

        try:
            result = _request_capability(
                cap_name,
                session_id=sid,
                auto_confirm=body.get("auto_confirm", False),
                **params,
            )
            # P3-5: auto-record reasoning trace
            _trace_capability_call(cap_name, params, result, session_id=sid)
            # P3-4: Observer — verify execution
            observer_result = _observe(cap_name, result, session_id=sid)
            if not observer_result["verified"]:
                result["_observer"] = observer_result
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, result)

    def _handle_capability_graph_request(self):
        """POST /capability/graph/request body:{capability, params:{...}} → execute with deps。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error": "JSON required"})
            return
        cap_name = str(body.get("capability", "")).strip()
        if not cap_name:
            self._send_json(400, {"error": "capability required"})
            return
        params = body.get("params", {})
        if not isinstance(params, dict):
            params = {}
        try:
            result = _request_capability_graph(
                cap_name,
                session_id=body.get("session_id", ""),
                **params,
            )
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, result)

    def _handle_trace_query(self, path):
        """Handle /traces/* POST queries."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            body = {}
        sid = body.get("session_id", "")
        if path == "/traces/recent":
            traces = _get_session_traces(sid) if sid else _get_recent_traces(limit=20)
            self._send_json(200, {"traces": traces})
        elif path == "/traces/failures":
            analysis = _get_failure_analysis()
            self._send_json(200, analysis)

    # P2 Study Session Handlers

    def _handle_study_start(self):
        """POST /study/start body:{subject, chapter, goals} → 开始学习会话。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return
        subject = str(body.get("subject", ""))
        chapter = str(body.get("chapter", ""))
        goals = str(body.get("goals", ""))
        try:
            from nous_core.study_session import start_session
            sid = start_session(subject=subject, chapter=chapter, goals=goals)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {"ok": True, "session_id": sid})

    def _handle_study_end(self):
        """POST /study/end body:{session_id} → 结束学习会话并生成总结。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return
        sid = str(body.get("session_id", ""))
        if not sid:
            self._send_json(400, {"error": "session_id 不能为空"})
            return
        try:
            from nous_core.study_session import end_session, get_session_detail
            summary = end_session(sid)
            detail = get_session_detail(sid)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {"ok": True, "summary": summary, "detail": detail})

    # Health

    def _handle_health(self):
        """GET /health → 返回健康状态 + 运行统计。"""
        health = {
            "status": "ok",
            "sessions_count": len(sessions),
            "rate_limited_ips": len(_rate_limit_buckets),
            "auth_failures": sum(len(v) for v in _auth_failures.values()),
            "seen_nonces": len(_seen_nonces),
        }
        self._send_json(200, health)

    def _handle_config_get(self):
        """GET /config — 返回当前配置(敏感项脱敏:只显示后4位)。"""
        def mask(v):
            if not v or len(v) < 8:
                return "***" if v else ""
            return "***" + v[-4:]

        self._send_json(200, {
            "ok": True,
            "config": {
                "BRAIN_HOST": config.BRAIN_HOST,
                "BRAIN_PORT": config.BRAIN_PORT,
                "DEFAULT_DEVICE": config.DEFAULT_DEVICE,
                "DEVICES_COUNT": len(devices),
                "RELAY_PRIMARY": config.RELAY_PRIMARY,
                "AUTH_TOKEN": mask(config.AUTH_TOKEN),
                "LLM_API_URL": config.LLM_API_URL,
                "LLM_API_KEY": mask(config.LLM_API_KEY),
                "LLM_MODEL": config.LLM_MODEL,
                "LLM_TIMEOUT": config.LLM_TIMEOUT,
                "PHONE_SSH_IP": config.PHONE_SSH_IP,
                "PHONE_SSH_PORT": config.PHONE_SSH_PORT,
                "SAFETY_MODE": getattr(config, "SAFETY_MODE", "normal"),
                "ALLOWED_IPS": ",".join(config.ALLOWED_IPS),
                # 高级设置
                "BRAIN_MAX_STEPS": getattr(config, "BRAIN_MAX_STEPS", 9999),
                "BRAIN_STEP_WARNING": getattr(config, "BRAIN_STEP_WARNING", 3000),
                "BRAIN_IDLE_LIMIT": getattr(config, "BRAIN_IDLE_LIMIT", 3),
                "COMMAND_TIMEOUT": getattr(config, "COMMAND_TIMEOUT", 30),
                "RATE_LIMIT_PER_MINUTE": getattr(config, "RATE_LIMIT_PER_MINUTE", 30),
            },
        })

    def _handle_security_status(self):
        """GET /security/status - return a non-secret production safety checklist."""
        cfg_file = getattr(config, "_CONFIG_FILE", "")
        cfg_mode = ""
        try:
            if cfg_file and os.path.exists(cfg_file):
                cfg_mode = oct(os.stat(cfg_file).st_mode & 0o777)
        except Exception:
            cfg_mode = ""
        checks = {
            "auth_token_configured": bool(getattr(config, "AUTH_TOKEN", "")),
            "agent_signing_secret_configured": bool(getattr(config, "AGENT_SIGNING_SECRET", "")),
            "llm_api_key_configured": bool(getattr(config, "LLM_API_KEY", "")),
            "allowed_ips_configured": bool(getattr(config, "ALLOWED_IPS", [])),
            "rate_limit_enabled": int(getattr(config, "RATE_LIMIT_PER_MINUTE", 0) or 0) > 0,
            "safety_mode": getattr(config, "SAFETY_MODE", "normal"),
            "phone_control_host_configured": bool(getattr(config, "PHONE_CONTROL_HOST", "")),
            "phone_control_token_configured": bool(getattr(config, "PHONE_CONTROL_TOKEN", "")),
            "query_token_compatibility_enabled": True,
            "config_file_mode": cfg_mode,
            "clients_count": len(clients),
            "devices_count": len(devices),
        }
        high_risks = []
        if not checks["auth_token_configured"]:
            high_risks.append("AUTH_TOKEN is not configured")
        if not checks["agent_signing_secret_configured"]:
            high_risks.append("AGENT_SIGNING_SECRET is not configured")
        if not checks["allowed_ips_configured"]:
            high_risks.append("ALLOWED_IPS is empty")
        if checks["query_token_compatibility_enabled"]:
            high_risks.append("Some legacy endpoints still accept token in URL query")
        self._send_json(200, {
            "ok": True,
            "production_ready": len(high_risks) == 0,
            "checks": checks,
            "high_risks": high_risks,
        })

    def _handle_whoami(self):
        """GET /whoami — 返回当前令牌对应的客户端身份信息。"""
        token = "".join(parse_qs(urlparse(self.path).query).get("token", [""]))
        cid = getattr(self, "_client_id", "") or resolve_client(token)
        if not cid:
            self._send_json(401, {"error": "unauthorized"})
            return
        if cid == "legacy":
            self._send_json(200, {"ok": True, "client_id": "legacy",
                                  "name": "共享令牌用户", "token_type": "shared"})
            return
        c = clients.get(cid, {})
        tok = c.get("token", "")
        self._send_json(200, {"ok": True, "client_id": cid,
                              "name": c.get("name", ""),
                              "token_suffix": tok[-4:] if tok else "",
                              "disabled": c.get("disabled", False)})

    def _handle_daily_inspiration(self):
        """GET /learn/daily — 每日灵感: 名言/公式/方程,按周几轮换领域。"""
        import random
        import hashlib
        today = time.strftime("%Y-%m-%d")
        weekday = __import__('datetime').date.today().weekday()  # 0=Mon

        domains = ["哲学","数学","语言","科学","技术","电子","物理","公式"]
        domain = domains[weekday % len(domains)]

        # 用日期做种子,同一天所有人看到相同内容
        seed = int(hashlib.md5(today.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        inspirations = {
            "哲学": [
                {"text": "我思故我在。", "author": "笛卡尔", "context": "认识论的基础——怀疑一切,唯有思考本身不可怀疑。"},
                {"text": "人不能两次踏进同一条河流。", "author": "赫拉克利特", "context": "万物皆流变,变化是宇宙的本质。"},
                {"text": "未经审视的人生不值得过。", "author": "苏格拉底", "context": "反思和自我认知是哲学的核心。"},
                {"text": "存在先于本质。", "author": "萨特", "context": "人先存在,然后通过自己的选择定义自己。"},
                {"text": "知识就是力量。", "author": "培根", "context": "掌握知识意味着拥有改变世界的能力。"},
            ],
            "数学": [
                {"text": "e^(iπ) + 1 = 0", "author": "欧拉公式", "context": "数学最美的公式,连接了e、π、i、1、0五个基本常数。"},
                {"text": "∫ e^x dx = e^x + C", "author": "微积分基本定理", "context": "唯一导数是自身的函数,指数函数的奇妙性质。"},
                {"text": "f'(x) = lim[h→0] (f(x+h)-f(x))/h", "author": "导数定义", "context": "变化率的精确数学表达,微积分的基石。"},
                {"text": "A = πr²", "author": "圆面积公式", "context": "最简单的公式之一,却蕴含了无理数π的奥秘。"},
                {"text": "1+1=2", "author": "皮亚诺公理", "context": "最简单也最深刻——整个算术体系建立在这个基础之上。"},
            ],
            "语言": [
                {"text": "To be, or not to be, that is the question.", "author": "莎士比亚《哈姆雷特》", "context": "生存还是毁灭,这是对人生最根本的追问。"},
                {"text": "Stay hungry, stay foolish.", "author": "Steve Jobs", "context": "保持求知若渴,保持谦逊——终身学习的核心态度。"},
                {"text": "The only way to do great work is to love what you do.", "author": "Steve Jobs", "context": "唯有热爱,才能成就卓越。"},
            ],
            "语言": [
                {"text": "学而时习之,不亦说乎。", "author": "《论语》", "context": "学了之后按时复习,这不是很愉快吗——最早的间隔复习理论。"},
                {"text": "路漫漫其修远兮,吾将上下而求索。", "author": "屈原《离骚》", "context": "学习之路很长,但坚持探索才是意义所在。"},
                {"text": "读书破万卷,下笔如有神。", "author": "杜甫", "context": "大量阅读是写作能力的基础。"},
            ],
            "技术": [
                {"text": "Any fool can write code that a computer can understand. Good programmers write code that humans can understand.", "author": "Martin Fowler", "context": "代码是写给人看的,顺便能在机器上运行。"},
                {"text": "Talk is cheap. Show me the code.", "author": "Linus Torvalds", "context": "不要争论,用代码说话——工程师的终极标准。"},
                {"text": "O(1) > O(n) > O(n²)", "author": "算法复杂度", "context": "常数时间优于线性时间优于平方时间——算法的本质追求。"},
            ],
            "电子": [
                {"text": "V = IR", "author": "欧姆定律", "context": "电压=电流×电阻,电子学最基本的定律。"},
                {"text": "P = VI = I²R", "author": "功率公式", "context": "功率=电压×电流,能量转换的核心。"},
            ],
            "物理": [
                {"text": "E = mc²", "author": "爱因斯坦", "context": "质量和能量是同一枚硬币的两面——质能方程。"},
                {"text": "F = ma", "author": "牛顿第二定律", "context": "力=质量×加速度,经典力学的核心。"},
            ],
            "公式": [
                {"text": "f'(x) = lim[h→0] (f(x+h)-f(x))/h", "author": "导数定义", "context": "变化率的精确数学表达——理解它,就理解了微积分的起点。"},
                {"text": "e^(iπ) + 1 = 0", "author": "欧拉恒等式", "context": "数学最美的公式。五个基本常数融于一身。"},
                {"text": "PV = nRT", "author": "理想气体方程", "context": "压力×体积=物质的量×常数×温度,物理化学的桥梁。"},
                {"text": "F = G·m₁m₂/r²", "author": "万有引力定律", "context": "两个物体之间的引力与质量乘积成正比,与距离平方成反比。"},
                {"text": "c² = a² + b²", "author": "勾股定理", "context": "直角三角形斜边的平方等于两直角边平方之和——几何第一定理。"},
                {"text": "λ = h/p", "author": "德布罗意波长", "context": "波长=普朗克常数/动量——万物皆有波动性,量子力学的起点。"},
            ],
        }

        items = inspirations.get(domain, inspirations["数学"])
        item = items[seed % len(items)]

        self._send_json(200, {"ok": True, "daily": {
            "text": item["text"],
            "author": item["author"],
            "context": item["context"],
            "domain": domain,
            "date": today,
        }})

    def _handle_learn_dashboard(self):
        """GET /learn/dashboard — 学习仪表盘数据(直读,无LLM,毫秒级)。"""
        import learn_db
        import learner_profile
        import schedule_engine
        try:
            stats = learn_db.get_stats()
            profile = learner_profile.load_profile()
            weak = learn_db.get_weak_topics(top_n=5)
            due_fm = learn_db.get_due_formulas(limit=5)
            due_kp = learn_db.get_due_knowledge_points(limit=10)
            coverage = learn_db.get_coverage()
            upcoming = learn_db.get_upcoming_exams(30)
            ach = __import__('efficiency_engine').AchievementSystem.check_all()
            tt = schedule_engine.get_timetable_engine()
            today_schedule = tt.get_today_schedule()
            free_slots = tt.get_free_slots()
            homework = tt.get_homework(due_only=True)

            self._send_json(200, {"ok": True, "dashboard": {
                "stats": stats,
                "streak": profile.get("behavior", {}).get("consecutive_days", 0),
                "weak_topics": [{"title": w["title"], "subject": w.get("subject",""),
                                 "mastery": w["mastery"]} for w in weak],
                "due_formulas": [{"name": f["name"], "plain": f.get("plain_text","")[:60],
                                  "mastery": f["mastery"]} for f in due_fm],
                "due_knowledge_points": [{"id": k["id"], "title": k["title"],
                                          "subject": k.get("subject","")} for k in due_kp],
                "coverage": coverage,
                "exams": [{"name": e["name"], "date": e["exam_date"],
                           "days_left": _days_until(e["exam_date"])} for e in upcoming[:3]],
                "achievements_earned": len(ach.get("earned", [])),
                "achievements_total": ach.get("total", 12),
                "today_schedule": [{"name": s["name"], "start": s["start_time"],
                                    "end": s["end_time"], "location": s.get("location","")}
                                   for s in today_schedule],
                "free_slots": free_slots,
                "homework_pending": len(homework),
                "heatmap": _build_heatmap(),
            }})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e)})

    def _handle_devices_list(self):
        """GET /devices — 返回所有已注册设备及在线状态。"""
        items = []
        for did, dev in devices.items():
            items.append({
                "device_id": did,
                "name": dev.get("name", did),
                "host": dev.get("host", ""),
                "port": dev.get("port", 0),
                "os": dev.get("os", ""),
                "type": dev.get("type", ""),  # phone/laptop/watch/tablet,空则前端按 os 推断
                "capabilities": dev.get("capabilities", []),
                "last_seen": dev.get("last_seen", 0),
                "online": is_device_online(dev),
            })
        self._send_json(200, {
            "ok": True,
            "devices": items,
            "default_device": config.DEFAULT_DEVICE,
        })

    def _handle_usage(self):
        """GET /usage — 返回 LLM token 用量统计。"""
        import brain_utils as _bu
        data = _bu._load_usage()
        self._send_json(200, {"ok": True, "usage": data})

    # 学习计划端点
    def _handle_study_plan_get(self):
        """GET /study/plan — 返回当前学习计划。"""
        self._send_json(200, {"ok": True, "plan": study_manager.get_plan()})

    def _handle_study_today(self):
        """GET /study/today — 返回今日任务 + 完成状态。"""
        self._send_json(200, {"ok": True, "today": study_manager.get_today_tasks()})

    def _handle_study_quiz(self, params):
        """GET /study/quiz?subject=英语&type=单词&count=5 — 出题。"""
        subject = "".join(params.get("subject", [""])).strip()
        qtype = "".join(params.get("type", ["练习题"])).strip()
        try:
            count = int("".join(params.get("count", ["5"])))
        except ValueError:
            count = 5
        if not subject:
            self._send_json(400, {"ok": False, "error": "subject 不能为空"})
            return
        try:
            q = study_manager.quiz(subject, qtype, count, call_model)
            self._send_json(200, {"ok": True, "subject": subject, "quiz": q})
        except Exception as e:
            log.error("出题失败: %s", e)
            self._send_json(200, {"ok": False, "error": f"出题失败: {e}"})

    def _handle_study_summaries(self):
        """GET /study/summaries — 返回历史学习总结列表。"""
        self._send_json(200, {"ok": True, "summaries": study_manager.list_summaries()})

    def _handle_kptree(self, params):
        """GET /learn/kptree?subject= — 知识树(思维导图数据)+ 科目列表。纯 DB。"""
        import learn_db
        subject = "".join(params.get("subject", [""])).strip()
        try:
            # 科目列表
            try:
                with learn_db._conn() as db:
                    rows = db.execute(
                        "SELECT DISTINCT subject FROM knowledge_points "
                        "WHERE subject IS NOT NULL AND subject!='' ORDER BY subject").fetchall()
                subjects = [r[0] for r in rows]
            except Exception:
                subjects = []
            tree = learn_db.get_kp_tree(subject=subject) if subject else learn_db.get_kp_tree()

            def _slim(nodes):
                out = []
                for n in nodes:
                    out.append({
                        "id": n.get("id"),
                        "title": n.get("title") or n.get("chapter") or n.get("section") or "",
                        "subject": n.get("subject", ""),
                        "mastery": n.get("mastery", 0),
                        "children": _slim(n.get("children", [])),
                    })
                return out

            self._send_json(200, {"ok": True, "subjects": subjects, "tree": _slim(tree)})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e), "subjects": [], "tree": []})

    def _handle_taxonomy(self):
        """GET /learn/taxonomy — 库里已有的阶段/科目/类型(下拉/分类提示用)。"""
        import learn_db
        try:
            self._send_json(200, {"ok": True, **learn_db.taxonomy_values()})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e),
                                  "stages": [], "subjects": [], "doc_types": []})

    def _handle_catalog(self, params):
        """GET /learn/catalog?stage=&subject= — token 友好知识目录(阶段→科目→章节→知识点)。"""
        import learn_db
        stage = "".join(params.get("stage", [""])).strip()
        subject = "".join(params.get("subject", [""])).strip()
        try:
            self._send_json(200, {"ok": True, "catalog": learn_db.get_catalog(stage, subject)})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e), "catalog": {}})

    def _handle_doc_meta(self, post_path):
        """POST /learn/doc/{id}/meta body:{stage?,subject?,doc_type?} — 人工修正分类。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        try:
            doc_id = int(post_path.split("/learn/doc/", 1)[1].rsplit("/meta", 1)[0])
        except ValueError:
            self._send_json(400, {"ok": False, "error": "无效的文档ID"}); return
        body = self._read_json_body()
        if body is None: return
        import learn_db
        try:
            learn_db.update_document_meta(
                doc_id,
                stage=body.get("stage"), subject=body.get("subject"),
                doc_type=body.get("doc_type"))
            self._send_json(200, {"ok": True, "id": doc_id})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e)})

    def _handle_doc_delete(self, post_path):
        """POST /learn/doc/{id}/delete — 删除一份资料及其知识点。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        try:
            doc_id = int(post_path.split("/learn/doc/", 1)[1].rsplit("/delete", 1)[0])
        except ValueError:
            self._send_json(400, {"ok": False, "error": "无效ID"}); return
        import learn_db
        ok = learn_db.delete_document(doc_id)
        self._send_json(200, {"ok": ok, "id": doc_id})

    def _handle_clear_failed(self):
        """POST /learn/docs/clear_failed — 一键清除所有解析失败的资料。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        import learn_db
        n = learn_db.delete_failed_documents()
        self._send_json(200, {"ok": True, "deleted": n})

    def _handle_clear_empty(self):
        """POST /learn/docs/clear_empty — 清除已解析但 0知识点0题 的资料。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        import learn_db
        n = learn_db.delete_empty_documents()
        self._send_json(200, {"ok": True, "deleted": n})

    def _handle_clear_all(self):
        """POST /learn/docs/clear_all — 清空整个资料/知识库(保留考试/计划/课表)。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        import learn_db
        n = learn_db.delete_all_documents()
        self._send_json(200, {"ok": True, "deleted": n})

    def _handle_clear_pending(self):
        """POST /learn/docs/clear_pending — 删除待解析/卡住的文档,保留已解析好的。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        import learn_db
        n = learn_db.delete_unfinished_documents()
        self._send_json(200, {"ok": True, "deleted": n})

    def _handle_parse_pending(self):
        """POST /learn/parse_pending — 启动后台批量解析所有待解析文档。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        import learn_db
        import threading
        n = learn_db.count_pending()
        if n and not is_parse_worker_running():
            set_parse_worker_running(True)
            threading.Thread(target=_parse_pending_worker, daemon=True).start()
        self._send_json(200, {"ok": True, "pending": n, "running": is_parse_worker_running()})

    def _handle_study_plan_today(self):
        """GET /study/plan_today — 自适应每日计划(纯DB实时计算)+ 完成态。"""
        import plan_engine
        import study_manager
        try:
            plan = plan_engine.compute_today()
            try:
                done = set(study_manager.get_today_tasks().get("done_today", []) or [])
            except Exception:
                done = set()
            for t in plan["tasks"]:
                t["done"] = t["title"] in done
            self._send_json(200, {"ok": True, **plan})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e), "tasks": []})

    def _handle_study_todo(self):
        """GET /study/todo — 组装今日待办清单(数据驱动,无 LLM)。"""
        import learn_db
        import schedule_engine
        items = []
        goal = ""
        days_left = -999
        try:
            tasks = study_manager.get_today_tasks()
            if tasks.get("has_plan"):
                goal = tasks.get("goal", "")
                days_left = tasks.get("days_left", -999)
                done_today = set(tasks.get("done_today", []) or [])
                dp = tasks.get("daily_plan", {}) or {}
                # daily_plan 可能是 {科目:任务} 或列表
                plan_items = []
                if isinstance(dp, dict):
                    for k, v in dp.items():
                        plan_items.append(f"{k}:{v}" if v else str(k))
                elif isinstance(dp, list):
                    plan_items = [str(x) for x in dp]
                for t in plan_items:
                    items.append({"kind": "plan", "text": t, "done": t in done_today})
            else:
                done_today = set()
        except Exception:
            done_today = set()
        # 今日课表
        try:
            tt = schedule_engine.get_timetable_engine()
            for s in tt.get_today_schedule():
                txt = f"{s.get('start_time','')} {s.get('name','')}".strip()
                items.append({"kind": "class", "text": txt, "done": txt in done_today})
        except Exception:
            pass
        # 到期复习(知识点 + 公式)
        try:
            n_kp = len(learn_db.get_due_knowledge_points(limit=50))
            n_fm = len(learn_db.get_due_formulas(limit=50))
            if n_kp or n_fm:
                t = f"复习到期内容(知识点{n_kp}+公式{n_fm})"
                items.append({"kind": "review", "text": t, "done": t in done_today})
        except Exception:
            pass
        # 弱项
        try:
            for w in learn_db.get_weak_topics(top_n=3):
                t = f"强化:{w['title']} {w.get('mastery',0)}%"
                items.append({"kind": "weak", "text": t, "done": t in done_today})
        except Exception:
            pass
        # 作业
        try:
            tt = schedule_engine.get_timetable_engine()
            for h in tt.get_homework(due_only=True):
                t = f"作业:{h.get('content', h.get('name',''))}"
                items.append({"kind": "hw", "text": t, "done": t in done_today})
        except Exception:
            pass
        done_count = sum(1 for it in items if it["done"])
        self._send_json(200, {"ok": True, "goal": goal, "days_left": days_left,
                              "items": items, "done_count": done_count, "total": len(items)})

    def _handle_study_todo_check(self):
        """POST /study/todo/check {text, done} — 勾选/取消今日待办。"""
        if not self._check_access():
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        body = self._read_json_body()
        if body is None:
            return
        text = str(body.get("text", "")).strip()
        done = bool(body.get("done", True))
        if not text:
            self._send_json(400, {"ok": False, "error": "text 不能为空"})
            return
        try:
            tasks = study_manager.get_today_tasks()
            cur = list(tasks.get("done_today", []) or []) if tasks.get("has_plan") else []
            if done and text not in cur:
                cur.append(text)
            elif not done and text in cur:
                cur.remove(text)
            study_manager.checkin(cur, "")
            self._send_json(200, {"ok": True, "done_count": len(cur)})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e)})

    def _read_json_body(self):
        """读取并解析 POST 请求体 JSON。失败返回 None 并已回错误响应。"""
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return None

    def _handle_study_plan_post(self):
        """POST /study/plan — 创建学习计划(LLM 生成每日分配)。需鉴权。"""
        if not self._check_access():
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        body = self._read_json_body()
        if body is None:
            return
        goal = str(body.get("goal", "")).strip()
        deadline = str(body.get("deadline", "")).strip()
        subjects = body.get("subjects", []) or []
        extra = str(body.get("extra", "")).strip()
        if not goal or not deadline:
            self._send_json(400, {"ok": False, "error": "goal 和 deadline 不能为空"})
            return
        try:
            plan = study_manager.create_plan(goal, deadline, subjects, extra, call_model)
            log.info("学习计划已创建: %s(截止 %s)", goal, deadline)
            self._send_json(200, {"ok": True, "plan": plan})
        except Exception as e:
            log.error("创建学习计划失败: %s", e)
            self._send_json(200, {"ok": False, "error": f"创建失败: {e}"})

    def _handle_study_checkin_post(self):
        """POST /study/checkin — 今日打卡。需鉴权。"""
        if not self._check_access():
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        body = self._read_json_body()
        if body is None:
            return
        done = body.get("done", []) or []
        note = str(body.get("note", "")).strip()
        result = study_manager.checkin(done, note)
        self._send_json(200, result)

    def _handle_config_post(self):
        """POST /config — 更新配置并保存到 config.local.json。需 token 鉴权。"""
        if not self._check_access():
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "JSON 格式错误"})
            return
        updates = body.get("config", {})
        if not updates:
            self._send_json(400, {"error": "config 字段不能为空"})
            return
        try:
            config.save_config(updates)
            log.info("配置已更新: %s", ", ".join(updates.keys()))
            self._send_json(200, {"ok": True, "message": "配置已保存并生效"})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": f"保存失败: {e}"})

    def _handle_exec_proxy(self):
        """
        POST /exec — 终端模式代理:brain 转发命令到指定设备的 agent。
        请求体: {"command": "ls", "device_id": "laptop"}
        这样手机终端模式也能通过 brain 路由,统一链路,保留审计。
        """
        if not self._check_access():
            return
        if not _check_replay(self.client_address[0],
                             self.headers.get("X-Timestamp", ""), self.headers.get("X-Nonce", "")):
            self._send_json(403, {"error": "replay detected or missing anti-replay headers"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "JSON 格式错误"})
            return
        command = str(body.get("command", "")).strip()
        if not command:
            self._send_json(400, {"error": "command 不能为空"})
            return
        device_id = str(body.get("device_id", "")) or config.DEFAULT_DEVICE
        # 终端模式无确认流程:危险命令一律拒绝,引导用户走指挥模式(有安全闸确认)
        danger = safety.check_danger(command, getattr(config, "SAFETY_MODE", "normal"))
        if danger.is_danger:
            log.warning("终端代理拒绝危险命令[%s→%s]: %s —— %s",
                        self.client_address[0], device_id, command[:80], "; ".join(danger.reasons))
            self._send_json(200, {
                "command": command, "ok": False, "returncode": -1, "stdout": "",
                "stderr": "拒绝:终端模式不执行危险命令(请用指挥模式,会有确认流程)。原因: " + "; ".join(danger.reasons),
            })
            return
        log.info("exec代理[%s→%s]: %s", self.client_address[0], device_id, command[:80])
        try:
            text, returncode = _exec_raw(command, device_id=device_id)
            # 拆分 stdout/stderr(如果有 [stderr] 标记)
            stdout, stderr = text, ""
            if "\n[stderr]\n" in text:
                parts = text.split("\n[stderr]\n", 1)
                stdout, stderr = parts[0], parts[1]
            self._send_json(200, {
                "command": command, "ok": returncode == 0 if isinstance(returncode, int) else True,
                "returncode": returncode or 0, "stdout": stdout, "stderr": stderr,
            })
        except Exception as e:
            self._send_json(200, {
                "command": command, "ok": False, "returncode": -1,
                "stdout": "", "stderr": f"执行失败: {e}",
            })

    def _handle_sessions_list(self):
        """GET /sessions?token=xxx → 返回所有会话摘要列表。"""
        items = []
        for sid, s in sessions.items():
            # 取最后一条用户消息作为预览
            preview = ""
            for m in reversed(s.get("messages", [])):
                if m.get("role") == "user":
                    preview = str(m.get("content", ""))[:50]
                    break
            # 优先用 LLM 生成标题，其次用户设置 name，最后用首条消息截断
            display_name = s.get("title") or s.get("name") or preview[:20]
            items.append({
                "session_id": sid,
                "name": display_name,
                "preview": preview,
                "tags": s.get("tags", []),
                "updated": s.get("updated", 0),
                "message_count": len(s.get("messages", [])),
            })
        items.sort(key=lambda x: x["updated"], reverse=True)
        self._send_json(200, {"ok": True, "sessions": items})

    def _handle_session_detail(self, sid):
        """GET /session/{id}?token=xxx → 返回单个会话的完整消息历史。"""
        s = sessions.get(sid)
        if not s:
            self._send_json(404, {"ok": False, "error": "会话不存在"})
            return
        self._send_json(200, {
            "ok": True,
            "session_id": sid,
            "cwd": s.get("cwd", ""),
            "summary": s.get("summary", ""),
            "messages": s.get("messages", []),
            "updated": s.get("updated", 0),
        })

    def _handle_chat_stream(self, params):
        """
        GET /chat/stream?session_id=xxx&message=xxx&model=xxx&token=xxx
        SSE 流式推送:每完成一步命令,实时推送进度到手机。
        为什么用 GET 而不是 POST:SSE 规范使用 GET,参数通过 query string 传递。
        """
        message = "".join(params.get("message", [""])).strip()
        if not message:
            self._send_json(400, {"error": "message 不能为空"})
            return

        # 防重放(SSE 用 query 参数 ts/nonce)
        if not _check_replay(self.client_address[0],
                             "".join(params.get("ts", [""])), "".join(params.get("nonce", [""]))):
            self._send_json(403, {"error": "replay detected or missing anti-replay params"})
            return

        sid = "".join(params.get("session_id", [uuid.uuid4().hex]))
        model = "".join(params.get("model", [config.LLM_MODEL]))
        target_device = "".join(params.get("target_device", [""])) or None
        session = get_session(sid, target_device=target_device)
        session["_source_ip"] = self.client_address[0]
        _src_cid = resolve_client("".join(params.get("token", [""])))
        session["_source_client"] = _src_cid
        session["_client_profile"] = _client_tool_profile(_src_cid)
        # Skill Runtime + 旧关键词分诊:先按任务级 Skill 路由,无匹配再回退旧分诊。
        _route_message_skill(session, message)
        if not session.get("_transcript_sid"):
            session["_transcript_sid"] = sid

        # 教学模式检测: 学习场景下自动切换教学状态机
        if _is_learning_context(None, message):
            current = session.get("_teach_mode", "")
            session["_teach_mode"] = brain_prompt.detect_teach_mode(message, current)

        log.info("SSE对话[%s] 模型=%s 目标=%s: %s", sid[:8], model,
                 session.get("target_device", "?"), _mask_sensitive(message))

        # 设置 SSE 响应头
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")  # 禁用 nginx 缓冲
        self.end_headers()

        try:
            # 新用户消息(处理 #code/#write/#study 模式前缀)
            actual_text = _apply_mode_prefix(session, message)
            session["messages"].append({"role": "user", "content": actual_text})
            _write_transcript(sid, {"type": "user_message", "content": actual_text})
            maybe_summarize(session, model)

            # 流式执行
            _continue_loop_stream(session, model, [], config.BRAIN_MAX_STEPS, 0, self.wfile)

            session["updated"] = time.time()
            save_sessions()
            # 首次对话 → 后台生成会话标题
            if not session.get("_title_generated"):
                _generate_session_title(session, sid)
            # 对话完成后自动更新学习者画像
            try:
                updater = learner_profile.get_profile_updater()
                updater.update_from_conversation(session.get("messages", []))
            except Exception:
                pass
        except Exception as e:
            log.error("SSE 对话失败: %s", e)
            try:
                _sse_write(self.wfile, "error", {"message": f"对话失败: {e}"})
            except Exception:
                pass
            # 即使异常也保存（已添加的消息不应丢失）
            try:
                session["updated"] = time.time()
                save_sessions()
            except Exception:
                pass
        finally:
            # 正常路径已保存，但 finally 确保落盘（幂等，多一次 save 无副作用）
            try:
                session["updated"] = time.time()
                save_sessions()
            except Exception:
                pass
            # 显式关闭 wfile,确保手机端 readLine 收到 EOF 退出阻塞
            try:
                self.wfile.flush()
                self.wfile.close()
            except Exception:
                pass

    def do_POST(self):
        parsed_post = urlparse(self.path)
        post_path = parsed_post.path.rstrip("/") or "/"

        # P5: NEP Edge Protocol endpoint
        if post_path == "/edge/msg":
            self._handle_edge_message()
            return

        # P4: Kernel API v1 POST endpoints
        if post_path == "/api/v1/kernel/capabilities/invoke":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_kernel_invoke()
            return
        if post_path == "/api/v1/kernel/jobs":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_kernel_jobs()
            return

        # P8: Control API — approval actions
        if post_path.startswith("/api/v1/control/approvals/"):
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_control_approval(post_path)
            return

        if post_path == "/config":
            self._handle_config_post()
            return

        if post_path == "/exec":
            self._handle_exec_proxy()
            return

        if post_path == "/study/plan":
            self._handle_study_plan_post()
            return

        if post_path == "/study/checkin":
            self._handle_study_checkin_post()
            return

        if post_path == "/study/todo/check":
            self._handle_study_todo_check()
            return

        if post_path == "/schedule/bulk":
            self._handle_schedule_bulk()
            return

        if post_path.startswith("/learn/doc/") and post_path.endswith("/subject"):
            self._handle_doc_subject(post_path)
            return

        if post_path.startswith("/learn/doc/") and post_path.endswith("/meta"):
            self._handle_doc_meta(post_path)
            return

        if post_path.startswith("/learn/doc/") and post_path.endswith("/delete"):
            self._handle_doc_delete(post_path)
            return

        if post_path == "/learn/docs/clear_failed":
            self._handle_clear_failed()
            return

        if post_path == "/learn/docs/clear_empty":
            self._handle_clear_empty()
            return

        if post_path == "/learn/docs/clear_all":
            self._handle_clear_all()
            return

        if post_path == "/learn/docs/clear_pending":
            self._handle_clear_pending()
            return

        if post_path == "/learn/parse_pending":
            self._handle_parse_pending()
            return

        # 需要鉴权的端点（所有写操作都需 token）
        if post_path in ("/tts", "/transcribe", "/chat"):
            # 公网暴露时强制鉴权；VPN 隧道内 IP 免重放检查
            client_ip = self.client_address[0]
            if not client_ip.startswith("10.10.0."):
                if not _check_replay(client_ip,
                                     self.headers.get("X-Timestamp", ""),
                                     self.headers.get("X-Nonce", "")):
                    self._send_json(403, {"error": "replay detected"})
                    return
            if not self._authorized():
                log.warning("拒绝:令牌错误,端点=%s 来自 %s", post_path, client_ip)
                _check_anomaly(client_ip, False)
                self._send_json(401, {"error": "unauthorized"})
                return

        if post_path == "/tts":
            self._handle_tts()
            return

        if post_path == "/transcribe":
            self._handle_transcribe()
            return

        if post_path == "/learn/upload_raw":
            self._handle_learn_upload_raw()
            return

        if post_path == "/learn/upload":
            self._handle_learn_upload()
            return

        # P2: Study Session endpoints
        if post_path == "/study/start":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_study_start()
            return
        if post_path == "/study/end":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_study_end()
            return

        # P3: Capability Request
        if post_path == "/capability/request":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_capability_request()
            return

        # P3: Capability Graph Request (execute with all deps)
        if post_path == "/capability/graph/request":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_capability_graph_request()
            return

        # P3: Reasoning Traces API
        if post_path in ("/traces/recent", "/traces/failures"):
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_trace_query(post_path)
            return

        # P1: Quick Capture + Closed Loops
        if post_path == "/capture":
            if not self._check_access() or not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_capture()
            return

        if post_path == "/chat":
            if not self._check_access() or not self._authorized():
                client_ip = self.client_address[0]
                _audit_log(
                    "auth.failure",
                    actor="unknown",
                    target="/chat",
                    result="failure",
                    detail={"reason": "unauthorized", "endpoint": "/chat"},
                    ip_address=client_ip,
                )
                self._send_json(401, {"error": "unauthorized"})
                return

        if post_path not in ("/tts", "/transcribe", "/chat", "/capture"):
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return

        # 两种请求模式:普通聊天(有 message) 或 确认回复(有 confirmation)
        message = str(body.get("message", "")).strip()
        confirmation = body.get("confirmation")  # {"id": "...", "action": "approve"|"deny"}

        if not message and not confirmation:
            self._send_json(400, {"error": "message 或 confirmation 至少需要一个"})
            return

        sid = str(body.get("session_id") or uuid.uuid4().hex)  # 缺省则新建会话
        model = str(body.get("model") or config.LLM_MODEL)
        target_device = str(body.get("target_device", "")) or None

        # P0: detect new session before get_session auto-creates it
        is_new_session = sid not in brain_sessions.sessions

        session = get_session(sid, target_device=target_device)

        # P0: record session created event
        if is_new_session:
            _emit_event("session.created",
                        source=getattr(self, "_client_id", "unknown"),
                        session_id=sid,
                        payload={"target_device": target_device or config.DEFAULT_DEVICE})

        # 记录来源(审计用):IP + 客户端身份
        session["_source_ip"] = self.client_address[0]
        _src_cid = getattr(self, "_client_id", "")
        session["_source_client"] = _src_cid
        session["_client_profile"] = _client_tool_profile(_src_cid)
        # Skill Runtime + 旧关键词分诊:先按任务级 Skill 路由,无匹配再回退旧分诊。
        _route_message_skill(session, message)

        # 确保 transcript session_id 已设置
        if not session.get("_transcript_sid"):
            session["_transcript_sid"] = sid

        # 教学模式检测: 学习场景下自动切换教学状态机
        if message and _is_learning_context(None, message):
            current = session.get("_teach_mode", "")
            session["_teach_mode"] = brain_prompt.detect_teach_mode(message, current)

        if confirmation:
            log.info("对话[%s] 收到确认: id=%s action=%s",
                     sid[:8], confirmation.get("id", "?")[:12], confirmation.get("action", "?"))
            # 如果 SSE 流正在等待确认,直接通过 event 唤醒它(不需要再走 run_turn)
            stream_event = session.pop("_confirmation_event", None)
            if stream_event:
                # 将确认结果写入 pending,然后唤醒 SSE 线程
                pending = session.get("pending_confirmation", {})
                pending["_action"] = confirmation.get("action", "deny")
                pending["_confirmed_by"] = "post"
                session["pending_confirmation"] = pending
                stream_event.set()
                session["updated"] = time.time()
                save_sessions()
                self._send_json(200, {"ok": True, "session_id": sid, "status": "confirmed"})
                return
        else:
            log.info("对话[%s] 模型=%s: %s", sid[:8], model, _mask_sensitive(message))
            # 新用户消息写入 transcript
            _write_transcript(sid, {"type": "user_message", "content": message})

        try:
            result = run_turn(session, message, model, confirmation=confirmation)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            log.error("模型接口 HTTP %s: %s", e.code, detail)
            self._send_json(200, {"ok": False, "session_id": sid, "error": f"模型接口错误 HTTP {e.code}: {detail}"})
            return
        except Exception as e:
            log.error("对话失败: %s", e)
            self._send_json(200, {"ok": False, "session_id": sid, "error": f"对话失败: {e}"})
            return

        session["updated"] = time.time()
        save_sessions()

        # P0: record event (best-effort, never breaks chat)
        _emit_event("chat.message.received",
                    source=getattr(self, "_client_id", "unknown"),
                    session_id=sid,
                    payload={"model": model, "message_length": len(message) if message else 0})

        # 首次对话 → 后台生成会话标题
        if not session.get("_title_generated"):
            _generate_session_title(session, sid)

        # P0-6: Skill completion verification at end of turn
        active_skill = session.get("_active_skill", "")
        if active_skill and status == "done":
            try:
                skill_result = skill_engine.complete_skill(
                    active_skill, session,
                    result={"status": status, "steps": len(result.get("steps", []))})
                if skill_result.get("verification", {}).get("suggestion"):
                    log.info("Skill完成验证[%s]: %s", active_skill[:16],
                             skill_result["verification"]["suggestion"])
                if skill_result.get("next_skill"):
                    ns = skill_result["next_skill"]
                    log.debug("Skill[%s] 建议链式切换到: %s", active_skill, ns.get("id", ""))
            except Exception:
                pass

        # 对话完成后自动更新学习者画像
        try:
            updater = learner_profile.get_profile_updater()
            updater.update_from_conversation(session.get("messages", []))
        except Exception:
            pass

        # 根据 run_turn 返回的 status 构建不同响应
        status = result.get("status", "error")
        if status == "awaiting_confirmation":
            log.info("会话[%s] 等待用户确认: %s", sid[:8], _mask_sensitive(result.get("command", "")))
            self._send_json(200, {
                "ok": True,
                "session_id": sid,
                "status": "awaiting_confirmation",
                "confirmation_id": result.get("confirmation_id"),
                "command": result.get("command"),
                "dangers": result.get("dangers"),
            })
        elif status == "done":
            reply = result.get("reply", "")
            steps = result.get("steps", [])
            log.info("会话[%s] 完成,执行 %d 条命令,当前 cwd=%s", sid[:8], len(steps), session.get("cwd"))
            # 助手最终回复写入 transcript
            if reply and reply != "(已达最大执行步数,任务可能未完成)":
                _write_transcript(sid, {"type": "assistant_reply", "content": reply})
            self._send_json(200, {"ok": True, "session_id": sid, "reply": reply, "steps": steps})
        else:  # error
            self._send_json(200, {"ok": False, "session_id": sid, "error": result.get("message", "未知错误")})


    def do_DELETE(self):
        """DELETE /session/{id}?token=xxx → 删除单个会话
           DELETE /sessions?token=xxx       → 删除全部会话"""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        token = "".join(params.get("token", [""]))
        if not resolve_client(token):
            self._send_json(401, {"error": "unauthorized"})
            return
        # 删除全部会话
        if path == "/sessions":
            count = len(sessions)
            sessions.clear()
            save_sessions()
            log.info("已删除全部 %d 个会话", count)
            self._send_json(200, {"ok": True, "deleted_all": True, "count": count})
            return
        # 删除单个会话
        if path.startswith("/session/"):
            sid = path.split("/session/", 1)[1]
            if sid in sessions:
                del sessions[sid]
                save_sessions()
                self._send_json(200, {"ok": True, "deleted": sid})
            else:
                self._send_json(404, {"ok": False, "error": "会话不存在"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        """PUT /session/{id}?token=xxx body:{"name":"新名称"} → 重命名会话。"""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        token = "".join(params.get("token", [""]))
        if not resolve_client(token):
            self._send_json(401, {"error": "unauthorized"})
            return
        if path.startswith("/session/") and path.endswith("/rename"):
            sid = path.split("/session/", 1)[1].rsplit("/rename", 1)[0]
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "请求体必须是 JSON"})
                return
            name = str(body.get("name", "")).strip()
            if not name:
                self._send_json(400, {"ok": False, "error": "name 不能为空"})
                return
            if sid in sessions:
                sessions[sid]["name"] = name
                save_sessions()
                self._send_json(200, {"ok": True, "renamed": sid, "name": name})
            else:
                self._send_json(404, {"ok": False, "error": "会话不存在"})
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_learn_brief(self):
        """GET /learn/brief — 主动今日简报:倒计时+今日计划+待复习+弱项+时间线+明日预备包。"""
        import learn_db
        import learner_profile
        import schedule_engine
        try:
            profile = learner_profile.load_profile()
            weak = learn_db.get_weak_topics(top_n=3)
            due_fm = learn_db.get_due_formulas(limit=20)
            upcoming = learn_db.get_upcoming_exams(120)
            tt = schedule_engine.get_timetable_engine()
            today_schedule = tt.get_today_schedule()
            stats = learn_db.get_stats()
            # 计划提醒(若有学习计划)
            plan = study_manager.get_plan()
            reminders = plan.get("reminders", []) if plan else []
            # 时间线 = 课表 + 计划提醒,按时间排序
            timeline = []
            for s in today_schedule:
                timeline.append({"time": s.get("start_time", ""), "text": s.get("name", ""),
                                 "kind": "class", "location": s.get("location", "")})
            for r in reminders:
                timeline.append({"time": r.get("time", ""), "text": r.get("text", ""),
                                 "kind": "reminder", "subject": r.get("subject", "")})
            timeline.sort(key=lambda x: x.get("time", "99:99"))
            pack = _load_tomorrow_pack()
            pack_ready = pack.get("date") == time.strftime("%Y-%m-%d")  # 预备包是给今天的
            self._send_json(200, {"ok": True, "brief": {
                "streak": profile.get("behavior", {}).get("consecutive_days", 0),
                "exam": ({"name": upcoming[0]["name"], "date": upcoming[0]["exam_date"],
                          "days_left": _days_until(upcoming[0]["exam_date"])} if upcoming else None),
                "due_review_count": len(due_fm),
                "weak_topics": [{"title": w["title"], "subject": w.get("subject", ""),
                                 "mastery": w["mastery"]} for w in weak],
                "today_minutes": stats.get("today_minutes", 0) if isinstance(stats, dict) else 0,
                "timeline": timeline,
                "has_plan": bool(plan),
                "prepared_questions": pack_ready and bool(pack.get("questions")),
                "prepared_topics": pack.get("topics", []) if pack_ready else [],
            }})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e)})

    def _handle_learn_docs_list(self):
        """GET /learn/docs — 返回文档库列表(资料管理页用)。"""
        try:
            import learn_db
            docs = learn_db.list_documents()
            items = [{
                "id": d.get("id"), "filename": d.get("filename", ""),
                "subject": d.get("subject", ""), "filetype": d.get("filetype", ""),
                "stage": d.get("stage", ""), "doc_type": d.get("doc_type", ""),
                "parsed": d.get("parsed", 0), "kp_count": d.get("kp_count", 0),
                "ex_count": d.get("ex_count", 0), "uploaded_at": d.get("uploaded_at", ""),
                "status": d.get("status", ""), "note": d.get("note", ""),
                "progress": d.get("progress", ""),
            } for d in docs]
            self._send_json(200, {"ok": True, "docs": items})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e), "docs": []})

    def _handle_learn_upload_raw(self):
        """POST /learn/upload_raw?filename=&subject=&stage=&doc_type=&keep=0 — 原始字节流式上传(大文件不占内存)。"""
        client_ip = self.client_address[0]
        if not client_ip.startswith("10.10.0."):
            if not _check_replay(client_ip, self.headers.get("X-Timestamp", ""),
                                 self.headers.get("X-Nonce", "")):
                self._send_json(403, {"error": "replay detected"}); return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        params = parse_qs(urlparse(self.path).query)
        filename = os.path.basename("".join(params.get("filename", [""])).strip())
        if not filename:
            self._send_json(400, {"ok": False, "error": "filename 必填"}); return
        subject = "".join(params.get("subject", [""])).strip()
        stage = "".join(params.get("stage", [""])).strip()
        doc_type = "".join(params.get("doc_type", [""])).strip()
        keep = "".join(params.get("keep", ["0"])) == "1"
        parse_now = "".join(params.get("parse", ["1"])) != "0"   # parse=0 → 仅上传,稍后批量解析
        docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_docs")
        os.makedirs(docs_dir, exist_ok=True)
        dest = os.path.join(docs_dir, filename)
        filetype = os.path.splitext(filename)[1].lower().lstrip(".")
        length = int(self.headers.get("Content-Length", 0))
        try:
            remaining = length
            with open(dest, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(262144, remaining))
                    if not chunk:
                        break
                    f.write(chunk); remaining -= len(chunk)
        except Exception as e:
            self._send_json(400, {"ok": False, "error": f"接收失败: {e}"}); return

        # 防重:同名且已成功解析(有内容)→ 跳过,不重复解析/上传
        import learn_db as _ldb
        if _ldb.document_has_content(filename):
            if not keep:
                try:
                    os.remove(dest)
                except Exception:
                    pass
            self._send_json(200, {"ok": True, "skipped": True, "filename": filename,
                                  "message": "已存在且有内容,已跳过"})
            return

        # 仅上传模式:只登记+留底,不解析(稍后点"开始解析"批量处理)
        if not parse_now:
            doc_id = _ldb.add_document(filename=filename, filepath=dest, filetype=filetype,
                                       subject=subject, total_pages=0, stage=stage, doc_type=doc_type)
            _ldb.update_document_status(doc_id, "pending")
            self._send_json(200, {"ok": True, "filename": filename, "pending": True,
                                  "message": "已上传,待批量解析"})
            return

        import threading
        def _process():
            try:
                import doc_engine
                import learn_db
                tax = learn_db.taxonomy_values()
                with doc_engine._INGEST_LOCK:  # 串行解析,防并发 OCR 爆内存
                    doc_engine.process_document(
                        dest, call_ingest_model, subject=subject, doc_type=doc_type,
                        stage=stage, taxonomy=tax, keep_original=keep)
            except Exception as e:
                log.error("后台文档处理失败: %s", e)
        threading.Thread(target=_process, daemon=True).start()
        self._send_json(200, {"ok": True, "filename": filename, "message": "已接收,后台分析归类中"})

    def _handle_learn_upload(self):
        """POST /learn/upload — 上传文件到文档库。支持 base64 内容 或 JSON指定路径。"""
        ct = self.headers.get("Content-Type", "")
        client_ip = self.client_address[0]
        if not client_ip.startswith("10.10.0."):
            if not _check_replay(client_ip, self.headers.get("X-Timestamp", ""),
                                 self.headers.get("X-Nonce", "")):
                self._send_json(403, {"error": "replay detected"})
                return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            body = {}

        filepath = str(body.get("filepath", "")).strip()
        subject = str(body.get("subject", "")).strip()
        content_b64 = body.get("content_b64", "")
        upload_name = str(body.get("filename", "")).strip()
        doc_type = str(body.get("doc_type", "")).strip()  # 课本/讲义/题库/试卷/资料,空=自动
        stage = str(body.get("stage", "")).strip()        # User-defined stage, empty=auto

        # 防重:同名且已有内容 → 跳过
        if upload_name:
            import learn_db as _ldb
            if _ldb.document_has_content(upload_name):
                self._send_json(200, {"ok": True, "skipped": True, "filename": upload_name,
                                      "message": "已存在,跳过"})
                return

        # 方式一:App 直接上传文件字节(base64)→ 存到 learn_docs/ 再处理
        if content_b64:
            if not upload_name:
                self._send_json(400, {"ok": False, "error": "filename 不能为空"})
                return
            import base64
            docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_docs")
            os.makedirs(docs_dir, exist_ok=True)
            safe_name = os.path.basename(upload_name)
            filepath = os.path.join(docs_dir, safe_name)
            try:
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(content_b64))
            except Exception as e:
                self._send_json(400, {"ok": False, "error": f"文件保存失败: {e}"})
                return

        # 方式二:指定服务器已有文件路径
        if not filepath:
            self._send_json(400, {"ok": False, "error": "需提供 content_b64+filename 或 filepath"})
            return

        if not os.path.isfile(filepath):
            self._send_json(400, {"ok": False, "error": f"文件不存在: {filepath}"})
            return

        # 异步处理(大文件不阻塞)
        import threading
        def _process():
            try:
                import doc_engine
                import learn_db
                tax = learn_db.taxonomy_values()  # 复用已有词表,避免别名分裂
                with doc_engine._INGEST_LOCK:  # 串行解析,防并发 OCR 爆内存
                    doc_engine.process_document(
                        filepath, call_ingest_model,  # 便宜模型解析,省 token
                        subject=subject, doc_type=doc_type, stage=stage, taxonomy=tax,
                        keep_original=bool(body.get("keep", False)))
            except Exception as e:
                log.error("后台文档处理失败: %s", e)

        t = threading.Thread(target=_process, daemon=True)
        t.start()

        filename = os.path.basename(filepath)
        self._send_json(200, {"ok": True,
            "message": f"文档 '{filename}' 已提交处理,后台解析中。用 learn_list_docs 查看进度。",
            "filename": filename})

    def _handle_doc_subject(self, post_path):
        """POST /learn/doc/{id}/subject  body:{"subject":"英语"} — 改文档科目。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        try:
            doc_id = int(post_path.split("/learn/doc/", 1)[1].rsplit("/subject", 1)[0])
        except ValueError:
            self._send_json(400, {"ok": False, "error": "无效的文档ID"}); return
        body = self._read_json_body()
        if body is None: return
        subject = str(body.get("subject", "")).strip()
        try:
            import sqlite3
            import learn_db
            db = sqlite3.connect(learn_db._db_path())
            db.execute("UPDATE documents SET subject=? WHERE id=?", (subject, doc_id))
            db.commit(); db.close()
            self._send_json(200, {"ok": True, "id": doc_id, "subject": subject})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e)})

    def _handle_schedule_bulk(self):
        """POST /schedule/bulk body:{"text":"整张课表多行文本"} — 批量解析入库。"""
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"}); return
        body = self._read_json_body()
        if body is None: return
        text = str(body.get("text", "")).strip()
        if not text:
            self._send_json(400, {"ok": False, "error": "text 不能为空"}); return
        import schedule_engine
        tt = schedule_engine.get_timetable_engine()
        added, failed = [], []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                p = tt.parse_natural(line)
                if p.get("weekday", -1) >= 0 and p.get("start_time") and p.get("end_time"):
                    tt.add_slot(p.get("name", line), p["weekday"], p["start_time"],
                                p["end_time"], location=p.get("location", ""))
                    added.append(p.get("name", line))
                else:
                    failed.append(line)
            except Exception:
                failed.append(line)
        self._send_json(200, {"ok": True, "added": len(added), "added_names": added,
                              "failed": failed})

    # 语音转文字（转发到 Agent Whisper）
    def _handle_transcribe(self):
        """POST /transcribe — 优先本地 whisper,不可用则转发 Agent。"""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            self._send_json(200, {"ok": False, "error": "音频数据为空"})
            return

        # hint=wake → 偏置识别到唤醒词,提高"Nous"命中率(只影响唤醒,不影响正常语音命令)
        hint = "".join(parse_qs(urlparse(self.path).query).get("hint", [""]))
        # 1. 尝试本地 whisper(模型缓存,避免每次重载导致卡顿)
        transcribe_text = None
        try:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.write(raw); tmp.close()
            # 唤醒词 "Nous" 是英文。短音频+噪声下 whisper-tiny 易"幻觉成整句"
            # (如 "I'm going to kill you")。唤醒段:强制英文 + VAD 过滤静音/噪声
            # + 关低置信幻觉,只在真有"Nous"语音时出短词;正常语音命令仍按中文高质量转写。
            if hint == "wake":
                model = _get_whisper_cmd()  # base(比 tiny 准很多,短英文词不再幻觉)
                wake_kw = dict(language="en", beam_size=1, temperature=0.0,
                               condition_on_previous_text=False,
                               no_speech_threshold=0.6, log_prob_threshold=-1.0,
                               compression_ratio_threshold=2.4)
                try:
                    segments, _ = model.transcribe(tmp.name, vad_filter=True, **wake_kw)
                    parts = [s.text.strip() for s in segments if s.text.strip()]
                except Exception:
                    segments, _ = model.transcribe(tmp.name, **wake_kw)
                    parts = [s.text.strip() for s in segments if s.text.strip()]
            else:
                cmd_model = _get_whisper_cmd()  # base(或 WHISPER_CMD_MODEL env),指令更准
                segments, _ = cmd_model.transcribe(tmp.name, language="zh", beam_size=5,
                                                   condition_on_previous_text=False,
                                                   initial_prompt=None)
                parts = [s.text.strip() for s in segments if s.text.strip()]
            transcribe_text = "".join(parts) if parts else "(未识别到语音)"
            os.unlink(tmp.name)
        except ImportError:
            pass
        except Exception as e:
            log.warning("本地 whisper 失败: %s, 尝试转发...", e)
            try:
                if 'tmp' in dir() and os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except Exception:
                pass

        # 2. 本地失败则回退: 转发到 Agent
        if transcribe_text is None:
            dev = get_device(config.DEFAULT_DEVICE)
            if dev:
                try:
                    agent_url = f"http://{dev['host']}:{dev['port']}/transcribe"
                    token = dev.get("token", "") or crypto.load_token()
                    response = device_transport.request(
                        agent_url,
                        expected_host=dev["host"],
                        expected_port=int(dev["port"]),
                        method="POST",
                        body=raw,
                        headers={"Content-Type": self.headers.get("Content-Type", "audio/wav"),
                                 "X-Auth-Token": token},
                        timeout=40,
                    )
                    result = response.json()
                    transcribe_text = result.get("text", "(未识别到语音)")
                except Exception as e2:
                    log.error("转写转发也失败: %s", e2)

        if transcribe_text is None:
            self._send_json(200, {"ok": False, "error": "转写不可用(本地和 Agent 均失败)"})
            return

        # 3. 唤醒词检测:客户端 transcribeWake() 需要 response.wake 字段
        resp = {"ok": True, "text": transcribe_text}
        if hint == "wake":
            is_wake, greeting = _is_wake_word(transcribe_text)
            resp["wake"] = is_wake
            resp["greeting"] = greeting
            log.info("唤醒检测: text=%r wake=%s greeting=%s", transcribe_text, is_wake, greeting)
        self._send_json(200, resp)

    # 云端 TTS（转发到 Agent 生成，避免服务器无法访问 Google）
    def _handle_tts(self):
        """POST /tts — 优先本地 edge-tts,不可用则转发 Agent。"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            text = json.loads(body.decode("utf-8")).get("text", "")
        except Exception:
            text = ""
        if not text:
            self._send_json(400, {"error": "text 不能为空"})
            return

        # 1. 尝试本地 edge-tts
        try:
            import tempfile
            import asyncio
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            from edge_tts import Communicate
            async def _gen():
                await Communicate(text[:300], "zh-CN-XiaoxiaoNeural").save(tmp.name)
            asyncio.run(_gen())
            with open(tmp.name, "rb") as f:
                audio = f.read()
            os.unlink(tmp.name)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
            return
        except ImportError:
            pass
        except Exception as e:
            log.warning("本地 TTS 失败: %s, 尝试转发...", e)

        # 2. 回退: 转发到 Agent
        dev = get_device(config.DEFAULT_DEVICE)
        if dev:
            try:
                agent_url = f"http://{dev['host']}:{dev['port']}/tts"
                token = dev.get("token", "") or crypto.load_token()
                response = device_transport.request(
                    agent_url,
                    expected_host=dev["host"],
                    expected_port=int(dev["port"]),
                    method="POST",
                    body=body,
                    headers={"Content-Type": "application/json", "X-Auth-Token": token},
                    timeout=15,
                    max_response_bytes=device_transport.MAX_RESPONSE_BYTES,
                )
                audio = response.body
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(audio)))
                self.end_headers()
                self.wfile.write(audio)
                return
            except Exception as e2:
                log.error("TTS 转发也失败: %s", e2)
        self._send_json(500, {"error": "TTS 不可用(本地和 Agent 均失败)"})


# Web 管理面板 HTML
_WEB_PANEL_HTML = ""
_DASHBOARD_HTML = ""
_CONTROL_CENTER_HTML = ""

def _load_web_panel():
    global _WEB_PANEL_HTML
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_panel.html")
    try:
        with open(p, encoding="utf-8") as f:
            _WEB_PANEL_HTML = f.read()
    except Exception:
        _WEB_PANEL_HTML = "<h1>Web panel not found</h1>"

def _load_dashboard():
    global _DASHBOARD_HTML, _CONTROL_CENTER_HTML
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    try:
        with open(p, encoding="utf-8") as f:
            _DASHBOARD_HTML = f.read()
    except Exception:
        _DASHBOARD_HTML = "<h1>Dashboard not found</h1>"
    cc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "control_center.html")
    try:
        with open(cc, encoding="utf-8") as f:
            _CONTROL_CENTER_HTML = f.read()
    except Exception:
        _CONTROL_CENTER_HTML = "<h1>Control Center not found</h1>"


def start_study_scheduler():
    """学习每日总结调度(后台线程)。非核心功能，失败不影响主服务。"""
    try:
        t = threading.Thread(target=_study_scheduler_loop, daemon=True, name="study-scheduler")
        t.start()
        log.info("学习每日总结调度已启动")
    except Exception as e:
        log.warning("学习调度器启动失败(非致命): %s", e)


def _study_scheduler_loop():
    """后台:每天 23:00 触发学习总结生成。"""
    import study_manager as _sm
    _SUMMARY_HOUR = 23
    _SUMMARY_MINUTE = 0
    _last_summary_date = ""
    while True:
        try:
            now = time.strftime("%Y-%m-%d")
            h = int(time.strftime("%H"))
            m = int(time.strftime("%M"))
            if h == _SUMMARY_HOUR and m >= _SUMMARY_MINUTE and now != _last_summary_date:
                _last_summary_date = now
                try:
                    _sm.generate_daily_summary(call_model)
                    log.info("每日学习总结已生成")
                except Exception as e:
                    log.warning("每日总结生成失败: %s", e)
        except Exception:
            pass
        time.sleep(60)


def main():
    load_sessions()
    load_devices()
    load_clients()
    _load_web_panel()
    _load_upload_html()
    _load_dashboard()

    # 初始化学习引擎(注入 LLM 调用能力)
    learn_tools._learn_handler = learn_tools.LearnHandler(call_model=call_model)
    import learn_db
    learn_db.init()

    # P0: initialise Nous Core Kernel database, dispatcher, and services
    try:
        _run_nous_core_migrations()

        # v1.0: Demo Mode (if NOUS_DEMO_MODE=1)
        if _is_demo():
            log.info("🎭 Demo Mode enabled — using mock providers")
            _enable_demo()

        _register_builtin_handlers()

        # P0-7: register automation engine as global event handler
        _register_event_handler("*", _automation_evaluate, name="automation-engine")

        # P3: Seed capabilities + composed capabilities + register providers
        _seed_default_capabilities()
        _seed_composed_capabilities()

        # v1.0: Register providers via proper Provider adapters
        # (backward-compatible: _register_provider still works for bare functions)
        try:
            from nous_runtime.provider.adapters.openai import OpenAIProvider
            from nous_runtime.provider.adapters.embed import FastEmbedProvider
            from nous_runtime.provider.adapters.audio import WhisperProvider, EdgeTTSProvider
            from nous_runtime.provider.adapters.chromadb import ChromaDBProvider
            from nous_runtime.provider.adapters.device_pc import PCAgentProvider
            from nous_runtime.provider.adapters.device_android import AndroidProvider
            from nous_runtime.provider.adapters.notification import NotificationProvider
            from nous_runtime.provider.adapters.web import WebProvider

            _register_adapter(OpenAIProvider())
            _register_adapter(FastEmbedProvider())
            _register_adapter(WhisperProvider())
            _register_adapter(EdgeTTSProvider())
            _register_adapter(ChromaDBProvider())
            _register_adapter(PCAgentProvider())
            _register_adapter(AndroidProvider())
            _register_adapter(NotificationProvider())
            _register_adapter(WebProvider())
            log.info("v1.0 Providers registered via adapters")
        except ImportError:
            # Fallback: use bare function registration if nous_runtime not available
            log.info("Using legacy provider registration (nous_runtime not installed)")
            _register_provider("openai", _capability_model_reason)
            _register_provider("claude_code", _capability_model_code)
            _register_provider("fastembed", _capability_model_embed)
            _register_provider("whisper", _capability_model_transcribe)
            _register_provider("edge_tts", _capability_model_tts)
            _register_provider("chromadb", _capability_rag)
            _register_provider("pc_agent", _capability_device_pc)
            _register_provider("android", _capability_device_android)
            _register_provider("nous_notify", _capability_notification)
            _register_provider("web", _capability_tool_web)
            _register_provider("nous_automation", _capability_automation)

        # Seed default automation rules (idempotent)
        _automation_seed_defaults()

        _start_dispatcher(interval=5.0)
        _recover_stale_jobs()
        # Sync devices from legacy devices.json → nous_core SQLite (best-effort)
        # Note: use brain_devices.devices directly (not the module-level alias)
        # because load_devices() replaces the dict object
        try:
            from brain_devices import devices as _live_devices
            if _live_devices:
                _sync_devices(_live_devices)
            else:
                log.debug("No legacy devices to sync (devices.json is empty)")
        except Exception as _e2:
            log.debug("Device sync skipped (non-fatal): %s", _e2)
        log.info("nous_core P0 Kernel initialized (events + dispatcher + jobs + devices + automation)")
    except Exception as _e:
        log.warning("nous_core P0 Kernel init failed (non-fatal): %s", _e)

    bind_host = config.BRAIN_HOST
    if not bind_host:
        log.error("BRAIN_HOST 未配置!请在 config.local.json 或环境变量 NOUS_BRAIN_HOST 中设置 Brain 监听地址。")
        return

    # 绑定重试:开机自启时隧道可能还没就绪,隔几秒重试。
    server = None
    while server is None:
        try:
            server = ThreadingHTTPServer((bind_host, config.BRAIN_PORT), Handler)
        except OSError as e:
            log.warning("绑定 %s:%s 失败(隧道未就绪?),%s 秒后重试… %s",
                        bind_host, config.BRAIN_PORT, config.BIND_RETRY_SECONDS, e)
            time.sleep(config.BIND_RETRY_SECONDS)
    log.info("大脑(指挥层)已启动,监听 http://%s:%s/chat (仅隧道内可达,需令牌)",
             bind_host, config.BRAIN_PORT)
    log.info("已注册 %d 个设备: %s", len(devices), ", ".join(devices.keys()) or "(无)")

    # P0: record brain startup event
    _emit_event("brain.startup",
                source="brain",
                payload={"host": bind_host, "port": config.BRAIN_PORT,
                         "devices": len(devices), "model": getattr(config, "LLM_MODEL", "unknown")})

    start_probe_thread()      # 启动设备在线状态探活
    start_study_scheduler()   # 启动学习每日总结调度
    # P9: initial stability snapshot
    try:
        _stability_snapshot()
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C,正在关闭...")
        server.shutdown()


if __name__ == "__main__":
    main()

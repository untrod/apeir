# -*- coding: utf-8 -*-
"""
大脑会话存储 — 管理所有对话会话的持久化。

从 brain.py 提取。依赖:config, brain_devices。
"""
import json as _json
import logging as _logging
import os as _os
import time as _time

import threading as _threading

import config as _config
import brain_devices as _devices

_log = _logging.getLogger("brain")

SESSIONS_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "sessions.json")

sessions = {}  # {session_id: {"messages":[...], "cwd":str, "summary":str, "updated":float}}
_sessions_lock = _threading.Lock()  # 保护 sessions dict 的并发读写

# 会话生命周期配置(可通过 env 覆盖)
_SESSION_MAX = int(_os.environ.get("NOUS_SESSION_MAX", "100"))    # 最多保留会话数
_SESSION_TTL = int(_os.environ.get("NOUS_SESSION_TTL", "604800"))  # 7天未活跃则清理(秒)


def _cleanup_expired():
    """清理过期和超量会话(需在持有 _sessions_lock 时调用)。"""
    global sessions
    now = _time.time()
    # 1) 按 TTL 清理
    stale = [sid for sid, s in sessions.items()
             if now - s.get("updated", 0) > _SESSION_TTL]
    for sid in stale:
        del sessions[sid]
    if stale:
        _log.info("清理 %d 个过期会话(>%d天未活跃)", len(stale), _SESSION_TTL // 86400)
    # 2) 按数量上限清理(删最旧的)
    if len(sessions) > _SESSION_MAX:
        sorted_sids = sorted(sessions, key=lambda sid: sessions[sid].get("updated", 0))
        overflow = sorted_sids[:len(sessions) - _SESSION_MAX]
        for sid in overflow:
            del sessions[sid]
        _log.info("清理 %d 个超量会话(超出上限 %d)", len(overflow), _SESSION_MAX)


def load_sessions():
    global sessions
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            loaded = _json.load(f)
        with _sessions_lock:
            sessions = loaded
        _log.info("已加载 %d 个历史会话", len(sessions))
    except FileNotFoundError:
        with _sessions_lock:
            sessions = {}
    except _json.JSONDecodeError as e:
        _log.error("sessions.json 损坏(%s),尝试从备份恢复", e)
        # 尝试从 .bak 恢复
        bak = SESSIONS_FILE + ".bak"
        try:
            with open(bak, encoding="utf-8") as f:
                sessions = _json.load(f)
            _log.info("已从 .bak 恢复 %d 个会话", len(sessions))
        except Exception:
            with _sessions_lock:
                sessions = {}
            _log.error("备份也损坏,会话已重置为空")
    except Exception as e:
        _log.error("加载会话异常: %s", e)
        with _sessions_lock:
            sessions = {}

def save_sessions():
    """原子写入:先写 .tmp 再 rename,防止写入中断导致文件损坏。
    写入前备份当前文件到 .bak(可恢复)。"""
    import os as _os2
    tmp = SESSIONS_FILE + ".tmp"
    try:
        with _sessions_lock:
            _cleanup_expired()     # 先清理过期/超量会话
            data = dict(sessions)  # 快照,避免持锁期间 IO
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        # 备份当前文件(如果存在且有效)
        if _os2.path.exists(SESSIONS_FILE):
            try:
                _os2.replace(SESSIONS_FILE, SESSIONS_FILE + ".bak")
            except OSError:
                pass
        _os2.replace(tmp, SESSIONS_FILE)  # 原子重命名（跨平台）
    except Exception as e:
        _log.error("保存会话失败: %s", e)
        try:
            if _os2.path.exists(tmp):
                _os2.unlink(tmp)
        except Exception:
            pass

def get_session(sid, target_device=None):
    with _sessions_lock:
        s = sessions.get(sid)
        if not s:
            dev_id = target_device or _config.DEFAULT_DEVICE
            s = {"messages": [], "cwd": _devices.get_default_cwd(dev_id), "summary": "",
                 "updated": _time.time(), "target_device": dev_id}
            sessions[sid] = s
    if target_device and s.get("target_device") != target_device:
        s["target_device"] = target_device
        s["cwd"] = _devices.get_default_cwd(target_device)
    return s

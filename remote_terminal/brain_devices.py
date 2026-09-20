# -*- coding: utf-8 -*-
"""
大脑设备注册表 — 管理所有被控设备的注册、探活、路由。

从 brain.py 提取。依赖:config。
"""
import json as _json
import logging as _logging
import os as _os
import time as _time
import threading as _threading

import config as _config
import device_transport as _device_transport

_log = _logging.getLogger("brain")

# P0: event recording (lazy import to avoid circular deps)
def _emit_device_event(event_type: str, device_id: str, **kw):
    """Fire-and-forget event emit. Never raises."""
    try:
        from nous_core.events import emit_event
        emit_event(event_type, source="brain", device_id=device_id, payload=kw)
    except Exception:
        pass

# 全局设备表 {device_id: {"name","host","port","token","os","capabilities","default_cwd","last_seen"}}
devices = {}
_devices_lock = _threading.Lock()  # 保护 devices dict 的并发读写(探活线程 + 请求线程)

# 探活参数
_PROBE_INTERVAL = 30      # 探活间隔(秒)
_PROBE_TIMEOUT = 4        # 单次探活超时(秒)
_OFFLINE_AFTER = 75       # 超过此秒数没探到 → 判离线



def _devices_file():
    return getattr(_config, "DEVICES_FILE", "") or _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "devices.json")

def load_devices():
    global devices
    path = _devices_file()
    try:
        with open(path, encoding="utf-8") as f:
            loaded = _json.load(f)
        with _devices_lock:
            devices = loaded
        _log.info("已加载 %d 个设备: %s", len(devices), ", ".join(devices.keys()))
    except FileNotFoundError:
        with _devices_lock:
            devices = {}
        _log.warning("设备注册表 %s 不存在,无已注册设备", path)
    except Exception as e:
        with _devices_lock:
            devices = {}
        _log.error("加载设备注册表失败: %s", e)

def save_devices():
    path = _devices_file()
    try:
        with _devices_lock:
            data = dict(devices)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.error("保存设备注册表失败: %s", e)

def get_device(device_id: str) -> dict:
    """获取设备信息。找不到时返回 None。"""
    with _devices_lock:
        return devices.get(device_id)

def get_default_cwd(device_id: str) -> str:
    """获取设备的默认工作目录。"""
    dev = get_device(device_id)
    if dev:
        return dev.get("default_cwd", "/root" if dev.get("os") != "windows" else "C:\\")
    if _os.name == "nt":
        return _os.environ.get("USERPROFILE") or "C:\\"
    return _os.environ.get("HOME") or "/root"

def is_device_online(dev: dict) -> bool:
    """根据 last_seen 判断设备是否在线。"""
    return (_time.time() - dev.get("last_seen", 0)) < _OFFLINE_AFTER

def _probe_device(did: str, dev: dict):
    """探测单个设备 agent 的健康检查端点。通则更新 last_seen。"""
    host, port = dev.get("host", ""), dev.get("port", 0)
    if not host or not port:
        return
    was_online = is_device_online(dev)
    url = f"http://{host}:{port}/"
    try:
        resp = _device_transport.request(
            url,
            expected_host=host,
            expected_port=int(port),
            method="GET",
            timeout=_PROBE_TIMEOUT,
            max_response_bytes=64 * 1024,
        )
        if resp.status_code == 200:
            with _devices_lock:
                dev["last_seen"] = _time.time()
            # P0: emit heartbeat event
            _emit_device_event("device.heartbeat", did, host=host, port=port)
            if not was_online:
                _log.info("设备上线: %s (%s:%s)", did, host, port)
                _emit_device_event("device.online", did, host=host, port=port)
    except Exception:
        # P0: detect offline transition
        if was_online:
            since = _time.time() - dev.get("last_seen", 0)
            if since >= _OFFLINE_AFTER:
                _log.info("设备离线: %s (%s:%s, 最后一次探活 %.0fs 前)", did, host, port, since)
                _emit_device_event("device.offline", did, host=host, port=port,
                                   last_seen_seconds_ago=round(since, 1))

def _probe_loop():
    """后台探活循环。"""
    while True:
        try:
            with _devices_lock:
                snapshot = list(devices.items())
            for did, dev in snapshot:
                _probe_device(did, dev)
        except Exception as e:
            _log.error("设备探活异常: %s", e)
        _time.sleep(_PROBE_INTERVAL)

def start_probe_thread():
    """启动设备探活后台线程(daemon,随主进程退出)。"""
    t = _threading.Thread(target=_probe_loop, daemon=True, name="device-probe")
    t.start()
    _log.info("设备探活线程已启动(每 %ds 探测一次)", _PROBE_INTERVAL)

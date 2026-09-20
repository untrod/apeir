# -*- coding: utf-8 -*-
"""
大脑客户端注册表 — 管理连接 Brain 的控制端(手机/平板/手表)。

从 brain.py 提取。依赖:config。
"""
import hmac as _hmac
import json as _json
import logging as _logging
import os as _os

import config as _config

_log = _logging.getLogger("brain")

clients = {}          # {client_id: {...}}
_token_to_client = {} # 反查: token -> client_id

def _clients_file():
    return getattr(_config, "CLIENTS_FILE", "") or _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "clients.json")

def load_clients():
    global clients, _token_to_client
    path = _clients_file()
    try:
        with open(path, encoding="utf-8") as f:
            clients = _json.load(f)
    except FileNotFoundError:
        clients = {}
    except Exception as e:
        clients = {}
        _log.error("加载客户端注册表失败: %s", e)
    _token_to_client = {}
    for cid, c in clients.items():
        if c.get("disabled"):
            continue
        tok = c.get("token", "")
        if tok:
            _token_to_client[tok] = cid
    _log.info("已加载 %d 个客户端: %s", len(clients), ", ".join(clients.keys()) or "(无)")

def resolve_client(token: str) -> str:
    """根据 token 解析客户端身份。返回 client_id;命中遗留 AUTH_TOKEN 返回 'legacy';无效返回空串。"""
    if not token:
        return ""
    for cid, c in clients.items():
        if c.get("disabled"):
            continue
        tok = c.get("token", "")
        if tok and _hmac.compare_digest(token, tok):
            return cid
    legacy = _config.AUTH_TOKEN
    if legacy and _hmac.compare_digest(token, legacy):
        return "legacy"
    return ""

def client_tool_profile(cid: str) -> str:
    """客户端的工具档位。缺省 full。手表设 learn 档→只发学习工具。"""
    c = clients.get(cid)
    if c and c.get("tool_profile"):
        return c["tool_profile"]
    return "full"

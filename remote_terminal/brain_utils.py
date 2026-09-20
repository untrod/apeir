# -*- coding: utf-8 -*-
"""
brain 通用工具:HTTP 小工具 + 输出截断 + transcript 审计 + token 用量追踪。

从 brain.py 提取。依赖:config, brain_latex。
"""
import json as _json
import logging as _logging
import os as _os
import re as _re
import time as _time

import config as _config
import device_transport as _device_transport

_log = _logging.getLogger("brain")

# HTTP helper retained for brain compatibility, now bound to Device Transport Authority.
def post_json(url, payload, timeout, headers=None, *, expected_host, expected_port):
    return _device_transport.request_json(
        url,
        payload,
        expected_host=expected_host,
        expected_port=expected_port,
        timeout=timeout,
        headers=headers,
    )

# 输出截断
def truncate(s):
    """把过长输出截断:留头+尾,中间标注截断了多少,避免炸上下文。"""
    limit = _config.TOOL_OUTPUT_MAX_CHARS
    if len(s) <= limit:
        return s
    head = s[: int(limit * 0.7)]
    tail = s[-int(limit * 0.25):]
    return f"{head}\n...[输出过长,已截断约 {len(s) - len(head) - len(tail)} 字]...\n{tail}"


def mask_sensitive(text: str) -> str:
    """Mask common secrets before writing logs or transcript files."""
    if not isinstance(text, str) or not text:
        return text
    patterns = [
        (r'sk-[a-zA-Z0-9_-]{16,}', 'sk-***MASKED***'),
        (r'Bearer\s+[a-zA-Z0-9._-]{16,}', 'Bearer ***MASKED***'),
        (r'(api[_-]?key|token|password|secret)\s*[=:]\s*["\']?[^\s"\']+', r'\1=***MASKED***'),
        (r'(X-Auth-Token["\']?\s*[:=]\s*["\']?)[a-zA-Z0-9._-]{12,}', r'\1***MASKED***'),
    ]
    out = text
    for pat, repl in patterns:
        out = _re.sub(pat, repl, out, flags=_re.IGNORECASE)
    return out


def _mask_entry(obj):
    """Recursively mask string values in transcript entries."""
    if isinstance(obj, str):
        return mask_sensitive(obj)
    if isinstance(obj, list):
        return [_mask_entry(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _mask_entry(v) for k, v in obj.items()}
    return obj


# 审计 transcript
_TRANSCRIPT_DIR = getattr(_config, "TRANSCRIPT_DIR", None) or _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "sessions"
)

def _ensure_transcript_dir():
    try:
        _os.makedirs(_TRANSCRIPT_DIR, exist_ok=True)
    except OSError:
        pass

def write_transcript(session_id: str, entry: dict, session: dict = None):
    """
    向会话的审计 transcript 追加一条记录。
    格式:每行一条 JSON(便于追加,不重写全文件)。
    """
    _ensure_transcript_dir()
    entry.setdefault("timestamp", _time.strftime("%Y-%m-%dT%H:%M:%S"))
    entry.setdefault("session_id", session_id)
    if session:
        entry.setdefault("target_device", session.get("target_device", ""))
        entry.setdefault("source_ip", session.get("_source_ip", ""))
        entry.setdefault("source_client", session.get("_source_client", ""))
    entry = _mask_entry(entry)
    path = _os.path.join(_TRANSCRIPT_DIR, f"{session_id}.transcript.jsonl")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        _log.error("写入 transcript 失败: %s", e)


# Token 用量追踪
_USAGE_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "llm_usage.json")

def _load_pricing():
    """Load model pricing from env. Prices are per 1M tokens."""
    raw = _os.environ.get("NOUS_MODEL_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = _json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        _log.warning("NOUS_MODEL_PRICING_JSON 解析失败: %s", e)
        return {}

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate LLM cost from configured per-1M-token prices."""
    pricing = _load_pricing()
    p = pricing.get(model) or pricing.get(str(model).lower()) or {}
    if not isinstance(p, dict):
        return 0.0
    try:
        input_price = float(p.get("input", 0) or 0)
        output_price = float(p.get("output", 0) or 0)
        return round((prompt_tokens / 1_000_000) * input_price +
                     (completion_tokens / 1_000_000) * output_price, 8)
    except Exception:
        return 0.0

def _load_usage():
    try:
        if _os.path.exists(_USAGE_FILE):
            with open(_USAGE_FILE, encoding="utf-8") as f:
                return _json.load(f)
    except Exception:
        pass
    return {}

def _save_usage(data):
    try:
        with open(_USAGE_FILE, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.error("保存用量失败: %s", e)

def record_usage(model, prompt_tokens, completion_tokens, cost=0):
    """记录 LLM token 用量到本地文件,便于统计费用。"""
    today = _time.strftime("%Y-%m-%d")
    if not cost:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
    data = _load_usage()
    data.setdefault(today, {"models": {}, "total_prompt": 0, "total_completion": 0, "total_cost": 0})
    day = data[today]
    day["total_prompt"] += prompt_tokens
    day["total_completion"] += completion_tokens
    day["total_cost"] += cost
    day["models"].setdefault(model, {"prompt": 0, "completion": 0, "cost": 0})
    day["models"][model]["prompt"] += prompt_tokens
    day["models"][model]["completion"] += completion_tokens
    day["models"][model]["cost"] += cost
    _save_usage(data)

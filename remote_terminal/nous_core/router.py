# -*- coding: utf-8 -*-
"""
Model Router — intelligent task-to-model routing.

Not "default GPT" — analyze the task, pick the best model.

Routing rules:
  math/derivation    → deepseek (strong at math)
  code/generation    → claude (strong at code)
  summary/extraction → gpt (fast, cheap)
  knowledge/search   → rag (vector search)
  translation        → deepseek (multilingual)
  creative/writing   → claude (nuanced)
  analysis/reasoning → claude (deep thinking)
  quick/simple       → local (no cost, fast)

Future: vision, audio, specialized domain models.

Usage:
  from nous_core.router import route

  model, provider, reason = route("求 x^2 + 2x + 1 = 0 的解")
  # → ("deepseek-chat", "openai", "Math problem → DeepSeek")
"""

from __future__ import annotations

import re as _re
import logging as _logging

_log = _logging.getLogger("nous_core.router")

# Task type → (model, provider, priority)
_ROUTING_TABLE: list[tuple[str, list[str], str, str, str]] = [
    # (task_type, keywords, model, provider, reason_template)
    ("math", [
        "求", "解", "计算", "推导", "证明", "方程", "函数", "导数", "积分",
        "极限", "矩阵", "概率", "统计", "几何", "代数", "微积分", "线性",
        "solve", "calculate", "derive", "prove", "equation", "integral",
        "derivative", "matrix", "probability",
    ], "deepseek-chat", "openai", "数学推理 → DeepSeek"),

    ("code", [
        "代码", "编程", "实现", "写一个", "函数", "class", "def", "bug",
        "报错", "重构", "测试", "构建", "部署", "API", "接口",
        "code", "implement", "function", "class", "bug", "error",
        "refactor", "test", "build", "deploy", "api",
    ], "claude-sonnet-4-6", "anthropic", "代码生成 → Claude"),

    ("knowledge", [
        "知识点", "复习", "什么是", "定义", "概念", "原理", "总结", "概述",
        "讲义", "笔记", "课程", "章节", "资料", "文档",
        "knowledge", "review", "definition", "concept", "summary",
        "lecture", "chapter", "document",
    ], "deepseek-chat", "openai", "知识检索 → RAG + DeepSeek"),

    ("translation", [
        "翻译", "英文", "中文", "日语", "韩语", "文言文", "古文",
        "translate", "english", "chinese", "japanese", "korean",
    ], "deepseek-chat", "openai", "翻译 → DeepSeek"),

    ("creative", [
        "写", "作文", "文章", "诗", "故事", "创意", "设计", "想象",
        "write", "essay", "poem", "story", "creative", "design",
    ], "claude-sonnet-4-6", "anthropic", "创作 → Claude"),

    ("analysis", [
        "分析", "诊断", "评估", "比较", "对比", "优劣", "建议", "推荐",
        "为什么", "原因", "影响", "后果", "如何", "怎么",
        "analyze", "diagnose", "evaluate", "compare", "why",
        "how", "recommend", "impact",
    ], "claude-sonnet-4-6", "anthropic", "深度分析 → Claude"),

    ("quick", [
        "你好", "谢谢", "再见", "是的", "不对", "OK", "ok",
        "hello", "thanks", "bye", "yes", "no", "hi", "hey",
    ], "deepseek-chat", "openai", "快速回复 → DeepSeek"),
]

# Default fallback
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_PROVIDER = "openai"


def route(task_text: str) -> tuple[str, str, str]:
    """
    Analyze task text and route to the best model.

    Returns: (model_name, provider_name, reason)
    """
    if not task_text or not isinstance(task_text, str):
        return (_DEFAULT_MODEL, _DEFAULT_PROVIDER, "Empty input → default")

    text = task_text.lower().strip()

    # Check for explicit model request: #claude, #gpt, #deepseek
    explicit = _re.search(r'#(\w+)', text)
    if explicit:
        tag = explicit.group(1).lower()
        if tag in ("claude", "sonnet"):
            return ("claude-sonnet-4-6", "anthropic", "Explicit #claude tag")
        if tag in ("gpt", "openai", "chatgpt"):
            return ("gpt-4o", "openai", "Explicit #gpt tag")
        if tag in ("deepseek", "ds"):
            return ("deepseek-chat", "openai", "Explicit #deepseek tag")
        if tag in ("local", "本地"):
            return ("local", "local", "Explicit #local tag")
        if tag in ("rag", "搜索", "search"):
            return ("rag", "chromadb", "Explicit #rag tag")

    # Score each routing rule
    best_score = 0
    best_match = (_DEFAULT_MODEL, _DEFAULT_PROVIDER, "No match → default")

    for task_type, keywords, model, provider, reason_tpl in _ROUTING_TABLE:
        score = sum(1 for kw in keywords if kw in text)
        # Longer keyword matches get bonus
        score += sum(2 for kw in keywords if len(kw) >= 3 and kw in text)
        if score > best_score:
            best_score = score
            best_match = (model, provider, reason_tpl)

    _log.debug("Router: '%s...' → %s (score=%d)", task_text[:50], best_match[0], best_score)
    return best_match


def get_model_config(model_name: str) -> dict:
    """Get configuration for a routed model name."""
    configs = {
        "deepseek-chat": {"base_url": "https://api.deepseek.com/v1/chat/completions",
                          "max_tokens": 4096, "temperature": 0.0},
        "claude-sonnet-4-6": {"base_url": "https://api.anthropic.com/v1/messages",
                              "max_tokens": 4096, "temperature": 0.0},
        "gpt-4o": {"base_url": "https://api.openai.com/v1/chat/completions",
                   "max_tokens": 4096, "temperature": 0.0},
        "deepseek-reasoner": {"base_url": "https://api.deepseek.com/v1/chat/completions",
                              "max_tokens": 8192, "temperature": 0.0, "reasoning": True},
    }
    return configs.get(model_name, {"base_url": "", "max_tokens": 4096, "temperature": 0.0})


def list_routing_rules() -> list[dict]:
    """Export routing table for dashboard/audit."""
    return [
        {"task_type": t[0], "keywords_sample": t[1][:5], "model": t[2],
         "provider": t[3], "reason": t[4]}
        for t in _ROUTING_TABLE
    ]

"""Deterministic first-stage chat intent router."""

from __future__ import annotations

import re

from nous_runtime.chat.models import ChatIntent


# Text can request the trusted approval UI, but can never grant approval. Match
# complete short commands so explanations and code mentioning approvals remain
# ordinary engineering input.
_APPROVAL_COMMAND = re.compile(
    r"(?:"
    r"(?:please\s+)?(?:approve(?:d)?|reject(?:ed)?)"
    r"(?:\s+(?:(?:this|that|the)\s+)?(?:action|operation|request|proposal|work|change)"
    r"(?:\s+[\w:#.-]{1,128})?|\s+(?:this|that|it|[\w:#.-]{1,128}))?"
    r"|(?:请)?(?:批准|同意执行|拒绝(?:执行)?)"
    r"(?:(?:该|此|这个|这项)?(?:操作|请求|提案|任务|变更))?"
    r"(?:[：:\s]+[\w:#.-]{1,128})?"
    r")[.!?。！？]*",
    re.IGNORECASE,
)
_WORKFLOW_COMMAND = re.compile(
    r"(?:\b(?:create|run|start|edit|save)\s+(?:(?:a|the|saved)\s+)?workflow\b"
    r"|(?:创建|运行|启动|编辑|保存)(?:一个|这个|已有的)?工作流)"
)
_ENGINEERING = re.compile(
    r"\b(?:code|repository|patch|fix|implement|refactor|debug|build|test|write|create)\b"
    r"|代码|仓库|修复|修改|创建|实现|重构|调试|编译|测试|函数|脚本"
)


def classify_chat(text: str) -> ChatIntent:
    value = text.strip().casefold()
    if _APPROVAL_COMMAND.fullmatch(value):
        return ChatIntent.APPROVAL_RESPONSE
    if _WORKFLOW_COMMAND.search(value):
        return ChatIntent.WORKFLOW_REQUEST
    if _ENGINEERING.search(value):
        return ChatIntent.CODE_TASK
    if any(token in value for token in ("status", "progress", "状态", "进度")):
        return ChatIntent.STATUS_QUERY
    if any(token in value for token in ("workflow", "工作流", "定时任务")):
        return ChatIntent.WORKFLOW_REQUEST
    if any(
        token in value
        for token in ("device", "phone", "watch", "设备", "手机", "手表", "电脑")
    ):
        return ChatIntent.DEVICE_ACTION
    if any(
        token in value
        for token in ("knowledge", "document", "library", "知识", "文档", "资料库")
    ):
        return ChatIntent.KNOWLEDGE_QUERY
    return ChatIntent.CONVERSATION

"""Deterministic first-stage chat intent router."""

from __future__ import annotations

from nous_runtime.chat.models import ChatIntent


def classify_chat(text: str) -> ChatIntent:
    value = text.strip().lower()
    if any(token in value for token in ("approve", "approved", "批准", "同意执行", "reject", "拒绝")):
        return ChatIntent.APPROVAL_RESPONSE
    if any(token in value for token in ("status", "progress", "状态", "进度")):
        return ChatIntent.STATUS_QUERY
    if any(token in value for token in ("workflow", "工作流", "定时任务")):
        return ChatIntent.WORKFLOW_REQUEST
    if any(token in value for token in ("device", "phone", "watch", "设备", "手机", "手表", "电脑")):
        return ChatIntent.DEVICE_ACTION
    if any(token in value for token in ("code", "repository", "patch", "代码", "仓库", "修复", "修改", "创建", "实现")):
        return ChatIntent.CODE_TASK
    if any(token in value for token in ("knowledge", "document", "library", "知识", "文档", "资料库")):
        return ChatIntent.KNOWLEDGE_QUERY
    return ChatIntent.CONVERSATION

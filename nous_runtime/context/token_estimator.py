# -*- coding: utf-8 -*-
"""
Token estimation and context budget management for Nous Runtime.

Implements §7.3 (Context Budget) and §17.1 (Context Optimization) of the
master plan. Provides:

- Approximate token counting (no API call needed)
- Context budget enforcement
- Message retention policies
- Automatic summarization triggers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Token estimator

def estimate_tokens(text: str, model_family: str = "default") -> int:
    """Estimate token count without calling an API.

    Uses character-based heuristics with model-family-specific ratios.
    Not exact but good enough for context budget decisions.

    Heuristics:
    - English: ~4 chars per token
    - Chinese: ~1.5 chars per token
    - Code: ~3 chars per token
    """
    if not text:
        return 0

    # Detect content mix
    chinese_chars = len(re.findall(r'[一-鿿㐀-䶿]', text))
    len(re.findall(r'[{}\[\]();=><|&!]', text))
    total_chars = len(text)

    if model_family == "claude":
        ratio = 4.5  # Claude uses more tokens per char on average
    elif model_family == "gpt":
        ratio = 3.5
    else:
        ratio = 4.0

    # Adjust for Chinese-heavy content
    if total_chars > 0:
        chinese_ratio = chinese_chars / total_chars
        if chinese_ratio > 0.5:
            ratio = ratio * 0.6  # Chinese characters pack more info per token

    return max(1, int(total_chars / ratio))


def estimate_message_tokens(messages: list[dict[str, str]],
                            model_family: str = "default") -> int:
    """Estimate total tokens for a list of messages."""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content", ""), model_family)
        total += 4  # Role marker overhead per message
    return total + 3  # Conversation framing overhead


# Context budget

@dataclass
class ContextBudget:
    """Token budget for a conversation context window."""
    max_tokens: int = 8000
    system_prompt_tokens: int = 0
    reserved_for_response: int = 1000
    used_tokens: int = 0

    @property
    def available(self) -> int:
        return max(0, self.max_tokens - self.system_prompt_tokens -
                   self.reserved_for_response - self.used_tokens)

    @property
    def utilization_ratio(self) -> float:
        if self.max_tokens <= 0:
            return 0.0
        return self.used_tokens / self.max_tokens

    def can_fit(self, tokens: int) -> bool:
        return tokens <= self.available


# Auto-summarizer

class ConversationSummarizer:
    """Automatic conversation summarization for context management.

    When the context budget exceeds a threshold, triggers summarization
    of older messages to keep recent context available.
    """

    SUMMARIZE_THRESHOLD = 0.5   # Summarize early enough to preserve response headroom
    KEEP_RECENT_N = 10          # Always keep the N most recent messages

    def __init__(self, max_tokens: int = 8000, model_family: str = "default"):
        self._max_tokens = max_tokens
        self._model_family = model_family

    def should_summarize(self, messages: list[dict[str, str]],
                         system_prompt: str = "") -> bool:
        """Check if the conversation needs summarization."""
        total = estimate_tokens(system_prompt, self._model_family)
        total += estimate_message_tokens(messages, self._model_family)
        budget = ContextBudget(max_tokens=self._max_tokens,
                               system_prompt_tokens=estimate_tokens(system_prompt, self._model_family),
                               used_tokens=total)
        return budget.utilization_ratio >= self.SUMMARIZE_THRESHOLD

    def build_summary_prompt(self, messages_to_summarize: list[dict[str, str]]) -> str:
        """Build a prompt to ask the model to summarize older messages."""
        conversation_text = "\n".join(
            f"[{m.get('role', 'unknown')}]: {m.get('content', '')[:500]}"
            for m in messages_to_summarize
        )
        return (
            "Summarize the following conversation segment concisely. "
            "Retain key facts, decisions, action items, and context that would "
            "be needed to continue the conversation. Output the summary in "
            "2-3 paragraphs.\n\n"
            f"{conversation_text}"
        )

    def incremental_summary(self, current_summary: str,
                            new_messages: list[dict[str, str]]) -> str:
        """Update an existing summary with new messages (incremental)."""
        new_text = "\n".join(
            f"[{m.get('role', 'unknown')}]: {m.get('content', '')[:300]}"
            for m in new_messages
        )
        return (
            f"Previous summary: {current_summary}\n\n"
            f"New messages since last summary:\n{new_text}\n\n"
            "Update the summary to include the new information. "
            "Keep the same level of detail."
        )


# Context Builder enhancement

@dataclass
class ContextAssembly:
    """Assembled context ready for a model call (§7.2)."""
    system_policy: str = ""
    user_profile: str = ""
    recent_messages: list[dict[str, str]] = field(default_factory=list)
    conversation_summary: str = ""
    long_term_memories: list[str] = field(default_factory=list)
    task_state: str = ""
    workspace_context: str = ""
    retrieval_context: str = ""
    device_state: str = ""
    allowed_capabilities: list[str] = field(default_factory=list)

    def estimate_total_tokens(self, model_family: str = "default") -> int:
        total = 0
        total += estimate_tokens(self.system_policy, model_family)
        total += estimate_tokens(self.user_profile, model_family)
        total += estimate_message_tokens(self.recent_messages, model_family)
        total += estimate_tokens(self.conversation_summary, model_family)
        total += sum(estimate_tokens(m, model_family) for m in self.long_term_memories)
        total += estimate_tokens(self.task_state, model_family)
        total += estimate_tokens(self.workspace_context, model_family)
        total += estimate_tokens(self.retrieval_context, model_family)
        total += estimate_tokens(self.device_state, model_family)
        return total

    def to_prompt(self) -> str:
        """Assemble into a prompt string for the model."""
        parts = []
        if self.system_policy:
            parts.append(f"## System Policy\n{self.system_policy}")
        if self.user_profile:
            parts.append(f"## User Profile\n{self.user_profile}")
        if self.conversation_summary:
            parts.append(f"## Conversation Summary\n{self.conversation_summary}")
        if self.long_term_memories:
            parts.append("## Relevant Memories\n" + "\n".join(
                f"- {m}" for m in self.long_term_memories))
        if self.task_state:
            parts.append(f"## Current Task\n{self.task_state}")
        if self.workspace_context:
            parts.append(f"## Workspace\n{self.workspace_context}")
        if self.retrieval_context:
            parts.append(f"## Retrieved Context\n{self.retrieval_context}")
        if self.device_state:
            parts.append(f"## Device State\n{self.device_state}")
        return "\n\n".join(parts)

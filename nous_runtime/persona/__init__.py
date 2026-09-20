"""Provider-neutral Nous Runtime identity."""

from nous_runtime.persona.capability_summary import build_capability_summary
from nous_runtime.persona.identity import RuntimeIdentity, get_identity
from nous_runtime.persona.style import BEHAVIOR_RULES
from nous_runtime.persona.system_prompt import (
    build_system_prompt,
    inject_system_message,
    nous_system_prompt,
)

__all__ = [
    "BEHAVIOR_RULES",
    "RuntimeIdentity",
    "build_capability_summary",
    "build_system_prompt",
    "get_identity",
    "inject_system_message",
    "nous_system_prompt",
]

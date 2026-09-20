# -*- coding: utf-8 -*-
"""Context Providers — each provider reads from ONE source of truth.

Context does NOT own data. Each provider reads from its canonical source:
  MemoryProvider   → project memory (JSONL stores)
  ProjectProvider  → project workspace
  AgentProvider    → agent registry
  DeviceProvider   → device registry / node runtime
  DecisionProvider → decision store
"""

from nous_runtime.context.providers.base import ContextProvider
from nous_runtime.context.providers.memory import MemoryProvider
from nous_runtime.context.providers.project import ProjectProvider
from nous_runtime.context.providers.agent import AgentProvider
from nous_runtime.context.providers.device import DeviceProvider
from nous_runtime.context.providers.decision import DecisionProvider

__all__ = [
    "ContextProvider",
    "MemoryProvider",
    "ProjectProvider",
    "AgentProvider",
    "DeviceProvider",
    "DecisionProvider",
]

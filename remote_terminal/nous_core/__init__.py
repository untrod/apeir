# -*- coding: utf-8 -*-
"""
Nous Core Kernel — P0 foundation layer.

This package provides the minimal backbone for event sourcing, persistent jobs,
device management, notifications, skill runtime, automation, and audit — all
without modifying the existing brain.py / tools.py / learn_*.py call chains.

Design rules:
  1. NO imports from brain.py, tools.py, learn_tools.py (avoid circular imports).
  2. All I/O goes through nous_core.db (SQLite, WAL mode).
  3. Failures in nous_core MUST NOT break existing chat / tool flows.
  4. Public API is synchronous (no async) — matches the existing codebase style.
"""

__version__ = "0.1.0"

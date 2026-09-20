# -*- coding: utf-8 -*-
"""
nous_core configuration.

Reuses the existing config.py configuration stack (env > config.local.json > defaults).
Adds nous_core-specific defaults without touching the existing config module's namespace.

Usage:
  from nous_core.config import get_config
  db_path = get_config("data_dir") + "/nous_core.db"
"""

from __future__ import annotations

import os as _os


# Path resolution
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # remote_terminal/


def _core_default(key: str) -> str:
    """nous_core-specific defaults. Only called when the key is not in env or config.local.json."""
    defaults = {
        "data_dir": _os.path.join(_ROOT, "data"),
    }
    return defaults.get(key, "")


def get_config(key: str, default: str = "") -> str:
    """
    Read a configuration value with the same priority as existing config.py:
      1. Environment variable NOUS_{KEY}
      2. config.local.json (via existing config module if available)
      3. nous_core default
      4. caller-supplied default

    This function deliberately does NOT import config at module level to avoid
    circular imports. It imports lazily inside the function.
    """
    # 1. Environment variable (highest priority)
    env_val = _os.environ.get(f"NOUS_{key.upper()}")
    if env_val is not None:
        return env_val

    # 2. config.local.json (if the existing config module is loaded)
    try:
        import config as _cfg
        cfg_val = _cfg._get(key, "")
        if cfg_val:
            return cfg_val
    except (ImportError, AttributeError):
        pass

    # 3. nous_core default
    core_val = _core_default(key)
    if core_val:
        return core_val

    # 4. caller default
    return default

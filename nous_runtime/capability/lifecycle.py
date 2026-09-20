# -*- coding: utf-8 -*-
"""
Capability Lifecycle — formalizes the capability state machine.

    Install → Register → Validate → Enable → Execute → Audit → Disable
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("nous.capability.lifecycle")


class CapabilityLifecycle(enum.Enum):
    """Standard capability lifecycle states."""
    INSTALL = "install"
    REGISTER = "register"
    VALIDATE = "validate"
    ENABLE = "enable"
    EXECUTE = "execute"
    AUDIT = "audit"
    DISABLE = "disable"
    ERROR = "error"


@dataclass
class LifecycleHooks:
    """Hooks that fire at each lifecycle stage.

    Each hook receives (capability_name, context_dict) and can return
    a modified context dict. Return None to abort the transition.
    """

    on_install: Callable | None = None
    on_register: Callable | None = None
    on_validate: Callable | None = None
    on_enable: Callable | None = None
    on_execute: Callable | None = None
    on_audit: Callable | None = None
    on_disable: Callable | None = None


# Global hook registry
_lifecycle_hooks: dict[str, LifecycleHooks] = {}


def register_lifecycle_hooks(capability_name: str, hooks: LifecycleHooks) -> None:
    """Register lifecycle hooks for a capability."""
    _lifecycle_hooks[capability_name] = hooks
    log.debug("Lifecycle hooks registered for '%s'", capability_name)


def get_lifecycle_hooks(capability_name: str) -> LifecycleHooks | None:
    """Get lifecycle hooks for a capability."""
    return _lifecycle_hooks.get(capability_name)


def fire_hook(capability_name: str, stage: CapabilityLifecycle, context: dict[str, Any]) -> dict[str, Any] | None:
    """Fire a lifecycle hook. Returns modified context, or None if aborted."""
    hooks = _lifecycle_hooks.get(capability_name)
    if not hooks:
        return context

    hook_fn = getattr(hooks, f"on_{stage.value}", None)
    if not hook_fn:
        return context

    try:
        result = hook_fn(capability_name, context)
        return result if result is not None else context
    except Exception as e:
        log.error("Lifecycle hook '%s' for '%s' failed: %s", stage.value, capability_name, e)
        return None

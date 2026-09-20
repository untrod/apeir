"""Runtime lifecycle service facade.

This module owns the transition from runtime-native lifecycle calls to the
remaining legacy compatibility implementations. Kernel code should call this
service instead of importing compatibility modules directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_migrations() -> int:
    from nous_runtime.services.database import run_migrations as _run_migrations

    return _run_migrations()


def enable_demo_mode() -> None:
    from nous_runtime.compat.demo_mode import enable_demo_mode as _enable_demo_mode

    _enable_demo_mode()


def seed_capabilities() -> int:
    from nous_runtime.compat.capability import (
        seed_composed_capabilities,
        seed_default_capabilities,
    )

    seed_default_capabilities()
    seed_composed_capabilities()
    return count_capabilities()


def start_event_dispatcher(interval: float = 5.0) -> None:
    from nous_runtime.compat.events.dispatcher import (
        register_builtin_handlers,
        register_handler,
        start_dispatcher,
    )

    register_builtin_handlers()
    _seed_automation(register_handler)
    start_dispatcher(interval=interval)


def stop_event_dispatcher() -> None:
    from nous_runtime.compat.events.dispatcher import stop_dispatcher

    stop_dispatcher()


def sync_legacy_devices() -> int:
    from nous_runtime.compat.devices import sync_from_legacy

    try:
        from nous_runtime.compat.devices import _get_live_devices

        live_devices = _get_live_devices()
    except (ImportError, AttributeError):
        live_devices = None

    if live_devices:
        sync_from_legacy(live_devices)
    return count_devices()


def recover_stale_jobs() -> int:
    from nous_runtime.compat.jobs import recover_stale_jobs as _recover_stale_jobs

    return _recover_stale_jobs()


def count_providers() -> int:
    from nous_runtime.services.providers import list_providers

    return len(list_providers())


def count_capabilities() -> int:
    from nous_runtime.services.capabilities import list_capabilities

    return len(list_capabilities())


def count_devices() -> int:
    try:
        from nous_runtime.compat.devices import list_devices

        return len(list_devices())
    except Exception:
        return 0


def count_events() -> int:
    try:
        from nous_runtime.compat.events import count_events as _count_events

        return _count_events()
    except Exception:
        return 0


def count_pending_jobs() -> int:
    from nous_runtime.services.jobs import list_jobs

    return len(list_jobs(status="pending"))


def count_automation_rules() -> int:
    try:
        from nous_runtime.compat.automation import list_rules

        return len(list_rules())
    except Exception:
        return 0


def _seed_automation(register_handler: Callable[[str, Callable[..., Any], str], Any]) -> None:
    from nous_runtime.compat.automation import evaluate_event, seed_default_rules

    seed_default_rules()
    register_handler("*", evaluate_event, "automation-engine")

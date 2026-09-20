"""Compatibility adapter for legacy device helpers."""

from remote_terminal.nous_core.devices import *  # noqa: F403


def _get_live_devices() -> dict:
    """Return the live devices dict from the legacy brain_devices module.

    This shim exists so that nous_runtime/services/lifecycle.py does not
    import remote_terminal.brain_devices directly.
    """
    try:
        from remote_terminal.brain_devices import devices
        return dict(devices) if devices else {}
    except (ImportError, AttributeError):
        return {}

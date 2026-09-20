"""Compatibility adapter for legacy provider registry and base class."""

from remote_terminal.nous_core import provider as _legacy_provider
from remote_terminal.nous_core.provider import *  # noqa: F403

_providers = _legacy_provider._providers


def clear_providers() -> int:
    """Unregister every legacy-backed Provider through its lifecycle hook."""
    removed = 0
    for provider_id in list(_providers):
        if _legacy_provider.unregister_adapter(provider_id):
            removed += 1
    return removed

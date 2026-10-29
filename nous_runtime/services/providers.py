"""Provider service facade used by public CLI and SDK surfaces."""

from __future__ import annotations

from typing import Any

from nous_runtime.provider.base import (
    Provider,
    clear_providers,
    get_provider,
    invoke_via_provider,
    invoke_via_provider_observation,
    list_providers,
    register_adapter,
    unregister_adapter,
)


def list_provider_summaries() -> list[dict[str, Any]]:
    """Project existing registrations and saved non-secret configuration."""
    import json
    from pathlib import Path
    from urllib.parse import urlsplit

    from nous_runtime.project.workspace import find_workspace
    from nous_runtime.provider.registry import registry

    summaries = {item["id"]: dict(item) for item in registry.list_all()}
    # This is the existing host-selected configuration, never a client path.
    # Writes already publish by atomic replacement. Do not resolve credentials.
    try:
        workspace = find_workspace(allow_uninitialized=True)
        path = Path(workspace) / "providers.json" if workspace is not None else None
        if path is None:
            return list(summaries.values())
        if path.is_symlink():
            raise ValueError
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            return list(summaries.values())
        with handle:
            raw = handle.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError
        saved = json.loads(raw)
        if not isinstance(saved, dict) or any(
            not isinstance(key, str) or not isinstance(value, dict)
            for key, value in saved.items()
        ):
            raise ValueError
        for provider_id, config in saved.items():
            if any(
                key in config and not isinstance(config[key], str)
                for key in ("name", "model")
            ):
                raise ValueError
            endpoint = config.get("base_endpoint", config.get("endpoint", ""))
            parsed = urlsplit(endpoint) if isinstance(endpoint, str) else None
            safe_endpoint = bool(
                parsed
                and parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and parsed.port != 0
                and not any(
                    character.isspace() or ord(character) < 32 for character in endpoint
                )
            )
            item = summaries.setdefault(
                provider_id,
                {
                    "id": provider_id,
                    "name": str(config.get("name") or provider_id),
                    "capabilities": [],
                    "health": {"status": "unknown"},
                },
            )
            item["configuration"] = {
                "name": str(config.get("name") or provider_id),
                "api_base_url": endpoint if safe_endpoint else "",
                "model": str(config.get("model") or ""),
                # Reference names and raw legacy secrets stay out of this view.
                "has_reference": bool(
                    config.get("credential_ref") or config.get("api_key_env")
                ),
            }
        return list(summaries.values())
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(
            "Saved Provider metadata is unavailable; inspect original configuration"
        ) from None


def provider_health_summary() -> dict[str, Any]:
    """Return aggregated provider health."""
    from nous_runtime.provider.registry import registry

    return registry.health_all()


__all__ = [
    "Provider",
    "clear_providers",
    "register_adapter",
    "unregister_adapter",
    "get_provider",
    "list_providers",
    "list_provider_summaries",
    "provider_health_summary",
    "invoke_via_provider",
    "invoke_via_provider_observation",
]

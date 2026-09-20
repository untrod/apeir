# -*- coding: utf-8 -*-
"""First-launch experience detector and launcher.

Detects whether Nous has been launched before and, on first run,
triggers the product setup wizard. Saves a marker file so the
wizard is not shown again.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("nous.deployment.first_launch")

MARKER_FILE = ".nous_initialized"


def is_first_launch(workspace: str | Path = "") -> bool:
    """Check if this is the first launch of Nous."""
    ws = Path(workspace) if workspace else Path.home() / ".nous"
    marker = ws / MARKER_FILE
    return not marker.is_file()


def mark_launched(workspace: str | Path = "") -> None:
    """Record that Nous has been launched successfully."""
    ws = Path(workspace) if workspace else Path.home() / ".nous"
    ws.mkdir(parents=True, exist_ok=True)
    marker = ws / MARKER_FILE
    marker.write_text(
        json.dumps({
            "initialized_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "version": _get_version(),
            "platform": sys.platform,
        }, indent=2),
        encoding="utf-8",
    )


def run_first_launch_if_needed(workspace: str | Path = "") -> bool:
    """Run the setup wizard if this is the first launch. Returns True if wizard was shown."""
    if not is_first_launch(workspace):
        return False

    ws = Path(workspace) if workspace else Path.home() / ".nous"
    ws.mkdir(parents=True, exist_ok=True)

    print("\nNous Runtime")
    print("First-run setup")
    print("-" * 40)
    print("Press Ctrl+C at any time to cancel.")

    try:
        from nous_runtime.deployment.setup_wizard import (
            ConsoleSetupWizard,
            save_setup_config,
        )

        wizard = ConsoleSetupWizard(str(ws))
        config = wizard.run()

        save_setup_config(config, ws / "setup_config.json")

        if config.providers:
            _save_provider_config(config.providers, ws)

    except Exception as exc:
        _log.warning("Setup wizard failed: %s. Continuing with defaults.", exc)
        print(f"\nSetup wizard skipped: {exc}")
        print("Run 'nous setup' later to configure providers.\n")

    mark_launched(ws)
    print("\nSetup complete. Launching Nous.\n")
    return True


def _get_version() -> str:
    try:
        from nous_runtime import __version__
        return __version__
    except Exception:
        return "0.1.0-rc1"


def _save_provider_config(providers: list[dict], workspace: Path) -> None:
    """Persist standard Provider profiles without credential material."""
    from nous_runtime.cli.provider_experience import (
        executable_capabilities,
        normalize_capability_mapping,
    )
    from nous_runtime.cli.provider_setup import SERVICE_PRESETS

    provider_file = workspace / "providers.json"
    existing: dict[str, dict] = {}
    if provider_file.is_file():
        try:
            raw = json.loads(provider_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = {
                    str(provider_id): dict(config)
                    for provider_id, config in raw.items()
                    if isinstance(config, dict)
                }
        except (OSError, ValueError):
            existing = {}

    forbidden = {"api_key", "token", "secret", "password"}
    for config in existing.values():
        for key in tuple(config):
            if key.lower() in forbidden:
                config.pop(key, None)

    aliases = {"anthropic": "claude"}
    for selected in providers:
        selected_id = str(selected.get("provider_id") or "").strip()
        service = aliases.get(selected_id, selected_id)
        preset = SERVICE_PRESETS.get(service)
        if preset is None:
            continue
        provider_id = service
        reference = str(selected.get("credential_ref") or "")
        if not reference and preset.get("env_key"):
            reference = f"env:{preset['env_key']}"
        capabilities = normalize_capability_mapping(preset.get("capabilities") or ())
        kind = str(preset["kind"])
        existing[provider_id] = {
            "name": str(preset["name"]),
            "service": service,
            "provider_id": provider_id,
            "kind": kind,
            "protocol": str(preset["protocol"]),
            "base_endpoint": str(preset["base_endpoint"]),
            "endpoint": str(preset["endpoint"]),
            "models_endpoint": str(preset["models_endpoint"]),
            "model": str(preset.get("model") or ""),
            "credential_ref": reference,
            "api_key_env": reference[4:] if reference.startswith("env:") else "",
            "authentication_required": bool(preset.get("env_key") or reference),
            "capability_mapping": list(capabilities),
            "executable_capabilities": list(
                executable_capabilities(kind, capabilities)
            ),
            "credential_scope": "environment" if reference.startswith("env:") else "none",
            "context_window": "Not declared",
        }

    provider_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(provider_file) + ".tmp")
    temporary.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(provider_file)

    legacy_file = workspace / "config" / "providers.json"
    if legacy_file.is_file():
        legacy_file.unlink()


def check_and_launch(workspace: str = "") -> None:
    """Check for first launch and trigger wizard if needed.

    Call this early in the `nous` CLI entry point.
    """
    try:
        run_first_launch_if_needed(workspace)
    except Exception as exc:
        _log.warning("First-launch check failed: %s", exc)


__all__ = [
    "is_first_launch",
    "mark_launched",
    "run_first_launch_if_needed",
    "check_and_launch",
]

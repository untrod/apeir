"""Service-first Provider configuration with reference-based credentials."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

from nous_runtime.cli.provider_experience import (
    executable_capabilities,
    fetch_provider_models,
    normalize_capability_mapping,
    probe_provider_config,
    render_probe_result,
)
from nous_runtime.provider.credentials import (
    store_credential,
    validate_environment_variable_name,
)

SERVICE_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "kind": "openai-compatible",
        "base_endpoint": "https://api.openai.com/v1",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "models_endpoint": "https://api.openai.com/v1/models",
        "model": "gpt-4o-mini",
        "fallback_models": ("gpt-4o-mini",),
        "env_key": "OPENAI_API_KEY",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Embedding", "Vision"),
    },
    "deepseek": {
        "name": "DeepSeek",
        "kind": "openai-compatible",
        "base_endpoint": "https://api.deepseek.com",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "models_endpoint": "https://api.deepseek.com/v1/models",
        "model": "deepseek-chat",
        "fallback_models": ("deepseek-chat", "deepseek-reasoner"),
        "env_key": "DEEPSEEK_API_KEY",
        "protocol": "openai",
        "structured_output_mode": "json_object",
        "capabilities": ("Reasoning", "Coding"),
    },
    "claude": {
        "name": "Claude",
        "kind": "anthropic-compatible",
        "base_endpoint": "https://api.anthropic.com",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "models_endpoint": "https://api.anthropic.com/v1/models",
        "model": "claude-sonnet-4-5",
        "fallback_models": ("claude-sonnet-4-5",),
        "env_key": "ANTHROPIC_API_KEY",
        "protocol": "anthropic",
        "capabilities": ("Reasoning", "Coding", "Vision"),
    },
    "ollama": {
        "name": "Ollama",
        "kind": "ollama",
        "base_endpoint": "http://localhost:11434",
        "endpoint": "http://localhost:11434/v1/chat/completions",
        "models_endpoint": "http://localhost:11434/api/tags",
        "model": "llama3.2",
        "fallback_models": ("llama3.2",),
        "env_key": "",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Embedding", "Vision"),
    },
    "openrouter": {
        "name": "OpenRouter",
        "kind": "openai-compatible",
        "base_endpoint": "https://openrouter.ai/api/v1",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "models_endpoint": "https://openrouter.ai/api/v1/models",
        "model": "openai/gpt-4o-mini",
        "fallback_models": ("openai/gpt-4o-mini",),
        "env_key": "OPENROUTER_API_KEY",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Vision"),
    },
    "siliconflow": {
        "name": "SiliconFlow",
        "kind": "openai-compatible",
        "base_endpoint": "https://api.siliconflow.cn/v1",
        "endpoint": "https://api.siliconflow.cn/v1/chat/completions",
        "models_endpoint": "https://api.siliconflow.cn/v1/models",
        "model": "Pro/deepseek-ai/DeepSeek-V3.2",
        "fallback_models": ("Pro/deepseek-ai/DeepSeek-V3.2",),
        "env_key": "SILICONFLOW_API_KEY",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Embedding", "Vision", "Rerank"),
    },
    "moonshot": {
        "name": "Moonshot AI",
        "kind": "openai-compatible",
        "base_endpoint": "https://api.moonshot.cn/v1",
        "endpoint": "https://api.moonshot.cn/v1/chat/completions",
        "models_endpoint": "https://api.moonshot.cn/v1/models",
        "model": "moonshot-v1-auto",
        "fallback_models": ("moonshot-v1-auto",),
        "env_key": "MOONSHOT_API_KEY",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Vision"),
    },
    "azure-openai": {
        "name": "Azure OpenAI",
        "kind": "openai-compatible",
        "base_endpoint": "https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1",
        "endpoint": (
            "https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1/chat/completions"
        ),
        "models_endpoint": "",
        "model": "gpt-4o-mini",
        "fallback_models": ("gpt-4o-mini",),
        "env_key": "AZURE_OPENAI_AUTH_TOKEN",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Embedding", "Vision"),
    },
    "generic-openai-compatible": {
        "name": "Generic OpenAI Compatible",
        "kind": "openai-compatible",
        "base_endpoint": "https://api.example.com/v1",
        "endpoint": "https://api.example.com/v1/chat/completions",
        "models_endpoint": "https://api.example.com/v1/models",
        "model": "",
        "fallback_models": (),
        "env_key": "NOUS_LLM_API_KEY",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding", "Embedding", "Vision"),
    },
    "local-http": {
        "name": "Local HTTP",
        "kind": "local-http",
        "base_endpoint": "http://localhost:8000/v1",
        "endpoint": "http://localhost:8000/v1/chat/completions",
        "models_endpoint": "http://localhost:8000/v1/models",
        "model": "local-model",
        "fallback_models": ("local-model",),
        "env_key": "",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding"),
    },
    "custom": {
        "name": "Custom Provider",
        "kind": "custom",
        "base_endpoint": "http://localhost:8000/v1",
        "endpoint": "http://localhost:8000/v1/chat/completions",
        "models_endpoint": "http://localhost:8000/v1/models",
        "model": "",
        "fallback_models": (),
        "env_key": "",
        "protocol": "openai",
        "capabilities": ("Reasoning", "Coding"),
    },
}

# Compatibility view for callers that still refer to protocol-oriented presets.
PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "openai-compatible": SERVICE_PRESETS["openai"],
    "anthropic-compatible": SERVICE_PRESETS["claude"],
    "ollama": SERVICE_PRESETS["ollama"],
    "local-http": SERVICE_PRESETS["local-http"],
    "custom": SERVICE_PRESETS["custom"],
}


def run_provider_setup(*, quick: bool = False) -> str:
    """Run the Provider Wizard using full-screen interaction when available."""
    if not quick:
        from nous_runtime.cli.screen_wizard import (
            WizardCancelled,
            run_screen_wizard,
            screen_wizard_supported,
        )

        if screen_wizard_supported():
            try:
                return run_screen_wizard(
                    lambda: _run_provider_setup(quick=False),
                    title="Nous / Provider Setup",
                )
            except WizardCancelled:
                return "Provider was not changed: cancelled."
    return _run_provider_setup(quick=quick)


def _run_provider_setup(*, quick: bool = False) -> str:
    """Run the service-first Provider Wizard."""
    print("\nProvider Wizard\n")
    print("Choose a service\n")
    services = (
        ("openai", "deepseek", "claude", "ollama") if quick else tuple(SERVICE_PRESETS)
    )
    for index, service_key in enumerate(services, 1):
        if not quick and index == 9:
            print("  " + "-" * 38)
        print(f"  {index:>2}. {SERVICE_PRESETS[service_key]['name']}")
    choice = _choose(
        "Service",
        tuple(
            (
                str(index),
                str(SERVICE_PRESETS[service_key]["name"]),
                "",
            )
            for index, service_key in enumerate(services, 1)
        ),
        "1",
    )
    try:
        service = services[int(choice) - 1]
    except (ValueError, IndexError):
        return "Provider was not changed: invalid service."
    return _setup_service(service, quick=quick)


def _setup_service(service: str, *, quick: bool = False) -> str:
    preset = SERVICE_PRESETS[service]
    default_id = service
    if quick:
        provider_id = default_id
    else:
        print("\nConfiguration name")
        print("  This name is used only on this device.")
        print(f"  Examples: {default_id}, {default_id}-work, company-ai")
        provider_id = _prompt("Name", default_id).strip()
    if not _valid_provider_id(provider_id):
        return "Provider was not changed: name may contain letters, numbers, '.', '_', and '-'."

    base_endpoint = (
        str(preset["base_endpoint"])
        if quick
        else _prompt("Endpoint", str(preset["base_endpoint"]))
    )
    endpoint = _request_endpoint(base_endpoint, preset)
    models_endpoint = _models_endpoint(base_endpoint, preset)
    credential_ref = (
        _configure_quick_credential(str(preset["env_key"]), provider_id)
        if quick
        else _configure_credential(str(preset["env_key"]), provider_id)
    )
    if credential_ref is None:
        return "Provider was not changed: credential configuration failed."

    config: dict[str, Any] = {
        "name": str(preset["name"]),
        "service": service,
        "provider_id": provider_id,
        "kind": str(preset["kind"]),
        "protocol": str(preset["protocol"]),
        "base_endpoint": base_endpoint,
        "endpoint": endpoint,
        "models_endpoint": models_endpoint,
        "credential_ref": credential_ref,
        "authentication_required": bool(preset["env_key"] or credential_ref),
    }
    if preset.get("credential_header"):
        config["credential_header"] = preset["credential_header"]
    if credential_ref.startswith("env:"):
        config["api_key_env"] = credential_ref[4:]

    print("\nFetching models...")
    discovered = fetch_provider_models(config)
    fallback = tuple(str(item) for item in preset.get("fallback_models") or ())
    candidates = discovered or fallback
    if discovered:
        print(f"  Connected. {len(discovered)} model(s) available.")
    else:
        print("  Model catalog unavailable; using a configured fallback.")
    model = str(preset.get("model") or "") if quick else _select_model(candidates)
    if not model:
        model = _prompt("Model", str(preset.get("model") or ""))
    if not model:
        return "Provider was not changed: a model is required."

    default_caps = tuple(str(item) for item in preset["capabilities"])
    if quick or _confirm("Use the selected model for all supported capabilities?"):
        capabilities = normalize_capability_mapping(default_caps)
    else:
        raw = _prompt("Capabilities", ", ".join(default_caps))
        capabilities = normalize_capability_mapping(raw.split(","))
    kind = str(preset["kind"])
    config.update(
        {
            "model": model,
            "context_window": "Not declared",
            "capability_mapping": list(capabilities),
            "executable_capabilities": list(
                executable_capabilities(kind, capabilities)
            ),
            "credential_scope": _credential_scope(credential_ref),
        }
    )

    probe: dict[str, Any] | None = None
    if not quick and _confirm("Run connection test now?"):
        print("\nTesting...")
        probe = probe_provider_config(provider_id, config, "test")
        print(render_probe_result(probe))
        if not probe.get("ok") and not _confirm(
            "Connection test failed. Save this unavailable configuration anyway?",
            default=False,
        ):
            return (
                "Provider was not saved because the connection test failed. "
                "Correct the credential or endpoint, then run 'nous provider add' again."
            )
    _change_provider_config(provider_id, lambda _: config, publish=True)
    if probe is not None:
        status = "Healthy" if probe.get("ok") else "Unavailable"
    else:
        status = "Configured (not verified)"
    return (
        "Provider saved.\n\n"
        f"Name     {provider_id}\n"
        f"Service  {preset['name']}\n"
        f"Model    {model}\n"
        f"Status   {status}\n\n"
        "Run /provider list or start a conversation."
    )


def _configure_credential(default_env: str, provider_id: str) -> str | None:
    print("\nAuthentication")
    print("  1. Use Environment Variable (Recommended)")
    print("  2. Store locally")
    print("  3. Enter once")
    print("  4. Skip")
    choice = _choose(
        "Authentication",
        (
            ("1", "Use environment variable", "Store only the variable name."),
            ("2", "Store in OS credential store", "Recommended for persistent use."),
            ("3", "Enter once", "Available only to this Runtime process."),
            ("4", "Skip", "Save without authentication."),
        ),
        "1" if default_env else "4",
    )
    if choice == "1":
        name = _prompt(
            "Environment variable name (not the API key)",
            default_env or "NOUS_LLM_API_KEY",
        )
        try:
            name = validate_environment_variable_name(name)
        except ValueError as exc:
            print(str(exc))
            return None
        return f"env:{name}"
    if choice == "2":
        reference = f"secret:nous-runtime:{provider_id}"
        value = _prompt_secret("API key")
        try:
            store_credential(reference, value)
        except (RuntimeError, ValueError) as exc:
            print(f"Credential store unavailable: {exc}")
            return None
        return reference
    if choice == "3":
        return _configure_session_credential(provider_id)
    if choice == "4":
        return ""
    print("Invalid authentication method.")
    return None


def _configure_quick_credential(default_env: str, provider_id: str) -> str | None:
    if not default_env:
        return ""
    print("\nAuthentication")
    print("  The key is kept only for this Runtime process.")
    return _configure_session_credential(provider_id)


def _configure_session_credential(provider_id: str) -> str:
    env_name = (
        "NOUS_SESSION_PROVIDER_"
        + "".join(char if char.isalnum() else "_" for char in provider_id.upper())
        + "_KEY"
    )
    value = _prompt_secret("API key")
    if value:
        os.environ[env_name] = value
    return f"env:{env_name}"


def _select_model(models: tuple[str, ...]) -> str:
    if not models:
        return ""
    visible = models[:20]
    print("\nAvailable models")
    for index, model in enumerate(visible, 1):
        print(f"  {index:>2}. {model}")
    if len(models) > len(visible):
        print(f"  ... {len(models) - len(visible)} more available")
    choice = _choose(
        "Model",
        tuple((str(index), model, "") for index, model in enumerate(visible, 1)),
        "1",
    )
    if choice.isdigit():
        index = int(choice) - 1
        return visible[index] if 0 <= index < len(visible) else ""
    return choice.strip()


def _request_endpoint(base_endpoint: str, preset: dict[str, Any]) -> str:
    value = base_endpoint.rstrip("/")
    default_base = str(preset["base_endpoint"]).rstrip("/")
    if value == default_base and preset.get("endpoint"):
        return str(preset["endpoint"])
    if value.endswith(("/chat/completions", "/messages")):
        return value
    if str(preset["protocol"]) == "anthropic":
        return value + "/v1/messages"
    return value + "/chat/completions"


def _models_endpoint(base_endpoint: str, preset: dict[str, Any]) -> str:
    default_base = str(preset["base_endpoint"]).rstrip("/")
    if base_endpoint.rstrip("/") == default_base:
        return str(preset.get("models_endpoint") or "")
    value = base_endpoint.rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    elif value.endswith("/messages"):
        value = value[: -len("/messages")]
    if str(preset["kind"]) == "ollama":
        root = value[: -len("/v1")] if value.endswith("/v1") else value
        return root + "/api/tags"
    return value + "/models"


def _setup_kind(kind: str) -> str:
    service = {
        "openai-compatible": "openai",
        "anthropic-compatible": "claude",
        "ollama": "ollama",
        "local-http": "local-http",
        "custom": "custom",
    }[kind]
    return _setup_service(service)


def _setup_preset(key: str) -> str:
    """Compatibility wrapper for the previous setup entry point."""
    return _setup_kind(key)


def _setup_custom() -> str:
    return _setup_service("custom")


def register_provider_from_config(
    provider_id: str,
    name: str,
    api_base_url: str,
    credential_ref: str | None = None,
    capabilities: Sequence[str] | None = None,
    model: str | None = None,
    capability_models: dict[str, str] | None = None,
) -> bool:
    """Persist and register a Provider from a trusted control-plane request.

    This is the shared non-interactive application service used by desktop and
    other control surfaces. It accepts credential references only; secret
    values are never accepted or persisted.
    """
    config = build_provider_config(
        provider_id=provider_id,
        name=name,
        api_base_url=api_base_url,
        credential_ref=credential_ref,
        capabilities=capabilities,
        model=model,
        capability_models=capability_models,
    )
    provider_id = str(config["provider_id"])
    _change_provider_config(provider_id, lambda _: config, publish=True)
    return True


def update_provider_from_config(provider_id: str, changes: dict[str, Any]) -> None:
    """Update the original saved adapter without replacing it with a generic one."""
    allowed = {
        "name",
        "api_base_url",
        "credential_ref",
        "capabilities",
        "model",
        "capability_models",
    }
    if not isinstance(changes, dict) or not changes or changes.keys() - allowed:
        raise ValueError("Unsupported Provider configuration fields")
    for field in ("name", "api_base_url", "credential_ref", "model"):
        if field in changes and not isinstance(changes[field], str):
            raise ValueError("Provider text fields must be strings")
    if "capabilities" in changes and (
        not isinstance(changes["capabilities"], list)
        or not all(isinstance(item, str) for item in changes["capabilities"])
    ):
        raise ValueError("Provider capabilities must be a list of strings")
    if "capability_models" in changes and (
        not isinstance(changes["capability_models"], dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changes["capability_models"].items()
        )
    ):
        raise ValueError("Provider model mappings must contain strings")

    def updated(previous: dict[str, Any] | None) -> dict[str, Any]:
        if previous is None:
            raise KeyError(provider_id)
        # Preserve host/CLI settings that this control surface does not edit.
        service = str(previous.get("service") or provider_id)
        validated = build_provider_config(
            service,
            changes.get("name", previous.get("name") or provider_id),
            changes.get("api_base_url", previous.get("base_endpoint") or ""),
            credential_ref=changes.get(
                "credential_ref", previous.get("credential_ref")
            ),
            capabilities=changes.get(
                "capabilities", previous.get("capability_mapping")
            ),
            model=changes.get("model", previous.get("model")),
            capability_models=changes.get(
                "capability_models", previous.get("capability_models")
            ),
        )
        config = dict(previous)
        fields = {
            "name": ("name",),
            "api_base_url": ("base_endpoint", "endpoint", "models_endpoint"),
            "credential_ref": (
                "credential_ref",
                "authentication_required",
                "credential_scope",
            ),
            "capabilities": ("capability_mapping", "executable_capabilities"),
            "model": ("model",),
            "capability_models": ("capability_models",),
        }
        for field in changes:
            for key in fields[field]:
                config[key] = validated[key]
        if "credential_ref" in changes:
            config.pop("api_key_env", None)
            if "api_key_env" in validated:
                config["api_key_env"] = validated["api_key_env"]
        return config

    _change_provider_config(provider_id, updated, publish=True)


def remove_provider_from_config(provider_id: str) -> None:
    """Remove configuration and current dispatch discovery, leaving secrets alone."""
    from nous_runtime.services.providers import get_provider

    def removed(previous: dict[str, Any] | None) -> None:
        if previous is None and get_provider(provider_id) is None:
            raise KeyError(provider_id)

    _change_provider_config(provider_id, removed, publish=True)


def build_provider_config(
    provider_id: str,
    name: str,
    api_base_url: str,
    credential_ref: str | None = None,
    capabilities: Sequence[str] | None = None,
    model: str | None = None,
    capability_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a validated, secret-free Provider configuration."""
    provider_id = provider_id.strip()
    if not _valid_provider_id(provider_id):
        raise ValueError(
            "provider_id may contain letters, numbers, '.', '_', and '-' only"
        )

    reference = str(credential_ref or "").strip()
    if reference.startswith("env:"):
        env_name = validate_environment_variable_name(reference[4:])
        reference = f"env:{env_name}"
    elif reference and not reference.startswith("secret:"):
        raise ValueError("credential_ref must use env: or secret:")

    service = provider_id if provider_id in SERVICE_PRESETS else "custom"
    preset = SERVICE_PRESETS[service]
    base_endpoint = str(api_base_url or preset["base_endpoint"]).strip().rstrip("/")
    try:
        parsed_endpoint = urlsplit(base_endpoint)
        valid_endpoint = (
            parsed_endpoint.scheme in {"http", "https"}
            and bool(parsed_endpoint.hostname)
            and parsed_endpoint.port != 0
            and parsed_endpoint.username is None
            and parsed_endpoint.password is None
            and not parsed_endpoint.query
            and not parsed_endpoint.fragment
            and not any(
                character.isspace() or ord(character) < 32
                for character in base_endpoint
            )
        )
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        raise ValueError(
            "Provider base URL must use HTTP(S) without embedded credentials, query parameters or fragments"
        )
    configured = normalize_capability_mapping(capabilities or preset["capabilities"])
    if not configured:
        configured = normalize_capability_mapping(preset["capabilities"])
    kind = str(preset["kind"])
    config: dict[str, Any] = {
        "name": name.strip() or str(preset["name"]),
        "service": service,
        "provider_id": provider_id,
        "kind": kind,
        "protocol": str(preset["protocol"]),
        "base_endpoint": base_endpoint,
        "endpoint": _request_endpoint(base_endpoint, preset),
        "models_endpoint": _models_endpoint(base_endpoint, preset),
        "credential_ref": reference,
        "authentication_required": bool(reference or preset.get("env_key")),
        "model": str(model or preset.get("model") or "").strip(),
        "capability_models": {
            str(capability): str(model_id).strip()
            for capability, model_id in (capability_models or {}).items()
            if str(capability).strip() and str(model_id).strip()
        },
        "context_window": "Not declared",
        "capability_mapping": list(configured),
        "executable_capabilities": list(executable_capabilities(kind, configured)),
        "credential_scope": _credential_scope(reference),
        "structured_output_mode": str(
            preset.get("structured_output_mode") or "json_schema"
        ),
    }
    if preset.get("credential_header"):
        config["credential_header"] = preset["credential_header"]
    if reference.startswith("env:"):
        config["api_key_env"] = reference[4:]

    return config


def validate_provider_from_config(
    provider_id: str,
    name: str,
    api_base_url: str,
    credential_ref: str | None = None,
    capabilities: Sequence[str] | None = None,
    model: str | None = None,
    capability_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate reference-only configuration without inference or network I/O."""
    config = build_provider_config(
        provider_id=provider_id,
        name=name,
        api_base_url=api_base_url,
        credential_ref=credential_ref,
        capabilities=capabilities,
        model=model,
        capability_models=capability_models,
    )
    return {
        "ok": True,
        "provider_id": config["provider_id"],
        "status": "Configuration accepted; authentication and inference not tested",
        "validation_scope": "configuration",
        "authentication": "UNKNOWN",
        "model_inference": "NOT_RUN",
        "latency_ms": None,
    }


def _save_provider_config(provider_id: str, config: dict[str, Any]) -> None:
    """Persist only non-secret Provider configuration."""
    _change_provider_config(provider_id, lambda _: config)


def _change_provider_config(
    provider_id: str,
    change: Callable[[dict[str, Any] | None], dict[str, Any] | None],
    *,
    publish: bool = False,
) -> None:
    """Serialize changes to the existing JSON owner, then publish its adapter."""
    from nous_runtime.locking import file_lock, runtime_locks
    from nous_runtime.project.workspace import find_workspace, init_workspace

    workspace = find_workspace()
    if workspace is None:
        workspace = init_workspace()
    path = Path(workspace) / "providers.json"
    with (
        runtime_locks.acquire(f"workspace:providers:{path}", owner="provider-config"),
        file_lock(str(path) + ".lock"),
    ):
        existing: dict[str, Any] = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(
                    "Provider configuration is unreadable or invalid; inspect original state"
                ) from exc
            if not isinstance(existing, dict) or not all(
                isinstance(value, dict) for value in existing.values()
            ):
                raise ValueError(
                    "Provider configuration must contain a mapping of Provider records"
                )
        config = change(existing.get(provider_id))
        candidate = (
            _configured_provider(provider_id, config=config)
            if publish and config is not None
            else None
        )
        if config is None:
            existing.pop(provider_id, None)
        else:
            existing[provider_id] = _sanitize_config(config)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".providers-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(existing, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if publish:
            from nous_runtime.model_runtime.factory import gateway_service
            from nous_runtime.provider.registry import ProviderRegistry
            from nous_runtime.runtime.no_intelligence import no_intelligence_enabled

            registry = ProviderRegistry()
            try:
                registry.remove(provider_id)
                if candidate is not None and not no_intelligence_enabled():
                    registry.install(candidate)
                gateway_service.configure_from_providers()
            except Exception as exc:
                # Persistence may already have changed. Never imply rollback or
                # keep advertising a partially refreshed Gateway as ready.
                gateway_service.clear()
                raise RuntimeError(
                    "Provider configuration saved; runtime refresh failed. Inspect original configuration before retrying."
                ) from exc


def load_providers_from_config(workspace: str | Path | None = None) -> int:
    """Register saved Providers while resolving credentials only at invocation."""
    from nous_runtime.runtime.no_intelligence import no_intelligence_enabled

    if no_intelligence_enabled():
        from nous_runtime.services.providers import clear_providers

        clear_providers()
        return 0
    from nous_runtime.cli.provider_experience import read_provider_configs

    count = 0
    for provider_id, config in read_provider_configs(workspace).items():
        try:
            _register_provider_runtime(provider_id, config=config)
        except (TypeError, ValueError):
            continue
        count += 1
    return count


def _register_provider_runtime(
    provider_id: str,
    endpoint: str = "",
    api_key: str = "",
    model: str = "",
    *,
    config: dict[str, Any] | None = None,
) -> None:
    """Register a configured adapter without persisting credential material."""
    from nous_runtime.services.providers import register_adapter

    register_adapter(
        _configured_provider(provider_id, endpoint, api_key, model, config=config)
    )


def _configured_provider(
    provider_id: str,
    endpoint: str = "",
    api_key: str = "",
    model: str = "",
    *,
    config: dict[str, Any] | None = None,
) -> Any:
    """Construct the existing adapter before any saved configuration is changed."""
    values = dict(config or {})
    values.setdefault("endpoint", endpoint)
    values.setdefault("model", model)
    if api_key:
        os.environ["NOUS_LLM_API_KEY"] = api_key
    kind = str(values.get("kind") or "openai-compatible")
    name = str(values.get("name") or provider_id)
    reference = str(values.get("credential_ref") or "")
    if not reference and values.get("api_key_env"):
        reference = f"env:{values['api_key_env']}"
    configured = (
        values.get("executable_capabilities")
        or values.get("capability_mapping")
        or ("model.reason", "model.code")
    )
    capabilities = executable_capabilities(kind, configured)
    if kind == "anthropic-compatible":
        from nous_runtime.provider.adapters.anthropic import AnthropicProvider

        provider = AnthropicProvider(
            provider_id=provider_id,
            provider_name=name,
            endpoint=str(values.get("endpoint") or PROVIDER_PRESETS[kind]["endpoint"]),
            model=str(values.get("model") or ""),
            credential_ref=reference,
            capabilities=capabilities,
            capability_models=dict(values.get("capability_models") or {}),
        )
    else:
        from nous_runtime.provider.adapters.openai import OpenAIProvider

        provider = OpenAIProvider(
            provider_id=provider_id,
            provider_name=name,
            endpoint=str(values.get("endpoint") or endpoint),
            model=str(values.get("model") or model),
            credential_ref=reference,
            authentication_required=values.get("authentication_required"),
            capabilities=capabilities,
            capability_endpoints=dict(values.get("capability_endpoints") or {}),
            capability_models=dict(values.get("capability_models") or {}),
            max_concurrency=int(values.get("max_concurrency") or 3),
            structured_output_mode=str(
                values.get("structured_output_mode") or "json_schema"
            ),
        )
    return provider


def _test_connection(endpoint: str, api_key: str, model: str) -> bool:
    """Compatibility connection test that never prints or persists the key."""
    name = "NOUS_PROVIDER_COMPATIBILITY_KEY"
    previous = os.environ.get(name)
    try:
        if api_key:
            os.environ[name] = api_key
        result = probe_provider_config(
            "compatibility-test",
            {
                "kind": "openai-compatible",
                "endpoint": endpoint,
                "model": model,
                "credential_ref": f"env:{name}" if api_key else "",
            },
            "test",
        )
        return bool(result.get("ok"))
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _sanitize_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_config(item)
            for key, item in value.items()
            if str(key).lower()
            not in {"api_key", "token", "secret", "password", "authorization"}
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_config(item) for item in value]
    return value


def _valid_provider_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in "._-" for char in value)


def _credential_scope(reference: str) -> str:
    if reference.startswith("env:NOUS_SESSION_PROVIDER_"):
        return "process"
    if reference.startswith(("secret:", "credman:")):
        return "local-secret-store"
    if reference.startswith("env:"):
        return "environment"
    return "none"


def _credential_label(reference: str) -> str:
    if not reference:
        return "Not required"
    if reference.startswith("env:"):
        return f"Environment variable {reference[4:]}"
    return "OS secret store"


def _choose(
    label: str,
    choices: Sequence[tuple[str, str, str]],
    default: str = "",
) -> str:
    from nous_runtime.cli.screen_wizard import WizardChoice, active_wizard

    wizard = active_wizard()
    if wizard is not None:
        return wizard.ask_select(
            label,
            tuple(WizardChoice(*choice) for choice in choices),
            default,
        )
    return _prompt(label, default)


def _prompt(label: str, default: str = "") -> str:
    from nous_runtime.cli.screen_wizard import active_wizard

    wizard = active_wizard()
    if wizard is not None:
        return wizard.ask_text(label, default)
    suffix = f" [{default}]: " if default else ": "
    value = input(f"{label}{suffix}")
    return value if value else default


def _prompt_secret(label: str, default: str = "") -> str:
    from nous_runtime.cli.screen_wizard import active_wizard

    wizard = active_wizard()
    if wizard is not None:
        return wizard.ask_text(label, default, secret=True)
    prompt = f"{label} [configured]: " if default else f"{label}: "
    return getpass.getpass(prompt) or default


def _confirm(prompt: str, *, default: bool = True) -> bool:
    from nous_runtime.cli.screen_wizard import active_wizard

    wizard = active_wizard()
    if wizard is not None:
        return wizard.ask_confirm(prompt, default=default)
    label = "y" if default else "n"
    answer = input(f"{prompt} (y/n) [{label}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")

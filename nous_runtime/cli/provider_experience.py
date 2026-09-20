"""Provider configuration, diagnostics, and terminal presentation."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from nous_runtime.provider.credentials import (
    credential_fix_suggestion,
    credential_status,
    describe_credential_reference,
    resolve_credential,
)

CAPABILITY_MAPPING = OrderedDict(
    (
        ("Reasoning", "model.reason"),
        ("Coding", "model.code"),
        ("Embedding", "model.embed"),
        ("Vision", "model.vision"),
        ("Speech", "model.transcribe"),
        ("Rerank", "model.rerank"),
    )
)
_EXECUTABLE_BY_KIND = {
    "openai-compatible": {
        "model.reason",
        "model.code",
        "model.embed",
        "model.vision",
        "model.rerank",
    },
    "ollama": {"model.reason", "model.code", "model.embed", "model.vision"},
    "local-http": {"model.reason", "model.code", "model.embed", "model.vision", "model.rerank"},
    "custom": {"model.reason", "model.code", "model.embed", "model.vision", "model.rerank"},
    "anthropic-compatible": {"model.reason", "model.code", "model.vision"},
}


def normalize_capability_mapping(values: Iterable[str]) -> tuple[str, ...]:
    """Normalize user-facing capability names to existing capability IDs."""
    by_name = {name.lower(): capability for name, capability in CAPABILITY_MAPPING.items()}
    by_id = set(CAPABILITY_MAPPING.values())
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        capability = by_name.get(item.lower(), item if item in by_id else "")
        if capability and capability not in result:
            result.append(capability)
    return tuple(result)


def executable_capabilities(kind: str, configured: Iterable[str]) -> tuple[str, ...]:
    supported = _EXECUTABLE_BY_KIND.get(kind, _EXECUTABLE_BY_KIND["custom"])
    return tuple(item for item in normalize_capability_mapping(configured) if item in supported)


def read_provider_configs(workspace: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Read non-secret Provider configuration from the active Workspace."""
    root = _workspace(workspace)
    if root is None:
        return {}
    path = root / "providers.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for provider_id, item in raw.items():
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        for key, value in item.items():
            if key.lower() in {"api_key", "token", "secret", "password"}:
                if value and str(value).strip():
                    entry["_has_direct_credential"] = True
                continue
            entry[key] = value
        result[str(provider_id)] = entry
    return result


def configured_provider_rows(workspace: str | Path | None = None) -> list[dict[str, Any]]:
    """Combine configured providers with public Registry health metadata."""
    from nous_runtime.services.providers import list_provider_summaries

    configs = read_provider_configs(workspace)
    registered = {
        str(item.get("id") or item.get("provider_id") or ""): item
        for item in list_provider_summaries()
    }
    rows: list[dict[str, Any]] = []
    for provider_id, config in configs.items():
        registry_item = registered.pop(provider_id, {})
        health = dict(registry_item.get("health") or {})
        configured = normalize_capability_mapping(config.get("capability_mapping") or ())
        executable = tuple(registry_item.get("capabilities") or ()) or executable_capabilities(
            str(config.get("kind") or "openai-compatible"),
            configured or ("model.reason", "model.code"),
        )
        auth_required = config.get("authentication_required")
        if auth_required is None:
            # Infer from kind: only ollama and local-http can be auth-free
            kind = str(config.get("kind") or "")
            if kind in ("ollama",):
                auth_required = False
        credential_ref = _credential_ref(config)
        rows.append(
            {
                "provider_id": provider_id,
                "name": config.get("name") or registry_item.get("name") or provider_id,
                "kind": config.get("kind") or "openai-compatible",
                "health": health.get("status") or "not loaded",
                "latency_ms": health.get("latency_ms"),
                "capabilities": configured or executable,
                "executable_capabilities": executable,
                "model": config.get("model") or health.get("model") or "Not configured",
                "context_window": config.get("context_window") or "Not declared",
                "credential": credential_status(
                    credential_ref,
                    authentication_required=auth_required,
                ),
                "authentication_required": auth_required,
            }
        )
    for provider_id, item in registered.items():
        health = dict(item.get("health") or {})
        rows.append(
            {
                "provider_id": provider_id,
                "name": item.get("name") or provider_id,
                "kind": "runtime",
                "health": health.get("status") or "unknown",
                "latency_ms": health.get("latency_ms"),
                "capabilities": tuple(item.get("capabilities") or ()),
                "executable_capabilities": tuple(item.get("capabilities") or ()),
                "model": health.get("model") or "Not declared",
                "context_window": "Not declared",
                "credential": credential_status("", authentication_required=None),
                "authentication_required": None,
            }
        )
    return rows


def render_provider_dashboard(workspace: str | Path | None = None) -> str:
    rows = configured_provider_rows(workspace)
    if not rows:
        return "Configured Providers\n\n  None\n\nUse /provider add to configure one."
    lines = ["Configured Providers"]
    for row in rows:
        configured = set(row["capabilities"])
        executable = set(row["executable_capabilities"])
        capabilities = []
        for label, capability in CAPABILITY_MAPPING.items():
            if capability in executable:
                capabilities.append(label)
            elif capability in configured:
                capabilities.append(f"{label} (configured only)")
        latency = row["latency_ms"]
        latency_text = f"{float(latency):.0f} ms" if latency is not None else "Not measured"
        credential = row["credential"]
        lines.extend(
            (
                "",
                f"{row['name']}  [{row['provider_id']}]",
                f"  Type           {row['kind']}",
                f"  Health         {row['health']}",
                f"  Latency        {latency_text}",
                f"  Default model  {row['model']}",
                f"  Context window {row['context_window']}",
                f"  Capabilities   {', '.join(capabilities) or 'None declared'}",
                f"  Credential     {_format_credential_state(credential)}",
            )
        )
    lines.extend(
        (
            "",
            "Actions",
            "  /provider add      Add a Provider",
            "  /provider quick    Quick setup",
            "  /provider doctor   Diagnose configuration and connectivity",
            "  /provider test ID  Send a minimal model request",
        )
    )
    return "\n".join(lines)


def render_provider_status(rows: list[dict[str, Any]]) -> str:
    """Render per-Provider status without any new network calls."""
    if not rows:
        return "Providers\n\n  None configured\n\nUse 'nous provider add' to configure one."
    lines = ["Providers"]
    for row in rows:
        latency = row.get("latency_ms")
        latency_text = f"{float(latency):.0f} ms" if latency is not None else "Not measured"
        credential = row["credential"]
        credential_state = _format_credential_state(credential)
        lines.extend(
            (
                "",
                f"{row['name']}  [{row['provider_id']}]",
                f"  Model       {row['model']}",
                f"  Health      {row['health']}",
                f"  Latency     {latency_text}",
                f"  Credential  {credential_state}",
            )
        )
    return "\n".join(lines)


def _format_credential_state(credential: Any) -> str:
    """Render a CredentialStatus as a human-readable one-line label."""
    if not credential.reference:
        return credential.detail or "Not configured"
    source_label = credential.source
    state_label = "Available" if credential.available else "Missing"
    if not credential.available and credential.detail and credential.detail not in ("Missing", "Reference configured; credential missing"):
        state_label = credential.detail
    return f"{source_label} - {state_label}"


def fetch_provider_models(
    config: dict[str, Any],
    *,
    timeout: float = 10,
) -> tuple[str, ...]:
    """Return model IDs from a Provider catalog without mutating Runtime state."""
    endpoint = str(config.get("models_endpoint") or "")
    if not endpoint:
        return ()
    reference = _credential_ref(config)
    try:
        credential = resolve_credential(reference) if reference else ""
    except (RuntimeError, ValueError):
        return ()
    if reference and not credential:
        return ()
    request = urllib.request.Request(
        endpoint,
        headers=_provider_headers(config, credential),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(1_048_576))
    except (OSError, ValueError, urllib.error.URLError):
        return ()
    return _model_ids(payload)


def diagnose_provider(
    provider_id: str,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect one Provider using bounded, read-only probes."""
    config = read_provider_configs(workspace).get(provider_id)
    if config is None:
        return {
            "ok": False,
            "provider_id": provider_id,
            "status": "not configured",
        }
    reference = _credential_ref(config)
    credential = credential_status(reference)
    models = fetch_provider_models(config)
    probe = probe_provider_config(provider_id, config, "test")
    selected_model = str(config.get("model") or "")
    authentication_required = bool(
        config.get("authentication_required", bool(reference))
    )
    authentication = (
        "not required"
        if not authentication_required
        else "passed"
        if probe.get("ok") and reference
        else "failed"
        if reference
        else "not configured"
    )
    try:
        credential_reference = describe_credential_reference(reference)
    except ValueError:
        credential_reference = reference or "Not configured"
    return {
        "ok": bool(probe.get("ok")),
        "provider_id": provider_id,
        "service": str(config.get("service") or config.get("name") or provider_id),
        "endpoint": "configured" if config.get("endpoint") else "missing",
        "credential": credential.source,
        "credential_reference": credential_reference,
        "credential_detail": credential.detail,
        "credential_available": credential.available,
        "credential_fix": credential_fix_suggestion(credential),
        "authentication": authentication,
        "model": selected_model or "not configured",
        "model_available": selected_model in models if models else None,
        "models_discovered": len(models),
        "streaming": "protocol-supported; not exercised",
        "latency_ms": probe.get("latency_ms", 0),
        "status": probe.get("status") or "unknown",
    }


def render_provider_doctor(result: dict[str, Any]) -> str:
    """Render Provider Doctor output without secret material."""
    available = result.get("model_available")
    model_status = (
        "available"
        if available is True
        else "not returned by catalog"
        if available is False
        else "catalog unavailable"
    )
    outcome = "Healthy" if result.get("ok") else "Needs attention"
    cred_state = "Available" if result.get("credential_available") else "Missing"
    lines = [
        "Provider Doctor",
        f"  Provider        {result.get('provider_id') or 'Unknown'}",
        f"  Result          {outcome}",
        f"  Endpoint        {result.get('endpoint') or 'unknown'}",
        f"  Credential      {result.get('credential') or 'Not configured'}",
        f"  Reference       {result.get('credential_reference') or 'Not configured'}",
        f"  Cred status     {cred_state}",
    ]
    if result.get("credential_fix"):
        lines.append(f"  Fix             {result['credential_fix']}")
    lines.extend(
        (
            f"  Authentication  {result.get('authentication') or 'unknown'}",
            f"  Model           {result.get('model') or 'not configured'} ({model_status})",
            f"  Models found    {result.get('models_discovered', 0)}",
            f"  Streaming       {result.get('streaming') or 'not verified'}",
            f"  Latency         {result.get('latency_ms', 0)} ms",
            f"  Status          {result.get('status') or 'unknown'}",
        )
    )
    return "\n".join(lines)


def probe_provider(
    provider_id: str,
    operation: str,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Run an explicit connection probe without changing Provider state."""
    configs = read_provider_configs(workspace)
    config = configs.get(provider_id)
    if config is None:
        return {"ok": False, "provider_id": provider_id, "status": "not configured"}
    return probe_provider_config(provider_id, config, operation)


def probe_provider_config(
    provider_id: str,
    config: dict[str, Any],
    operation: str,
) -> dict[str, Any]:
    endpoint = str(config.get("endpoint") or "")
    if not endpoint:
        return {"ok": False, "provider_id": provider_id, "status": "endpoint missing"}
    reference = _credential_ref(config)
    try:
        credential = resolve_credential(reference) if reference else ""
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "provider_id": provider_id, "status": str(exc)}
    if reference and not credential:
        return {"ok": False, "provider_id": provider_id, "status": "credential unavailable"}
    started = time.perf_counter()
    request = _probe_request(config, endpoint, credential, operation)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read(4096)
            code = int(getattr(response, "status", 200))
        ok = 200 <= code < 400
        status = "healthy" if ok else f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        exc.close()
        ok = operation == "ping" and code < 500
        if ok and code in {401, 403}:
            status = "reachable; authorization required"
        elif ok:
            status = f"reachable (HTTP {code})"
        else:
            status = f"HTTP {code}"
    except Exception as exc:
        code = 0
        ok = False
        status = f"unreachable: {type(exc).__name__}"
    return {
        "ok": ok,
        "provider_id": provider_id,
        "operation": operation,
        "status": status,
        "http_status": code,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "credential": describe_credential_reference(reference),
    }


def render_probe_result(result: dict[str, Any]) -> str:
    outcome = "Passed" if result.get("ok") else "Failed"
    return "\n".join(
        (
            f"Provider {result.get('operation') or 'probe'}",
            f"  Provider  {result.get('provider_id') or 'Unknown'}",
            f"  Result    {outcome}",
            f"  Status    {result.get('status') or 'Unknown'}",
            f"  Latency   {result.get('latency_ms', 0)} ms",
            f"  Credential {result.get('credential') or 'Not disclosed'}",
        )
    )


def _probe_request(
    config: dict[str, Any],
    endpoint: str,
    credential: str,
    operation: str,
) -> urllib.request.Request:
    kind = str(config.get("kind") or "openai-compatible")
    protocol = str(config.get("protocol") or ("anthropic" if kind == "anthropic-compatible" else "openai"))
    headers = _provider_headers(config, credential)
    if operation == "ping":
        return urllib.request.Request(endpoint, headers=headers, method="GET")
    model = str(config.get("model") or "")
    if protocol == "anthropic":
        body = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "Reply with OK"}],
        }
    else:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with OK"}],
            "max_tokens": 1,
        }
    return urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def _provider_headers(config: dict[str, Any], credential: str) -> dict[str, str]:
    kind = str(config.get("kind") or "openai-compatible")
    protocol = str(
        config.get("protocol")
        or ("anthropic" if kind == "anthropic-compatible" else "openai")
    )
    headers = {"Content-Type": "application/json"}
    if protocol == "anthropic":
        if credential:
            headers["x-api-key"] = credential
        headers["anthropic-version"] = "2023-06-01"
    elif credential:
        header = str(config.get("credential_header") or "Authorization")
        headers[header] = credential if header.lower() == "api-key" else f"Bearer {credential}"
    return headers


def _model_ids(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    items = payload.get("data") or payload.get("models") or ()
    if not isinstance(items, list):
        return ()
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "")
        else:
            model_id = ""
        if model_id and model_id not in result:
            result.append(model_id)
        if len(result) >= 200:
            break
    return tuple(result)


def _credential_ref(config: dict[str, Any]) -> str:
    reference = str(config.get("credential_ref") or "")
    if reference:
        return reference
    env_name = str(config.get("api_key_env") or "")
    if env_name:
        return f"env:{env_name}"
    if config.get("_has_direct_credential"):
        return "secret:nous-legacy:direct-key"
    return ""


def _workspace(workspace: str | Path | None) -> Path | None:
    if workspace is not None:
        path = Path(workspace)
        return path if path.name == ".nous" else path / ".nous"
    from nous_runtime.project.workspace import find_workspace

    found = find_workspace()
    return Path(found) if found else None
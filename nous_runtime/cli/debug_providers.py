# -*- coding: utf-8 -*-
"""Provider visibility debug -trace every layer of the provider pipeline."""

from __future__ import annotations

import json as _json
import os as _os
from pathlib import Path as _Path


def debug_providers(workspace: str | None = None) -> str:
    """Return a multi-section debug report on provider visibility."""
    sections: list[tuple[str, str]] = []

    # 1. Environment
    cwd = _os.getcwd()
    from nous_runtime.project.workspace import find_workspace
    ws = find_workspace()
    ws_str = str(ws) if ws else "(none)"
    prov_file = str(_Path(ws_str) / "providers.json") if ws else "(none)"

    sections.append(("Environment", (
        f"  CWD:              {cwd}\n"
        f"  Workspace:         {ws_str}\n"
        f"  providers.json:    {prov_file}\n"
        f"  File exists:       {_os.path.isfile(prov_file) if ws else 'N/A'}"
    )))

    # 2. Config file contents
    if ws and _os.path.isfile(prov_file):
        try:
            data = _json.loads(_Path(prov_file).read_text(encoding="utf-8"))
            lines = [f"  Provider count: {len(data)}"]
            for pid, cfg in data.items():
                key = cfg.get("api_key", "")
                masked = (key[:8] + "***" + key[-4:]) if len(key) > 8 else "***"
                lines.append(f"  -- {pid} --")
                lines.append(f"    endpoint:  {cfg.get('endpoint', '?')}")
                lines.append(f"    model:     {cfg.get('model', '?')}")
                lines.append(f"    api_key:   {masked}")
            sections.append(("Config file", "\n".join(lines)))
        except Exception as e:
            sections.append(("Config file", f"  ERROR reading: {e}"))
    else:
        sections.append(("Config file", "  (no providers.json)"))

    # 3. In-memory _providers dict
    try:
        from nous_runtime.compat.provider import _providers as _core_providers
        if _core_providers:
            lines = [f"  Count: {len(_core_providers)}"]
            for pid, prov in _core_providers.items():
                caps = prov.list_capabilities() if hasattr(prov, "list_capabilities") else []
                lines.append(f"  - {pid}  caps={caps}")
            sections.append(("Core _providers dict", "\n".join(lines)))
        else:
            sections.append(("Core _providers dict", "  (empty)"))
    except Exception as e:
        sections.append(("Core _providers dict", f"  ERROR: {e}"))

    # 4. list_providers() return
    try:
        from nous_runtime.services.providers import list_providers
        lp = list_providers()
        lines = [f"  Count: {len(lp)}",
                  f"  Type:  {type(lp).__name__}"]
        for p in lp:
            lines.append(f"  - {p.get('provider_id','?')}  "
                         f"caps={p.get('capabilities',[])}  "
                         f"health={p.get('health',{}).get('status','?')}")
        sections.append(("list_providers()", "\n".join(lines)))
    except Exception as e:
        sections.append(("list_providers()", f"  ERROR: {e}"))

    # 5. Registry.list_all()
    try:
        from nous_runtime.provider.registry import registry
        rl = registry.list_all()
        lines = [f"  Count: {len(rl)}"]
        for p in rl:
            lines.append(f"  - {p.get('name','?')}  id={p.get('id','?')}  "
                         f"caps={p.get('capabilities',[])}  "
                         f"health={p.get('health',{}).get('status','?')}")
        sections.append(("Registry.list_all()", "\n".join(lines)))
    except Exception as e:
        sections.append(("Registry.list_all()", f"  ERROR: {e}"))

    # 6. Capability resolver
    try:
        from nous_runtime.capability.resolver import resolve_capability
        r = resolve_capability("model.reason")
        lines = [
            f"  Resolved:    {r.resolved}",
            f"  Provider ID: {r.provider_id or '(none)'}",
            f"  Provider:    {r.provider_name or '(none)'}",
            f"  Error:       {r.error or '(none)'}",
        ]
        sections.append(("Resolver", "\n".join(lines)))
    except Exception as e:
        sections.append(("Resolver", f"  ERROR: {e}"))

    # 7. Runtime status
    try:
        from nous_runtime.runtime.lifecycle import Runtime
        rt = Runtime()
        s = rt.status()
        lines = [
            f"  Providers:    {s.providers}",
            f"  Capabilities: {s.capabilities}",
        ]
        sections.append(("Runtime.status()", "\n".join(lines)))
    except Exception as e:
        sections.append(("Runtime.status()", f"  ERROR: {e}"))

    # 8. Capability DB
    try:
        from nous_runtime.services.capabilities import list_capabilities, get_capability
        caps = list_capabilities()
        cap_mr = get_capability("model.reason")
        if cap_mr:
            lines = [
                f"  Total caps:   {len(caps)}",
                f"  model.reason: enabled={cap_mr.get('enabled')} "
                f"provider={cap_mr.get('provider')}",
            ]
        else:
            lines = ["  model.reason NOT FOUND in capability DB"]
        sections.append(("Capability DB", "\n".join(lines)))
    except Exception as e:
        sections.append(("Capability DB", f"  ERROR: {e}"))

    # Assemble report
    out: list[str] = ["Provider Visibility Debug", "=" * 56]
    for title, body in sections:
        out.append(f"\n-- {title} --")
        out.append(body)
    return "\n".join(out)

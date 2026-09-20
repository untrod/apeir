"""Dynamic capability summary derived from live runtime state.

The summary is never hand-written. It is derived, in order of preference,
from:

1. The capability availability cross-reference (capability DB + registry).
2. The live provider registry (capabilities of non-down providers).
3. Non-secret provider configuration on disk (no network access).

Every data source is optional; the summary degrades gracefully and never
raises.
"""

from __future__ import annotations

from collections import OrderedDict

AVAILABLE_MARK = "✓"  # check mark
UNAVAILABLE_MARK = "○"  # open circle

# Labels beyond the model.* mapping shared with the provider CLI.
_EXTRA_LABELS = OrderedDict((("Retrieval", "rag.search"),))
_RUNTIME_LABELS = OrderedDict(
    (
        ("Professional documents", "document.create"),
        ("Document rendering", "document.render"),
        ("Execution environments", "environment.run"),
        ("Governed network fetch", "network.fetch"),
        ("Reproducible simulations", "simulation.run"),
        ("Scientific analysis", "scientific.analyze"),
    )
)

_PROVIDER_LABEL_OVERRIDES = {
    # model.code is a dedicated provider route. It must not be presented as
    # the whole workspace coding surface: Chat can still generate code text
    # and request-scoped tools can create files and run governed checks.
    "model.code": "Dedicated code-provider route",
}


def _capability_labels() -> "OrderedDict[str, str]":
    """Friendly label -> capability id, reusing the provider CLI mapping."""
    labels: "OrderedDict[str, str]" = OrderedDict()
    try:
        from nous_runtime.cli.provider_experience import CAPABILITY_MAPPING

        for label, capability_id in CAPABILITY_MAPPING.items():
            labels[_PROVIDER_LABEL_OVERRIDES.get(capability_id, label)] = capability_id
    except Exception:
        labels.update(
            (
                ("Reasoning", "model.reason"),
                ("Dedicated code-provider route", "model.code"),
                ("Embedding", "model.embed"),
                ("Vision", "model.vision"),
                ("Speech", "model.transcribe"),
                ("Rerank", "model.rerank"),
            )
        )
    labels.update(_EXTRA_LABELS)
    return labels


def _matches(capability_id: str, declared: str) -> bool:
    if capability_id == declared:
        return True
    if declared.endswith("*"):
        return capability_id.startswith(declared.rstrip("*"))
    return False


def _ids_from_availability() -> set[str] | None:
    """Primary source: the capability availability cross-reference."""
    from nous_runtime.capability.availability import check_availability

    result = check_availability()
    available = {str(item.get("name") or "") for item in result.get("available") or []}
    return available or None  # nothing available yet; fall through


def _ids_from_registry() -> set[str] | None:
    """Fallback: union of capabilities from healthy registered providers."""
    from nous_runtime.compat.provider import list_providers

    providers = list_providers()
    if not providers:
        return None
    ids: set[str] = set()
    for item in providers:
        health = item.get("health") or {}
        if str(health.get("status") or "") == "down":
            continue
        ids.update(str(capability) for capability in item.get("capabilities") or ())
    return ids or None


def _ids_from_config() -> set[str]:
    """Last resort: derive from providers.json without any network access."""
    from nous_runtime.cli.provider_experience import (
        executable_capabilities,
        read_provider_configs,
    )

    ids: set[str] = set()
    for config in read_provider_configs().values():
        ids.update(
            executable_capabilities(
                str(config.get("kind") or "openai-compatible"),
                config.get("capability_mapping") or ("Reasoning", "Coding"),
            )
        )
    return ids


def _available_capability_ids() -> set[str]:
    for source in (_ids_from_availability, _ids_from_registry, _ids_from_config):
        try:
            ids = source()
        except Exception:
            ids = None
        if ids is not None:
            return ids
    return set()


def capability_flags() -> "OrderedDict[str, bool]":
    """Return friendly capability labels mapped to availability."""
    available_ids = _available_capability_ids()
    flags: "OrderedDict[str, bool]" = OrderedDict()
    for label, capability_id in _capability_labels().items():
        flags[label] = any(_matches(capability_id, item) for item in available_ids)
    return flags


def build_capability_summary() -> str:
    """Render truthful availability and execution-authority groups."""
    try:
        flags = capability_flags()
    except Exception:
        flags = OrderedDict()
    available = [label for label, ok in flags.items() if ok]
    unavailable = [label for label, ok in flags.items() if not ok]
    authorized: list[str] = []
    try:
        from nous_runtime.capability.availability import check_availability
        snapshot = check_availability()
        records = {str(item.get("name") or ""): item for item in snapshot.get("available") or []}
        for label, capability_id in _RUNTIME_LABELS.items():
            record = records.get(capability_id)
            if record and record.get("availability_state") == "requires_authorization":
                authorized.append(label)
    except Exception:
        pass
    if not available and not authorized:
        return "Available capabilities: none (no providers configured - run 'nous provider add')"
    parts: list[str] = []
    if available:
        parts.append("Immediately available: " + " ".join(f"{AVAILABLE_MARK} {label}" for label in available))
    if authorized:
        parts.append(
            "Available: explicit authorization required (Runtime service; local effects do not yet traverse the Rust Kernel): "
            + " ".join(f"{AVAILABLE_MARK} {label}" for label in authorized)
        )
    if unavailable:
        parts.append("Unavailable: " + " ".join(
            f"{UNAVAILABLE_MARK} {label}" for label in unavailable
        ))
    return " / ".join(parts)

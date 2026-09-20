# -*- coding: utf-8 -*-
"""Registry for retained protocol-specific outbound network authorities.

This module classifies low-level transports that must not use the public
Research WebGateway. It is a static ownership contract, not a second policy,
approval, credential, or event system.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EgressAuthority:
    authority_id: str
    owner: str
    network_scope: str
    private_targets_allowed: bool
    credential_boundary: str
    redirect_policy: str
    size_policy: str
    timeout_policy: str
    approval_capability: str
    enforcement: str


@dataclass(frozen=True)
class EgressCallSite:
    path: str
    direct_calls: int
    authority_id: str


AUTHORITIES: dict[str, EgressAuthority] = {
    "research.public_web": EgressAuthority(
        authority_id="research.public_web",
        owner="nous_runtime.evidence.web_gateway.WebGateway",
        network_scope="public_internet",
        private_targets_allowed=False,
        credential_boundary="credential_ref_only",
        redirect_policy="bounded_and_revalidated",
        size_policy="request_1MiB_response_5MiB",
        timeout_policy="single_total_budget_1_to_120_seconds",
        approval_capability="network.fetch",
        enforcement="centralized",
    ),
    "provider.model": EgressAuthority(
        authority_id="provider.model",
        owner="nous_runtime.model_runtime.gateway",
        network_scope="provider_endpoint",
        private_targets_allowed=True,
        credential_boundary="provider_registry_reference",
        redirect_policy="provider_adapter_specific",
        size_policy="provider_contract",
        timeout_policy="provider_contract",
        approval_capability="model.invoke",
        enforcement="retained_protocol_transport",
    ),
    "distribution.download": EgressAuthority(
        authority_id="distribution.download",
        owner="nous_runtime.model_distribution",
        network_scope="artifact_registry",
        private_targets_allowed=False,
        credential_boundary="registry_reference",
        redirect_policy="registry_and_downloader_specific",
        size_policy="streamed_bounded_by_distribution_contract",
        timeout_policy="download_contract",
        approval_capability="model.download",
        enforcement="retained_protocol_transport",
    ),
    "control.runtime": EgressAuthority(
        authority_id="control.runtime",
        owner="nous_runtime.control_plane",
        network_scope="loopback_or_configured_control_plane",
        private_targets_allowed=True,
        credential_boundary="runtime_bearer_token",
        redirect_policy="none",
        size_policy="control_plane_message_contract",
        timeout_policy="control_plane_contract",
        approval_capability="runtime.control",
        enforcement="retained_protocol_transport",
    ),
    "control.node": EgressAuthority(
        authority_id="control.node",
        owner="nous_runtime.connectivity",
        network_scope="configured_node_control_plane",
        private_targets_allowed=True,
        credential_boundary="node_identity",
        redirect_policy="none",
        size_policy="node_protocol_contract",
        timeout_policy="node_protocol_contract",
        approval_capability="node.connect",
        enforcement="retained_protocol_transport",
    ),
    "control.edge": EgressAuthority(
        authority_id="control.edge",
        owner="remote_terminal.nous_edge",
        network_scope="configured_brain_control_plane",
        private_targets_allowed=True,
        credential_boundary="edge_shared_secret",
        redirect_policy="none_required",
        size_policy="edge_protocol_contract",
        timeout_policy="edge_protocol_contract",
        approval_capability="edge.connect",
        enforcement="retained_protocol_transport",
    ),
    "device.agent": EgressAuthority(
        authority_id="device.agent",
        owner="remote_terminal.device_transport",
        network_scope="configured_device_agent",
        private_targets_allowed=True,
        credential_boundary="device_header_only",
        redirect_policy="blocked",
        size_policy="request_1MiB_response_5MiB",
        timeout_policy="per_operation_1_to_120_seconds",
        approval_capability="device.invoke",
        enforcement="centralized",
    ),
    "device.android": EgressAuthority(
        authority_id="device.android",
        owner="nous_runtime.provider.adapters.device_android",
        network_scope="configured_android_agent",
        private_targets_allowed=True,
        credential_boundary="device_pairing_token",
        redirect_policy="adapter_specific",
        size_policy="device_protocol_contract",
        timeout_policy="device_protocol_contract",
        approval_capability="device.invoke",
        enforcement="retained_protocol_transport",
    ),
}


RETAINED_DIRECT_CALL_SITES: tuple[EgressCallSite, ...] = (
    EgressCallSite("remote_terminal/nous_edge/__init__.py", 2, "control.edge"),
    EgressCallSite("nous_runtime/cli/runtime_api.py", 1, "control.runtime"),
    EgressCallSite("nous_runtime/sdk/client.py", 1, "control.runtime"),
    EgressCallSite("nous_runtime/cli/provider_experience.py", 2, "provider.model"),
    EgressCallSite("nous_runtime/provider/adapters/anthropic.py", 1, "provider.model"),
    EgressCallSite("nous_runtime/provider/adapters/ollama.py", 5, "provider.model"),
    EgressCallSite("nous_runtime/provider/adapters/openai.py", 1, "provider.model"),
    EgressCallSite("nous_runtime/cli/registry.py", 3, "distribution.download"),
    EgressCallSite("nous_runtime/model_distribution/downloader.py", 1, "distribution.download"),
    EgressCallSite("nous_runtime/platform/lite_node.py", 1, "control.node"),
    EgressCallSite("nous_runtime/provider/adapters/device_android.py", 1, "device.android"),
)


DIRECT_CALL_BASELINE = {item.path: item.direct_calls for item in RETAINED_DIRECT_CALL_SITES}


def validate_egress_contracts() -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in RETAINED_DIRECT_CALL_SITES:
        if item.path in seen:
            errors.append(f"duplicate_path:{item.path}")
        seen.add(item.path)
        if item.direct_calls < 1:
            errors.append(f"invalid_count:{item.path}")
        if item.authority_id not in AUTHORITIES:
            errors.append(f"missing_authority:{item.path}:{item.authority_id}")
    for authority_id, authority in AUTHORITIES.items():
        if authority.authority_id != authority_id:
            errors.append(f"authority_id_mismatch:{authority_id}")
        for field_name in (
            "owner",
            "network_scope",
            "credential_boundary",
            "redirect_policy",
            "size_policy",
            "timeout_policy",
            "approval_capability",
            "enforcement",
        ):
            if not getattr(authority, field_name):
                errors.append(f"empty_{field_name}:{authority_id}")
    return errors


__all__ = [
    "AUTHORITIES",
    "DIRECT_CALL_BASELINE",
    "EgressAuthority",
    "EgressCallSite",
    "RETAINED_DIRECT_CALL_SITES",
    "validate_egress_contracts",
]

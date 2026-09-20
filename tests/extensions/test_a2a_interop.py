from __future__ import annotations

import asyncio

import httpx
import pytest

from nous_runtime.extensions.a2a_interop import (
    A2AAgentReply,
    A2AInteropError,
    NousA2AClient,
    create_governed_a2a_http_client,
    create_a2a_server,
)


def test_official_a2a_1_client_server_task_and_artifact_interop():
    asyncio.run(_run_official_a2a_1_client_server_task_and_artifact_interop())


async def _run_official_a2a_1_client_server_task_and_artifact_interop():
    async def handler(text: str) -> A2AAgentReply:
        return A2AAgentReply(
            f"Nous 收到：{text}",
            (("analysis", "这是一个无本地权限的远端产物。"),),
        )

    server = create_a2a_server(
        handler,
        public_base_url="http://a2a.test",
        name="Nous Test Agent",
        version="1.2.3",
    )
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app),
        base_url="http://a2a.test",
    )
    try:
        result = await NousA2AClient().discover_and_send(
            http_client=http_client,
            base_url="http://a2a.test",
            message="你好",
            kernel_permit="local-permit-never-sent",
            authorized_origin="http://a2a.test",
        )
    finally:
        await server.aclose()

    assert result.agent_name == "Nous Test Agent"
    assert result.agent_version == "1.2.3"
    assert result.state == "completed"
    assert {"submitted", "working", "completed"} <= set(result.status_history)
    assert result.artifacts == (
        ("result", "Nous 收到：你好"),
        ("analysis", "这是一个无本地权限的远端产物。"),
    )
    assert result.authority == "none"
    assert result.local_effects_authorized is False
    assert result.requires_kernel_for_local_effects is True


def test_a2a_remote_error_is_propagated_as_failed_task():
    asyncio.run(_run_a2a_remote_error_is_propagated_as_failed_task())


async def _run_a2a_remote_error_is_propagated_as_failed_task():
    def handler(_: str) -> str:
        raise RuntimeError("remote failure")

    server = create_a2a_server(handler, public_base_url="http://a2a.test")
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app),
        base_url="http://a2a.test",
    )
    try:
        with pytest.raises(A2AInteropError, match="failed: remote failure"):
            await NousA2AClient().discover_and_send(
                http_client=http_client,
                base_url="http://a2a.test",
                message="fail",
                kernel_permit="local-only",
                authorized_origin="http://a2a.test",
            )
    finally:
        await server.aclose()


def test_a2a_requires_local_permit_and_exact_authorized_origin():
    asyncio.run(_run_a2a_requires_local_permit_and_exact_authorized_origin())


async def _run_a2a_requires_local_permit_and_exact_authorized_origin():
    client = NousA2AClient()
    http_client = httpx.AsyncClient(base_url="https://a2a.example.test")
    with pytest.raises(A2AInteropError, match="Kernel permit"):
        await client.discover_and_send(
            http_client=http_client,
            base_url="https://a2a.example.test",
            message="hello",
            kernel_permit="",
            authorized_origin="https://a2a.example.test",
        )
    with pytest.raises(A2AInteropError, match="outside"):
        await client.discover_and_send(
            http_client=http_client,
            base_url="https://a2a.example.test",
            message="hello",
            kernel_permit="local-only",
            authorized_origin="https://other.example.test",
        )
    await http_client.aclose()


def test_a2a_agent_card_declares_only_protocol_1_jsonrpc():
    server = create_a2a_server(lambda text: text, public_base_url="https://a2a.example.test")
    assert server.card.capabilities.streaming is True
    assert len(server.card.supported_interfaces) == 1
    interface = server.card.supported_interfaces[0]
    assert interface.protocol_binding == "JSONRPC"
    assert interface.protocol_version == "1.0"
    assert interface.url == "https://a2a.example.test/a2a"


def test_a2a_pinned_https_transport_keeps_origin_and_permit_local():
    asyncio.run(_run_a2a_pinned_https_transport_keeps_origin_and_permit_local())


async def _run_a2a_pinned_https_transport_keeps_origin_and_permit_local():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "test"})

    client = create_governed_a2a_http_client(
        "https://agent.example.test",
        kernel_permit="secret-local-permit",
        authorized_origin="https://agent.example.test",
        resolver=lambda _host, _port: ("93.184.216.34",),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        response = await client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        with pytest.raises(A2AInteropError, match="authorized HTTPS surface"):
            await client.get("/not-authorized")
    finally:
        await client.aclose()

    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "agent.example.test"
    assert seen[0].headers["accept-encoding"] == "identity"
    assert seen[0].extensions["sni_hostname"] == "agent.example.test"
    assert "secret-local-permit" not in str(seen[0].headers)


def test_a2a_pinned_transport_rejects_private_ip_and_redirect():
    with pytest.raises(A2AInteropError, match="not a public IP"):
        create_governed_a2a_http_client(
            "https://agent.example.test",
            kernel_permit="local-only",
            authorized_origin="https://agent.example.test",
            resolver=lambda _host, _port: ("127.0.0.1",),
        )
    asyncio.run(_run_a2a_redirect_rejection())


async def _run_a2a_redirect_rejection():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    client = create_governed_a2a_http_client(
        "https://agent.example.test",
        kernel_permit="local-only",
        authorized_origin="https://agent.example.test",
        resolver=lambda _host, _port: ("93.184.216.34",),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(A2AInteropError, match="redirects are forbidden"):
            await client.get("/.well-known/agent-card.json")
    finally:
        await client.aclose()

"""A2A 1.0 interoperability with zero implicit local authority."""

from __future__ import annotations

import inspect
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.client.client_factory import TransportProtocol
from a2a.helpers import (
    get_artifact_text,
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    GetTaskRequest,
    Role,
    SendMessageRequest,
    TaskState,
)
from starlette.applications import Starlette

A2A_PROTOCOL_VERSION = "1.0"
_MAX_MESSAGE_CHARS = 64 * 1024
_MAX_RESULT_CHARS = 1024 * 1024
_A2A_PATHS = frozenset({"/.well-known/agent-card.json", "/a2a"})


class A2AInteropError(RuntimeError):
    """Raised when discovery, protocol, task, or authorization checks fail."""


@dataclass(frozen=True)
class A2AAgentReply:
    text: str
    artifacts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class A2ATaskResult:
    agent_name: str
    agent_version: str
    task_id: str
    context_id: str
    state: str
    artifacts: tuple[tuple[str, str], ...]
    status_history: tuple[str, ...]
    messages: tuple[str, ...]
    authority: str = field(default="none", init=False)
    local_effects_authorized: bool = field(default=False, init=False)
    requires_kernel_for_local_effects: bool = field(default=True, init=False)


@dataclass
class A2AServer:
    app: Starlette
    card: AgentCard
    request_handler: DefaultRequestHandler

    async def aclose(self) -> None:
        await self.request_handler.aclose()


ReplyHandler = Callable[[str], A2AAgentReply | str | Awaitable[A2AAgentReply | str]]


class _DataOnlyAgentExecutor(AgentExecutor):
    def __init__(self, handler: ReplyHandler):
        self._handler = handler

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise A2AInteropError("A2A request does not contain a message")
        task = new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        try:
            value = self._handler(get_message_text(context.message))
            if inspect.isawaitable(value):
                value = await value
            reply = value if isinstance(value, A2AAgentReply) else A2AAgentReply(str(value))
            if len(reply.text) > _MAX_RESULT_CHARS:
                raise A2AInteropError("A2A result exceeds the configured character limit")
            await updater.add_artifact([new_text_part(reply.text)], name="result")
            for name, text in reply.artifacts:
                if len(text) > _MAX_RESULT_CHARS:
                    raise A2AInteropError("A2A artifact exceeds the configured character limit")
                await updater.add_artifact([new_text_part(text)], name=name)
            await updater.complete(
                updater.new_agent_message([new_text_part("A2A task completed")])
            )
        except Exception as exc:
            message = str(exc)[:512] or type(exc).__name__
            await updater.failed(updater.new_agent_message([new_text_part(message)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.task_id or not context.context_id:
            raise A2AInteropError("A2A cancellation requires task and context identifiers")
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def create_a2a_server(
    handler: ReplyHandler,
    *,
    public_base_url: str,
    name: str = "Nous Runtime",
    description: str = "Governed Nous A2A agent",
    version: str = "1.0.0",
) -> A2AServer:
    """Create an official-SDK JSON-RPC server advertising A2A 1.0."""

    rpc_url = public_base_url.rstrip("/") + "/a2a"
    card = AgentCard(
        name=name,
        description=description,
        version=version,
        supported_interfaces=[
            AgentInterface(
                url=rpc_url,
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=A2A_PROTOCOL_VERSION,
            )
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="nous-governed-request",
                name="Nous governed request",
                description="Return proposals, results, and artifacts without local authority",
                tags=["nous", "governed", "interoperability"],
            )
        ],
    )
    request_handler = DefaultRequestHandler(
        _DataOnlyAgentExecutor(handler), InMemoryTaskStore(), card
    )
    routes = create_agent_card_routes(card)
    routes.extend(create_jsonrpc_routes(request_handler, "/a2a"))
    return A2AServer(Starlette(routes=routes), card, request_handler)


class NousA2AClient:
    """Official A2A client requiring a local Kernel permit before egress.

    The permit is validated locally and is never attached to A2A requests.
    Returned artifacts always have ``authority=none``.
    """

    async def discover_and_send(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str,
        message: str,
        kernel_permit: str,
        authorized_origin: str,
    ) -> A2ATaskResult:
        if not kernel_permit.strip():
            raise A2AInteropError("a local Kernel permit is required for A2A egress")
        if _origin(base_url) != _origin(authorized_origin):
            raise A2AInteropError("A2A endpoint is outside the Kernel-authorized origin")
        transport = getattr(http_client, "_transport", None)
        in_process_test = isinstance(transport, httpx.ASGITransport) and (
            urlsplit(base_url).hostname or ""
        ).endswith(".test")
        if not isinstance(transport, A2APinnedHttpsTransport) and not in_process_test:
            raise A2AInteropError("A2A egress requires the governed pinned HTTPS transport")
        if not message or len(message) > _MAX_MESSAGE_CHARS:
            raise A2AInteropError("A2A message is empty or exceeds the configured limit")

        resolver = A2ACardResolver(http_client, base_url)
        card = await resolver.get_agent_card()
        _validate_card(card, authorized_origin)
        client = ClientFactory(
            ClientConfig(
                streaming=True,
                httpx_client=http_client,
                supported_protocol_bindings=[TransportProtocol.JSONRPC.value],
            )
        ).create(card)
        task_id = ""
        statuses: list[str] = []
        messages: list[str] = []
        streamed_artifacts: list[tuple[str, str]] = []
        try:
            request = SendMessageRequest(
                message=new_text_message(message, role=Role.ROLE_USER)
            )
            async for response in client.send_message(request):
                kind = response.WhichOneof("payload")
                if kind == "task":
                    task_id = response.task.id
                    statuses.append(_state_name(response.task.status.state))
                elif kind == "status_update":
                    task_id = response.status_update.task_id
                    statuses.append(_state_name(response.status_update.status.state))
                    if response.status_update.status.HasField("message"):
                        messages.append(
                            get_message_text(response.status_update.status.message)
                        )
                elif kind == "artifact_update":
                    task_id = response.artifact_update.task_id
                    artifact = response.artifact_update.artifact
                    streamed_artifacts.append(
                        (artifact.name, get_artifact_text(artifact))
                    )
                elif kind == "message":
                    messages.append(get_message_text(response.message))
            if not task_id:
                raise A2AInteropError("A2A peer returned no task lifecycle")
            task = await client.get_task(GetTaskRequest(id=task_id, history_length=20))
            state = _state_name(task.status.state)
            artifacts = tuple(
                (artifact.name, get_artifact_text(artifact))
                for artifact in task.artifacts
            ) or tuple(streamed_artifacts)
            if sum(len(text) for _, text in artifacts) > _MAX_RESULT_CHARS:
                raise A2AInteropError("A2A result exceeds the configured character limit")
            if state != "completed":
                detail = (
                    get_message_text(task.status.message)
                    if task.status.HasField("message")
                    else "remote task did not complete"
                )
                raise A2AInteropError(f"A2A task {state}: {detail}")
            return A2ATaskResult(
                agent_name=card.name,
                agent_version=card.version,
                task_id=task.id,
                context_id=task.context_id,
                state=state,
                artifacts=artifacts,
                status_history=tuple(statuses),
                messages=tuple(messages),
            )
        finally:
            await client.close()


class A2APinnedHttpsTransport(httpx.AsyncBaseTransport):
    """Pin A2A card/RPC requests to validated public IPs with verified TLS."""

    def __init__(
        self,
        base_url: str,
        *,
        resolver: Callable[[str, int], Iterable[str]] | None = None,
        max_response_bytes: int = 8 * 1024 * 1024,
        inner: httpx.AsyncBaseTransport | None = None,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
        ):
            raise A2AInteropError("A2A transport requires a credential-free HTTPS origin")
        if max_response_bytes < 1 or max_response_bytes > 16 * 1024 * 1024:
            raise ValueError("A2A response limit must be between 1 byte and 16 MiB")
        self._host = parsed.hostname.rstrip(".").lower()
        self._port = parsed.port or 443
        self._max_response_bytes = max_response_bytes
        self._pinned_addresses = _validated_public_addresses(
            (resolver or _resolve_addresses)(self._host, self._port)
        )
        self._inner = inner or httpx.AsyncHTTPTransport(verify=True, trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").rstrip(".").lower()
        port = request.url.port or 443
        if (
            request.url.scheme.lower() != "https"
            or host != self._host
            or port != self._port
            or request.url.path not in _A2A_PATHS
            or request.url.query
            or request.url.userinfo
            or request.url.fragment
        ):
            raise A2AInteropError("A2A request attempted to leave its authorized HTTPS surface")
        headers = request.headers.copy()
        headers["host"] = self._host if self._port == 443 else f"{self._host}:{self._port}"
        headers["accept-encoding"] = "identity"
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = self._host
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=self._pinned_addresses[0]),
            headers=headers,
            content=request.content,
            extensions=extensions,
        )
        response = await self._inner.handle_async_request(pinned)
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise A2AInteropError("A2A redirects are forbidden")
        encoding = response.headers.get("content-encoding", "identity").lower()
        if encoding not in {"", "identity"}:
            await response.aclose()
            raise A2AInteropError("compressed A2A responses are forbidden")
        declared = response.headers.get("content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                await response.aclose()
                raise A2AInteropError("A2A response has invalid Content-Length") from exc
            if declared_size < 0 or declared_size > self._max_response_bytes:
                await response.aclose()
                raise A2AInteropError("A2A response exceeds the configured byte limit")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_LimitedA2AStream(response, self._max_response_bytes),
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class _LimitedA2AStream(httpx.AsyncByteStream):
    def __init__(self, response: httpx.Response, limit: int):
        self._response = response
        self._limit = limit

    async def __aiter__(self):
        used = 0
        try:
            if self._response.is_stream_consumed:
                chunk = self._response.content
                if len(chunk) > self._limit:
                    raise A2AInteropError("A2A response exceeds the configured byte limit")
                yield chunk
            else:
                async for chunk in self._response.aiter_raw():
                    used += len(chunk)
                    if used > self._limit:
                        raise A2AInteropError(
                            "A2A response exceeds the configured byte limit"
                        )
                    yield chunk
        finally:
            await self._response.aclose()

    async def aclose(self) -> None:
        await self._response.aclose()


def create_governed_a2a_http_client(
    base_url: str,
    *,
    kernel_permit: str,
    authorized_origin: str,
    resolver: Callable[[str, int], Iterable[str]] | None = None,
    max_response_bytes: int = 8 * 1024 * 1024,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
) -> httpx.AsyncClient:
    """Create the only production A2A HTTP profile exposed by Nous."""

    if not kernel_permit.strip():
        raise A2AInteropError("a local Kernel permit is required for A2A egress")
    if _origin(base_url) != _origin(authorized_origin):
        raise A2AInteropError("A2A endpoint is outside the Kernel-authorized origin")
    transport = A2APinnedHttpsTransport(
        base_url,
        resolver=resolver,
        max_response_bytes=max_response_bytes,
        inner=transport_factory() if transport_factory else None,
    )
    return httpx.AsyncClient(
        transport=transport,
        base_url=base_url,
        follow_redirects=False,
        trust_env=False,
    )


def _validate_card(card: AgentCard, authorized_origin: str) -> None:
    if not card.name or not card.version:
        raise A2AInteropError("A2A AgentCard identity is incomplete")
    compatible = [
        interface
        for interface in card.supported_interfaces
        if interface.protocol_binding == TransportProtocol.JSONRPC.value
        and interface.protocol_version == A2A_PROTOCOL_VERSION
    ]
    if not compatible:
        raise A2AInteropError("A2A peer does not advertise JSON-RPC protocol 1.0")
    if any(_origin(interface.url) != _origin(authorized_origin) for interface in compatible):
        raise A2AInteropError("A2A AgentCard redirects outside the authorized origin")


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise A2AInteropError("A2A endpoint must be an absolute HTTP(S) URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.rstrip(".").lower(), port


def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise A2AInteropError(f"A2A host resolution failed: {host}") from exc
    return tuple(dict.fromkeys(record[4][0] for record in records))


def _validated_public_addresses(addresses: Iterable[str]) -> tuple[str, ...]:
    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw in addresses:
        try:
            if "%" in str(raw):
                raise ValueError("scoped IPv6 is forbidden")
            address = ipaddress.ip_address(str(raw))
        except ValueError as exc:
            raise A2AInteropError("A2A resolver returned an invalid IP") from exc
        if (
            not address.is_global
            or address.is_multicast
            or (
                isinstance(address, ipaddress.IPv6Address)
                and (address.sixtofour is not None or address.teredo is not None)
            )
        ):
            raise A2AInteropError(f"A2A destination is not a public IP: {address}")
        parsed.append(address)
    if not parsed:
        raise A2AInteropError("A2A host resolved to no addresses")
    return tuple(str(address) for address in parsed)


def _state_name(value: int) -> str:
    return TaskState.Name(value).removeprefix("TASK_STATE_").lower()

"""OpenAPI 3 execution adapter over the existing governed WebGateway."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

import yaml

from nous_runtime.evidence.web_gateway import WebGateway, WebRequest
from nous_runtime.extensions.executor import AdapterResult, ExtensionInvocation


class OpenApiExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenApiExecutionPolicy:
    timeout_seconds: int = 30
    max_response_bytes: int = 5_242_880
    max_redirects: int = 0
    credential_ref: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.timeout_seconds <= 120:
            raise ValueError("OpenAPI timeout must be between 1 and 120 seconds")
        if not 1 <= self.max_response_bytes <= WebGateway.MAX_CONTENT_SIZE:
            raise ValueError("OpenAPI response limit is outside the gateway boundary")
        if not 0 <= self.max_redirects <= 10:
            raise ValueError("OpenAPI redirect limit must be between 0 and 10")
        if self.credential_ref and not self.credential_ref.startswith("secret://"):
            raise ValueError("OpenAPI credential must be a secret:// reference")


class OpenApiExecutionAdapter:
    """Construct one declared operation; WebGateway owns all network effects."""

    def __init__(
        self,
        gateway: WebGateway | None = None,
        *,
        policies: dict[str, OpenApiExecutionPolicy] | None = None,
    ):
        self.gateway = gateway or WebGateway()
        self.policies = dict(policies or {})

    async def execute(
        self, invocation: ExtensionInvocation, *, permit_id: str
    ) -> AdapterResult:
        if not permit_id:
            raise OpenApiExecutionError("Kernel permit is required")
        if invocation.protocol != "openapi" or invocation.capability != "network.connect":
            raise OpenApiExecutionError("invocation is not an admitted OpenAPI operation")
        spec = _load_spec(invocation.package_root)
        method, route = _parse_operation(invocation.operation)
        if method not in {"GET", "HEAD", "POST"}:
            raise OpenApiExecutionError(
                f"OPENAPI_METHOD_UNSUPPORTED: {method} is not supported by the governed gateway"
            )
        path_item = (spec.get("paths") or {}).get(route)
        operation = path_item.get(method.lower()) if isinstance(path_item, dict) else None
        if not isinstance(operation, dict):
            raise OpenApiExecutionError("OpenAPI operation is absent from installed specification")
        servers = operation.get("servers") or (
            path_item.get("servers") if isinstance(path_item, dict) else None
        ) or spec.get("servers") or ()
        if not servers or not isinstance(servers[0], dict):
            raise OpenApiExecutionError("OpenAPI operation has no server URL")
        base_url = str(servers[0].get("url") or "")
        host = (urlsplit(base_url).hostname or "").rstrip(".").lower()
        allowed_hosts = {item.rstrip(".").lower() for item in invocation.scope}
        if not host or host not in allowed_hosts:
            raise OpenApiExecutionError("OpenAPI server is outside the Kernel-authorized host scope")
        url, body = _build_request(
            base_url,
            route,
            path_item,
            operation,
            invocation.arguments,
            method,
        )
        policy = self.policies.get(invocation.extension_id, OpenApiExecutionPolicy())
        request = WebRequest(
            url=url,
            method=method,
            body=body,
            timeout_seconds=policy.timeout_seconds,
            max_response_bytes=policy.max_response_bytes,
            credential_ref=policy.credential_ref,
            network_scope="public_internet",
            run_id=f"extension:{invocation.extension_id}",
            task_id=invocation.operation,
            approval_requirement="kernel_permit",
            max_redirects=policy.max_redirects,
            max_retries=0,
        )
        response = await asyncio.to_thread(self.gateway.fetch, request)
        if not response.ok:
            return AdapterResult(
                False,
                error_code=response.error_code or "OPENAPI_REQUEST_FAILED",
                output_bytes=response.size_bytes,
            )
        declared = operation.get("responses") or {}
        if declared and str(response.status_code) not in declared and "default" not in declared:
            return AdapterResult(
                False,
                error_code="OPENAPI_UNDECLARED_STATUS",
                output_bytes=response.size_bytes,
            )
        content: Any = response.content
        if "json" in response.content_type.lower() and response.content:
            try:
                content = json.loads(response.content)
            except json.JSONDecodeError:
                return AdapterResult(
                    False,
                    error_code="OPENAPI_INVALID_JSON_RESPONSE",
                    output_bytes=response.size_bytes,
                )
        return AdapterResult(
            True,
            {
                "status_code": response.status_code,
                "content_type": response.content_type,
                "content": content,
                "content_hash": response.content_hash,
                "final_url": response.final_url,
            },
            output_bytes=response.size_bytes,
            verification_status="protocol_and_schema_validated",
        )


def _load_spec(package_root: Path) -> dict[str, Any]:
    candidates = sorted(
        path
        for path in package_root.iterdir()
        if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}
    )
    for path in candidates:
        try:
            value = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.suffix.lower() == ".json"
                else yaml.safe_load(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if isinstance(value, dict) and str(value.get("openapi") or "").startswith("3."):
            return value
    raise OpenApiExecutionError("installed OpenAPI specification is unavailable")


def _parse_operation(value: str) -> tuple[str, str]:
    method, separator, route = value.partition(" ")
    if not separator or not route.startswith("/"):
        raise OpenApiExecutionError("invalid normalized OpenAPI operation")
    return method.upper(), route


def _build_request(
    base_url: str,
    route: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    arguments: dict[str, Any],
    method: str,
) -> tuple[str, Any]:
    remaining = dict(arguments)
    query: list[tuple[str, str]] = []
    parameters = list(path_item.get("parameters") or ()) + list(
        operation.get("parameters") or ()
    )
    for parameter in parameters:
        if not isinstance(parameter, dict) or "$ref" in parameter:
            continue
        name = str(parameter.get("name") or "")
        location = str(parameter.get("in") or "")
        if name not in remaining:
            if parameter.get("required"):
                raise OpenApiExecutionError(f"missing required OpenAPI parameter: {name}")
            continue
        value = remaining.pop(name)
        if location == "path":
            route = route.replace("{" + name + "}", quote(str(value), safe=""))
        elif location == "query":
            if isinstance(value, list):
                query.extend((name, str(item)) for item in value)
            else:
                query.append((name, str(value)))
        elif location in {"header", "cookie"}:
            raise OpenApiExecutionError(
                "OpenAPI header and cookie parameters require an explicit credential boundary"
            )
        else:
            raise OpenApiExecutionError(f"unsupported OpenAPI parameter location: {location}")
    if "{" in route or "}" in route:
        raise OpenApiExecutionError("unresolved OpenAPI path parameter")
    body = remaining.pop("body", None)
    if remaining:
        raise OpenApiExecutionError(
            "undeclared OpenAPI arguments: " + ", ".join(sorted(remaining))
        )
    if body is not None and method != "POST":
        raise OpenApiExecutionError("request body is not supported for this HTTP method")
    parts = urlsplit(urljoin(base_url.rstrip("/") + "/", route.lstrip("/")))
    url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), "")
    )
    return url, body

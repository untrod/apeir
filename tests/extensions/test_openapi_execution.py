from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nous_runtime.evidence.web_gateway import WebGateway, _TransportResponse
from nous_runtime.extensions.executor import ExtensionInvocation
from nous_runtime.extensions.openapi import (
    OpenApiExecutionAdapter,
    OpenApiExecutionError,
    OpenApiExecutionPolicy,
)


def write_spec(root: Path, method: str = "get") -> None:
    root.mkdir()
    operation = {
        "operationId": "operateItem",
        "parameters": [
            {
                "name": "id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            },
            {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
        ],
        "responses": {"200": {"description": "ok"}},
    }
    if method == "post":
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    (root / "openapi.json").write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Adapter", "version": "1.0.0"},
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {"/items/{id}": {method: operation}},
            }
        ),
        encoding="utf-8",
    )


def invocation(root: Path, method="GET", arguments=None, scope=("api.example.test",)):
    return ExtensionInvocation(
        extension_id="openapi/adapter",
        content_digest="sha256:" + "a" * 64,
        operation=f"{method} /items/{{id}}",
        protocol="openapi",
        capability="network.connect",
        scope=scope,
        arguments=arguments or {"id": "a/b", "verbose": True},
        package_root=root,
    )


def gateway(calls: list[dict], body=b'{"ok":true}', content_type="application/json"):
    def transport(**kwargs):
        calls.append(kwargs)
        return _TransportResponse(
            200,
            {"content-type": content_type, "content-length": str(len(body))},
            body,
        )

    return WebGateway(
        resolver=lambda host, port: ["93.184.216.34"],
        transport=transport,
    )


def test_openapi_adapter_builds_bounded_request_through_web_gateway(tmp_path: Path):
    package = tmp_path / "package"
    write_spec(package)
    calls = []
    adapter = OpenApiExecutionAdapter(gateway(calls))
    result = asyncio.run(
        adapter.execute(invocation(package), permit_id="extension-permit-1")
    )
    assert result.success
    assert result.output["content"] == {"ok": True}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.example.test/v1/items/a%2Fb?verbose=True"
    assert calls[0]["timeout"] <= 30
    assert calls[0]["max_bytes"] == WebGateway.MAX_CONTENT_SIZE


def test_openapi_post_body_is_encoded_and_bounded(tmp_path: Path):
    package = tmp_path / "package"
    write_spec(package, "post")
    calls = []
    adapter = OpenApiExecutionAdapter(gateway(calls))
    result = asyncio.run(
        adapter.execute(
            invocation(
                package,
                "POST",
                {"id": "42", "body": {"name": "safe"}},
            ),
            permit_id="extension-permit-2",
        )
    )
    assert result.success
    assert json.loads(calls[0]["body"]) == {"name": "safe"}


def test_openapi_host_outside_kernel_scope_is_blocked_before_transport(tmp_path: Path):
    package = tmp_path / "package"
    write_spec(package)
    calls = []
    adapter = OpenApiExecutionAdapter(gateway(calls))
    with pytest.raises(OpenApiExecutionError, match="outside"):
        asyncio.run(
            adapter.execute(
                invocation(package, scope=("other.example",)),
                permit_id="extension-permit-3",
            )
        )
    assert calls == []


def test_unsupported_method_and_invalid_credential_ref_are_explicit(tmp_path: Path):
    package = tmp_path / "package"
    write_spec(package, "delete")
    adapter = OpenApiExecutionAdapter(gateway([]))
    with pytest.raises(OpenApiExecutionError, match="METHOD_UNSUPPORTED"):
        asyncio.run(
            adapter.execute(
                invocation(package, "DELETE"), permit_id="extension-permit-4"
            )
        )
    with pytest.raises(ValueError, match="secret://"):
        OpenApiExecutionPolicy(credential_ref="raw-api-key")


def test_openapi_invalid_declared_json_is_failure_not_success(tmp_path: Path):
    package = tmp_path / "package"
    write_spec(package)
    adapter = OpenApiExecutionAdapter(
        gateway([], body=b"not-json", content_type="application/json")
    )
    result = asyncio.run(
        adapter.execute(invocation(package), permit_id="extension-permit-5")
    )
    assert not result.success
    assert result.error_code == "NETWORK_MIME_MISMATCH"

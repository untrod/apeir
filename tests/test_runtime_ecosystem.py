from __future__ import annotations

import sqlite3
from pathlib import Path

from nous_runtime.connectors.adapters import SQLiteConnector
from nous_runtime.connectors.models import (
    ConnectorAction,
    ConnectorManifest,
    ConnectorRequest,
)
from nous_runtime.connectors.store import ConnectorStore
from nous_runtime.events import EventStream, RunState
from nous_runtime.ide.protocol import IDERequest, IDERuntimeProtocol
from nous_runtime.sdk.client import NousClient
from nous_runtime.sdk.developer import render_template


def test_ide_protocol_reads_authoritative_run_events(tmp_path):
    stream = EventStream(str(tmp_path))
    stream.create_run("run_ide", task_id="task_ide")
    stream.emit_state_change("run_ide", RunState.RUNNING)
    protocol = IDERuntimeProtocol(str(tmp_path))

    listed = protocol.handle(IDERequest("run.list"))
    shown = protocol.handle(IDERequest("run.show", {"run_id": "run_ide"}))

    assert listed.ok and listed.data[0]["run_id"] == "run_ide"
    assert shown.ok and shown.data["run"]["state"] == "RUNNING"
    assert protocol.handle(IDERequest("unknown.action")).ok is False


def test_python_sdk_chat_and_workflow_use_server_runtime_paths(monkeypatch):
    client = NousClient(token="token")
    posted = []

    def post(path, payload):
        posted.append((path, payload))
        if path == "/api/chat":
            return {"ok": True, "data": {"message": "ok", "conversation_id": "conversation"}}
        return {"ok": True, "data": {"run_id": "workflow-run"}}

    monkeypatch.setattr(client, "_post", post)

    chat = client.chat("hello", workspace_id="workspace")
    workflow = client.workflow("wf", {"value": 1})

    assert chat.ok and chat.capability_id == "chat.runtime"
    assert chat.result["conversation_id"] == "conversation"
    assert workflow["ok"] is True
    assert posted == [
        ("/api/chat", {"text": "hello", "workspace_id": "workspace"}),
        (
            "/api/workflow/run",
            {
                "workflow_id": "wf",
                "version": "1.0.0",
                "inputs": {"value": 1},
                "idempotency_key": "",
            },
        ),
    ]


def test_sqlite_connector_is_read_only_and_bounded(tmp_path):
    database = tmp_path / "items.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE items (id INTEGER, name TEXT)")
        connection.execute("INSERT INTO items VALUES (1, 'one')")
        connection.commit()
    finally:
        connection.close()
    connector = SQLiteConnector(database)

    result = connector.execute(ConnectorRequest("sqlite", "query", "ws", {"sql": "SELECT * FROM items"}), None)
    denied = connector.execute(ConnectorRequest("sqlite", "query", "ws", {"sql": "DELETE FROM items"}), None)

    assert result.ok and result.items == ({"id": 1, "name": "one"},)
    assert denied.ok is False and denied.error_code == "READ_ONLY_REQUIRED"


def test_connector_enable_disable_reuses_connector_store(tmp_path):
    store = ConnectorStore(tmp_path)
    manifest = ConnectorManifest("example", "0.1.0", (ConnectorAction("read"),))
    store.register(manifest)

    assert store.set_enabled("example", False) is True
    assert store.get("example")[2] is True
    assert store.set_enabled("example", True) is True
    assert store.get("example")[2] is False


def test_dx_templates_cover_runtime_ecosystem_without_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for kind in ("runtime", "workflow", "agent", "plugin", "connector", "provider", "capability"):
        files = render_template(kind, "hello_world")
        assert files
        assert not any(tmp_path.iterdir())
        for content in files.values():
            assert "secret-value" not in content


def test_desktop_and_ide_clients_do_not_put_tokens_in_query_strings():
    desktop = Path("desktop/src/lib/api.ts").read_text(encoding="utf-8")
    extension = Path("ide/vscode/src/extension.ts").read_text(encoding="utf-8")

    assert "?token=" not in desktop
    assert "Authorization" in desktop
    assert "Authorization" in extension
    assert "localStorage.setItem" not in desktop
    assert "EventSource(" not in desktop
    assert "/api/v1/events/stream" in desktop
    assert "/api/v1/status" in desktop


def test_typescript_sdk_exposes_required_runtime_methods():
    source = Path("nous_runtime/sdk/client.js").read_text(encoding="utf-8")
    for method in ("chat(", "workflow(", "listRuns(", "runEvents(", "events("):
        assert method in source

def test_ide_server_route_requires_auth_and_uses_protocol(monkeypatch):
    from nous_runtime.api.routes import route_server

    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")
    denied = route_server("POST", "/api/ide/runtime", body={"action": "unknown.action"})
    response = route_server(
        "POST",
        "/api/ide/runtime",
        body={"action": "unknown.action"},
        auth={"headers": {"Authorization": "Bearer test-token"}},
    )

    assert denied["error"]["code"] == "NOUS_UNAUTHENTICATED"
    assert response["error"]["code"] == "NOUS_IDE_REQUEST_ERROR"


def test_authoritative_product_facades_are_registered():
    from nous_runtime.api.routes import ROUTES

    expected = {
        ("GET", "/api/runtime/runs"),
        ("GET", "/api/workspace"),
        ("GET", "/api/control/approvals"),
        ("POST", "/api/workflow/run"),
        ("POST", "/api/ide/runtime"),
    }
    assert expected <= set(ROUTES)


def test_typed_sdk_uses_bearer_auth_and_authoritative_paths():
    source = Path("nous_runtime/sdk/client.ts").read_text(encoding="utf-8")

    assert "Authorization" in source
    assert "/api/workflow/run" in source
    assert "/api/runtime/runs" in source
    assert "?token=" not in source

def test_python_sdk_has_no_local_runtime_execution_imports():
    source = Path("nous_runtime/sdk/client.py").read_text(encoding="utf-8")

    assert "execute_capability" not in source
    assert "from nous_runtime.kernel" not in source
    assert "from nous_runtime.services" not in source


def test_python_sdk_authenticated_http_smoke(tmp_path, monkeypatch):
    import threading

    from nous_runtime.api.server import create_server

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOUS_API_TOKEN", "sdk-smoke-token")
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = NousClient(port=server.server_port, token="sdk-smoke-token", timeout=5)
        assert client.health()["ok"] is True
        assert client.status().version
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def test_event_replay_facade_uses_canonical_event_stream(tmp_path, monkeypatch):
    from nous_runtime.api.routes import handle_run_events

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    stream = EventStream(str(tmp_path))
    stream.create_run("replay_run", task_id="task")
    stream.emit_state_change("replay_run", RunState.RUNNING)

    first = handle_run_events("replay_run", after_sequence=0, limit=1)
    cursor = first["data"]["next_after_sequence"]
    second = handle_run_events("replay_run", after_sequence=cursor, limit=10)

    assert first["ok"] and len(first["data"]["events"]) == 1
    assert all(event["sequence"] > cursor for event in second["data"]["events"])


def test_vscode_manifest_exposes_context_and_approval_commands():
    import json

    manifest = json.loads(Path("ide/vscode/package.json").read_text(encoding="utf-8"))
    commands = {item["command"] for item in manifest["contributes"]["commands"]}
    context_commands = {item["command"] for item in manifest["contributes"]["menus"]["editor/context"]}

    assert {"nous.approve", "nous.reject"} <= commands
    assert {"nous.explain", "nous.review", "nous.optimize", "nous.refactor", "nous.generateTests"} <= context_commands
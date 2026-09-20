import json

from typer.testing import CliRunner

from nous_runtime.capability.resolver import execute_capability_observation
from nous_runtime.cli.main import app
from nous_runtime.intelligence.reliability import CircuitState, CircuitStateRecord, JsonlReliabilityStore, snapshot_hash
from nous_runtime.api.routes import route
from nous_runtime.project.workspace import init_workspace
from remote_terminal.nous_core.provider import Provider, register_adapter, unregister_adapter


CAPABILITY_ID = "test.p5_reliability.reason"


class _Provider(Provider):
    provider_id = "p5_reliability_test"
    provider_name = "p5_reliability_test"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def list_capabilities(self):
        return [CAPABILITY_ID]

    def invoke(self, capability_id, **params):
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return {"ok": True, "content": "ok", "model": params.get("model", "m")}

    def health(self):
        return {"status": "ok"}


def _workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return init_workspace(tmp_path)


def _install(provider):
    unregister_adapter(provider.provider_id)
    register_adapter(provider)
    return provider


def test_capability_execution_uses_reliability_wrapper_success(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    provider = _install(_Provider([{"ok": True, "content": "done", "model": "m"}]))

    obs = execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m")
    store = JsonlReliabilityStore(ws)
    health = store.get_current_health(provider.provider_id, "m")

    assert obs.status == "success"
    assert obs.metadata["reliability_wrapped"] is True
    assert health is not None
    assert health.status == "ok"
    assert provider.calls == 1


def test_retryable_provider_failure_retries_and_persists(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    provider = _install(_Provider([
        {"ok": False, "error": "server_error", "error_code": "server_error", "http_status": 500},
        {"ok": True, "content": "recovered", "model": "m"},
    ]))

    obs = execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m")
    store = JsonlReliabilityStore(ws)

    assert obs.status == "success"
    assert provider.calls == 2
    assert store.list_retries()
    assert store.list_signals(provider_id=provider.provider_id)


def test_forced_open_circuit_blocks_provider_call(tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    provider = _install(_Provider([{"ok": True, "content": "should not run", "model": "m"}]))
    store = JsonlReliabilityStore(ws)
    store.append_circuit_event(
        CircuitStateRecord(
            record_id=snapshot_hash({"provider": provider.provider_id, "state": "forced_open"}),
            breaker_key=f"{provider.provider_id}:*",
            state=CircuitState.FORCED_OPEN,
            previous_state=CircuitState.CLOSED,
            transition_reason="test",
        )
    )

    obs = execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m")

    assert obs.status == "failed"
    assert obs.metadata["error_code"] == "NOUS_CIRCUIT_OPEN"
    assert provider.calls == 0


def test_provider_reliability_cli_verify_and_circuit_controls(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    runner = CliRunner()

    opened = runner.invoke(app, ["provider", "circuit", "open", "p5_cli", "--json"])
    shown = runner.invoke(app, ["provider", "circuit", "p5_cli", "--json"])
    closed = runner.invoke(app, ["provider", "circuit", "close", "p5_cli", "--json"])
    verify = runner.invoke(app, ["provider", "reliability", "verify", "--json"])

    assert opened.exit_code == 0
    assert json.loads(opened.stdout)["state"] == "forced_open"
    assert json.loads(shown.stdout)["state"] == "forced_open"
    assert closed.exit_code == 0
    assert json.loads(closed.stdout)["state"] == "closed"
    assert verify.exit_code == 0
    assert json.loads(verify.stdout)["canonical_wrapper"] is True


def test_inspector_provider_reliability_view(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    provider = _install(_Provider([{"ok": False, "error": "server_error", "http_status": 500}]))

    execute_capability_observation(CAPABILITY_ID, prompt="hello", model="m", _max_attempts=1)
    response = route("GET", "/api/inspector/providers/reliability", params={"provider_id": provider.provider_id})

    assert response["ok"] is True
    assert response["data"]["provider_id"] == provider.provider_id
    assert response["data"]["recent_failures"]

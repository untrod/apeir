"""Persisted performance history belongs to its selected workspace, not billing."""

import json
import os
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nous_runtime.api import routes
from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
from nous_runtime.model_runtime import observation_store


def test_public_record_survives_connection_close_and_reopen(tmp_path):
    owner = observation_store.ModelObservationStore(str(tmp_path))
    try:
        recorded = owner.record(
            model_id="shared/model",
            provider_id="fake-history-provider",
            trace_id="fake-original-trace",
            session_id="fake-original-session",
            prompt_tokens=3,
            completion_tokens=2,
            latency_ms=12,
            cost_usd=0.001,
            tags={"source": "owned-fixture"},
            metadata={"fixture": True},
        )
    finally:
        owner.shutdown()
    reopened = observation_store.ModelObservationStore(str(tmp_path))
    try:
        assert reopened.query(model_id="shared/model") == [recorded.to_dict()]
        assert reopened.count() == 1
    finally:
        reopened.shutdown()


def test_protected_history_reads_selected_workspace_and_preserves_sample_floor(
    tmp_path, monkeypatch
):
    roots = {name: tmp_path / name for name in ("a", "b", "legacy")}
    for name, root in roots.items():
        root.mkdir()
        owner = observation_store.ModelObservationStore(str(root))
        try:
            for _ in range(2 if name == "a" else 1):
                owner.record(
                    model_id="shared/model",
                    provider_id=f"fake-{name}",
                    trace_id=f"fake-trace-{name}",
                )
        finally:
            owner.shutdown()
    observation_store.reset_observation_store()
    legacy = observation_store.get_observation_store(str(roots["legacy"]))
    token = "APEIR_FAKE_ONLY_HISTORY_HTTP_TOKEN_ba16"
    monkeypatch.chdir(roots["legacy"])
    monkeypatch.setenv("NOUS_API_TOKEN", token)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(roots["a"]))
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()

    def read(path, *, authenticated=True):
        headers = {"Authorization": "Bearer " + token} if authenticated else {}
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/models/" + path,
            headers=headers,
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            envelope = json.load(response)
        assert envelope["ok"] is True
        return envelope["data"]

    try:
        with pytest.raises(HTTPError) as denied:
            read("observations", authenticated=False)
        with denied.value as response:
            assert response.code == 401
            assert b"fake-trace" not in response.read()
        for name in ("a", "b", "a"):
            monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(roots[name]))
            history = read("observations?model_id=shared%2Fmodel")
            assert history["count"] == (2 if name == "a" else 1)
            assert {item["provider_id"] for item in history["observations"]} == {
                f"fake-{name}"
            }
            assert {item["trace_id"] for item in history["observations"]} == {
                f"fake-trace-{name}"
            }
            assert read("rankings")["rankings"] == []  # Default requires ten.
            at_two = read("rankings?min_samples=2")["rankings"]
            assert len(at_two) == (1 if name == "a" else 0)
            one = read("rankings?min_samples=1")["rankings"]
            assert len(one) == 1 and one[0]["provider_id"] == f"fake-{name}"
        # API-owned readers must not retire an existing SDK writer.
        assert legacy.count() == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        observation_store.reset_observation_store()
    assert not thread.is_alive()


@pytest.mark.parametrize(
    ("method", "handler"),
    [
        ("query", routes.handle_model_observations),
        ("get_model_rankings", routes.handle_model_rankings),
    ],
)
def test_history_read_failure_closes_reader_without_private_error(
    tmp_path, monkeypatch, method, handler
):
    marker = "APEIR_FAKE_ONLY_PRIVATE_HISTORY_FAILURE"
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    closed = []
    original = observation_store.ModelObservationStore.shutdown

    def fail(_self, **_kwargs):
        raise RuntimeError(marker)

    def shutdown(owner):
        original(owner)
        closed.append(owner)

    monkeypatch.setattr(observation_store.ModelObservationStore, method, fail)
    monkeypatch.setattr(observation_store.ModelObservationStore, "shutdown", shutdown)
    result = handler()
    assert result["ok"] is False
    assert result["error"]["code"] == "NOUS_INTERNAL_ERROR"
    assert marker not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)
    assert len(closed) == 1 and closed[0]._db is None


@pytest.mark.parametrize(
    "handler", [routes.handle_model_observations, routes.handle_model_rankings]
)
def test_history_cannot_fall_back_to_cwd_for_missing_selected_workspace(
    tmp_path, monkeypatch, handler
):
    missing = tmp_path / "missing"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(missing))
    result = handler()
    assert result["ok"] is False
    assert not missing.exists()
    assert not (tmp_path / ".nous").exists()


def test_corrupt_database_is_unavailable_without_replacing_original_bytes(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    path = tmp_path / ".nous" / "model_observations.db"
    path.parent.mkdir()
    original = b"FAKE_ONLY_DAMAGED_OBSERVATION_DATABASE"
    path.write_bytes(original)
    for handler in (routes.handle_model_observations, routes.handle_model_rankings):
        response = handler()
        assert response["ok"] is False
        assert response["error"]["code"] == "NOUS_INTERNAL_ERROR"
        assert "FAKE_ONLY_DAMAGED" not in json.dumps(response)
    assert path.read_bytes() == original
    assert str(path) not in caplog.text


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_linked_database_or_sidecar_is_refused_before_sqlite_open(
    tmp_path, monkeypatch, suffix
):
    root = tmp_path / "project"
    (root / ".nous").mkdir(parents=True)
    outside = tmp_path / "owned-private-fixture"
    original = b"FAKE_ONLY_OUTSIDE_HISTORY"
    outside.write_bytes(original)
    os.link(outside, root / ".nous" / ("model_observations.db" + suffix))
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(root))

    def forbidden(*_args, **_kwargs):
        pytest.fail("linked model state reached SQLite")

    monkeypatch.setattr(observation_store.sqlite3, "connect", forbidden)
    result = routes.handle_model_observations()
    assert result["ok"] is False
    assert outside.read_bytes() == original
    assert "FAKE_ONLY_OUTSIDE_HISTORY" not in json.dumps(result)


def test_invalid_history_payload_is_not_an_empty_success(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    owner = observation_store.ModelObservationStore(str(tmp_path))
    try:
        owner.record(model_id="shared", provider_id="fake-provider")
        owner._db.execute(
            "UPDATE model_observations SET payload=?", ("FAKE_ONLY_INVALID_JSON",)
        )
        owner._db.commit()
    finally:
        owner.shutdown()
    result = routes.handle_model_observations()
    assert result["ok"] is False
    assert "FAKE_ONLY_INVALID_JSON" not in json.dumps(result)


def test_failed_sqlite_configuration_closes_each_owned_connection(
    tmp_path, monkeypatch, caplog
):
    original_connect = sqlite3.connect
    opened = []

    class Connection(sqlite3.Connection):
        closed = False

        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("FAKE_ONLY_PRIVATE_SETUP_FAILURE")

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=Connection, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(observation_store.sqlite3, "connect", connect)
    owner = observation_store.ModelObservationStore(str(tmp_path))
    try:
        with pytest.raises(observation_store.ModelObservationError):
            owner.record(model_id="shared", provider_id="fake-provider")
        assert opened and all(connection.closed for connection in opened)
        assert owner._db is None
        assert "FAKE_ONLY_PRIVATE_SETUP_FAILURE" not in caplog.text
    finally:
        owner.shutdown()


def test_lost_commit_confirmation_preserves_original_row_without_retry(
    tmp_path, monkeypatch
):
    original_connect = sqlite3.connect
    writes = []

    class Connection(sqlite3.Connection):
        written = False

        def execute(self, sql, *args, **kwargs):
            if sql.lstrip().startswith("INSERT OR REPLACE INTO model_observations"):
                writes.append(True)
                self.written = True
            return super().execute(sql, *args, **kwargs)

        def commit(self):
            super().commit()
            if self.written:
                raise sqlite3.OperationalError("FAKE_ONLY_LOST_COMMIT_CONFIRMATION")

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Connection, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(observation_store.sqlite3, "connect", connect)
        owner = observation_store.ModelObservationStore(str(tmp_path))
        try:
            with pytest.raises(observation_store.ModelObservationError):
                owner.record(
                    model_id="shared",
                    provider_id="fake-provider",
                    trace_id="fake-original-request",
                )
        finally:
            owner.shutdown()
    reopened = observation_store.ModelObservationStore(str(tmp_path))
    try:
        history = reopened.query()
        assert len(history) == 1
        assert history[0]["trace_id"] == "fake-original-request"
        assert writes == [True]
    finally:
        reopened.shutdown()

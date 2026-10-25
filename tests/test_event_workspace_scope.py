"""The existing global bus stays with its configured workspace owner."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from nous_runtime.events import bus as bus_module


@pytest.fixture(autouse=True)
def retire_owned_bus(monkeypatch):
    bus_module.reset_event_bus()
    monkeypatch.delenv("NOUS_WORKSPACE_ROOT", raising=False)
    yield
    bus_module.reset_event_bus()


def test_default_factory_uses_configured_workspace_instead_of_launcher_cwd(
    tmp_path, monkeypatch
):
    launcher = tmp_path / "launcher"
    launcher.mkdir()
    owner = tmp_path / "owner"
    monkeypatch.chdir(launcher)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(owner))
    bus = bus_module.get_event_bus()
    event = bus.publish("qualification.owner", payload={"owned": True})
    bus.shutdown()
    assert (owner / ".nous" / "event_bus.db").is_file()
    assert not (launcher / ".nous" / "event_bus.db").exists()
    assert bus.stream_events()[0]["event_id"] == event.event_id


def test_existing_owner_cannot_be_rebound_by_explicit_or_environment_change(
    tmp_path, monkeypatch
):
    owner = tmp_path / "owner"
    other = tmp_path / "other"
    bus = bus_module.get_event_bus(str(owner))
    original = bus.publish("qualification.owner").event_id
    with pytest.raises(RuntimeError, match="workspace"):
        bus_module.get_event_bus(str(other))
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(other))
    with pytest.raises(RuntimeError, match="workspace"):
        bus_module.get_event_bus()
    assert not (other / ".nous" / "event_bus.db").exists()
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(owner))
    assert bus_module.get_event_bus() is bus
    bus.shutdown()
    assert bus.stream_events()[0]["event_id"] == original


def test_relative_owner_is_pinned_before_cwd_changes(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    bus = bus_module.get_event_bus("owner")
    monkeypatch.chdir(second)
    assert bus_module.get_event_bus() is bus
    bus.publish("qualification.owner")
    bus.shutdown()
    assert (first / "owner" / ".nous" / "event_bus.db").is_file()
    assert not (second / "owner" / ".nous" / "event_bus.db").exists()


def test_concurrent_initialization_retains_exactly_one_owner(tmp_path):
    barrier = threading.Barrier(2)
    outcomes = []

    def acquire(name):
        barrier.wait(timeout=5)
        try:
            bus_module.get_event_bus(str(tmp_path / name))
            outcomes.append("owned")
        except RuntimeError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=acquire, args=(name,)) for name in ("a", "b")]
    try:
        for thread in threads:
            thread.start()
    finally:
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["owned", "rejected"]


@pytest.mark.parametrize("early_probe_error", [None, URLError, TimeoutError])
def test_real_cli_http_replays_only_its_original_workspace_events(
    tmp_path, early_probe_error
):
    source = str(Path(__file__).resolve().parents[1])
    launcher = tmp_path / "launcher"
    launcher.mkdir()
    owners = [tmp_path / "owner-a", tmp_path / "owner-b"]
    token = "APEIR_FAKE_ONLY_EVENT_OWNER_QUALIFICATION"
    base = {**os.environ, "PYTHONPATH": source, "NOUS_API_TOKEN": token}
    original_ids = []
    for index, owner in enumerate(owners):
        owner.mkdir()
        program = (
            "import json; from nous_runtime.events.bus import get_event_bus; "
            "bus=get_event_bus(); "
            f"event=bus.publish('qualification.owner',payload={{'owner':{index}}}); "
            "bus.shutdown(); print(json.dumps({'id':event.event_id}))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            cwd=launcher,
            env={**base, "NOUS_WORKSPACE_ROOT": str(owner)},
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        original_ids.append(json.loads(completed.stdout)["id"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nous_runtime.cli.main",
            "--no-intelligence",
            "runtime-api",
            "start",
            "--port",
            str(port),
        ],
        cwd=launcher,
        env={**base, "NOUS_WORKSPACE_ROOT": str(owners[1])},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    first_probe = True

    def request(**query):
        nonlocal first_probe
        if first_probe:
            first_probe = False
            if early_probe_error is not None:
                # The CLI intentionally binds before initialization, preventing
                # a second launch from rotating an existing session. A connected
                # socket is not proof that the HTTP serving loop is ready yet.
                raise early_probe_error("injected pre-serving startup probe")
        url = f"http://127.0.0.1:{port}/api/v1/events/stream?" + urlencode(query)
        return urlopen(
            Request(url, headers={"Authorization": "Bearer " + token}), timeout=1
        )

    try:
        until = time.monotonic() + 10
        response = None
        while time.monotonic() < until:
            if child.poll() is not None:
                pytest.fail("Owned model-disabled API exited during startup")
            try:
                with request(domain="qualification") as stream:
                    response = json.load(stream)
                break
            except (URLError, TimeoutError):
                # Retry only read-only readiness probes within the same original
                # 10-second startup deadline. Foreign cursor assertions and the
                # one-second request deadline below remain unchanged.
                time.sleep(0.05)
        assert response is not None, "Owned CLI HTTP startup deadline exceeded"
        assert response["ok"] is True
        assert [event["event_id"] for event in response["data"]["events"]] == [
            original_ids[1]
        ]
        with pytest.raises(HTTPError) as error:
            request(domain="qualification", since_event_id=original_ids[0])
        assert error.value.code == 409
        assert (
            json.load(error.value)["error"]["code"] == "NOUS_EVENT_CURSOR_UNAVAILABLE"
        )
        assert not (launcher / ".nous" / "event_bus.db").exists()
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
            pytest.fail("Owned CLI failed normal test cleanup")

"""Global event-ID replay is distinct from per-Run numeric sequences."""

import pytest

from nous_runtime.events.bus import RuntimeEventBus


@pytest.fixture
def bus(tmp_path):
    value = RuntimeEventBus(str(tmp_path), persist_interval_sec=3600)
    try:
        yield value
    finally:
        value.shutdown()


def publish(bus, count=230):
    events = [bus.publish("task.updated", payload={"ordinal": i}) for i in range(count)]
    bus.query()  # Existing public query initializes the existing DB.
    bus._flush_pending()
    return events


def ids(rows):
    return [row["event_id"] for row in rows]


def test_initial_window_is_chronological_and_replays_beyond_recent_page(bus):
    events = publish(bus)
    assert ids(bus.stream_events(limit=20)) == [e.event_id for e in events[-20:]]
    assert ids(bus.stream_events(since_event_id=events[0].event_id, limit=20)) == [
        e.event_id for e in events[1:21]
    ]


def test_all_pages_retain_original_ids_once_after_restart(bus, tmp_path):
    events = publish(bus)
    bus.shutdown()
    restored = RuntimeEventBus(str(tmp_path), persist_interval_sec=3600)
    try:
        seen = []
        cursor = events[0].event_id
        for _ in range(20):
            page = restored.stream_events(since_event_id=cursor, limit=17)
            if not page:
                break
            seen.extend(ids(page))
            cursor = page[-1]["event_id"]
        assert seen == [e.event_id for e in events[1:]]
        assert len(set(seen)) == len(seen)
    finally:
        restored.shutdown()


@pytest.mark.parametrize("cursor", ["missing-event", "0", "1"])
def test_unavailable_cursor_is_not_a_successful_recent_snapshot(bus, cursor):
    publish(bus, 3)
    with pytest.raises(ValueError, match="cursor unavailable"):
        bus.stream_events(since_event_id=cursor, limit=2)


def test_cursor_in_another_domain_retains_exact_order(bus):
    first = bus.publish("node.online")
    cursor = bus.publish("task.created")
    second = bus.publish("node.offline")
    bus.query()
    bus._flush_pending()
    assert ids(bus.stream_events(domain="node", since_event_id=cursor.event_id)) == [
        second.event_id
    ]
    assert first.event_id != second.event_id


def test_first_flush_before_any_query_keeps_original_event(bus):
    original = bus.publish("node.online")
    bus._flush_pending()
    assert ids(bus.query()) == [original.event_id]


def test_stream_includes_pending_events_without_requiring_a_sleep(bus):
    original = bus.publish("task.created")
    assert ids(bus.stream_events()) == [original.event_id]


def test_tail_cursor_does_not_replay_and_new_publish_advances(bus):
    events = publish(bus, 2)
    assert bus.stream_events(since_event_id=events[-1].event_id) == []
    latest = bus.publish("task.updated")
    assert ids(bus.stream_events(since_event_id=events[-1].event_id)) == [
        latest.event_id
    ]


def test_unavailable_persistence_retains_queue_and_does_not_certify_empty_history(
    bus, monkeypatch
):
    original = bus.publish("task.created")
    with monkeypatch.context() as scoped:
        scoped.setattr(bus, "_ensure_db", lambda: None)
        assert bus._flush_pending() is False
        with pytest.raises(RuntimeError, match="history unavailable"):
            bus.stream_events()
        assert [e.event_id for e in bus._pending_persist] == [original.event_id]
    assert ids(bus.stream_events()) == [original.event_id]


def test_removed_cursor_is_a_history_gap_and_domain_is_literal(bus):
    events = publish(bus, 3)
    with bus._db:
        bus._db.execute(
            "DELETE FROM event_bus WHERE event_id = ?", (events[0].event_id,)
        )
    with pytest.raises(ValueError, match="cursor unavailable"):
        bus.stream_events(since_event_id=events[0].event_id)
    assert bus.stream_events(domain="task%") == []


def test_concurrent_publish_and_flush_preserves_every_original_event_once(bus):
    from concurrent.futures import ThreadPoolExecutor

    def writer(index):
        result = []
        for ordinal in range(30):
            result.append(
                bus.publish(
                    "task.updated", payload={"writer": index, "ordinal": ordinal}
                )
            )
            if ordinal % 7 == 0:
                assert bus._flush_pending()
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        expected = [
            event.event_id for group in pool.map(writer, range(4)) for event in group
        ]
    actual = ids(bus.stream_events(limit=200))
    assert len(actual) == len(set(actual)) == len(expected) == 120
    assert set(actual) == set(expected)


def test_actual_authenticated_http_replay_reports_a_gap_without_recent_fallback(
    bus, monkeypatch
):
    import json
    import threading
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    import nous_runtime.events.bus as bus_module
    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer

    token = "APEIR_FAKE_ONLY_EVENT_HTTP"
    monkeypatch.setenv("NOUS_API_TOKEN", token)
    monkeypatch.setattr(bus_module, "get_event_bus", lambda: bus)
    events = publish(bus, 230)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    def call(query="", authenticated=True):
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/events/stream?limit=20"
            + query,
            headers={"Authorization": "Bearer " + token} if authenticated else {},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    try:
        assert call(authenticated=False)[0] == 401
        status, response = call("&since_event_id=" + events[0].event_id)
        assert status == 200 and response["ok"]
        assert response["data"]["ordering"] == "oldest_first"
        assert ids(response["data"]["events"]) == [
            event.event_id for event in events[1:21]
        ]
        assert response["data"]["latest_event_id"] == events[20].event_id
        status, response = call("&since_event_id=0")
        assert status == 409 and response["ok"] is False
        assert response["error"]["code"] == "NOUS_EVENT_CURSOR_UNAVAILABLE"
        assert "events" not in response.get("data", {})
        with monkeypatch.context() as scoped:

            def unavailable():
                raise RuntimeError("fake-private-storage-detail")

            scoped.setattr(bus, "_flush_pending", unavailable)
            status, response = call()
            assert (
                status == 503
                and response["error"]["code"] == "NOUS_EVENT_STREAM_UNAVAILABLE"
            )
            assert "fake-private-storage-detail" not in json.dumps(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()

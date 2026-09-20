"""Legacy web search must preserve pending review identity without reusing runs."""

from __future__ import annotations

from remote_terminal import tools


def test_legacy_search_keeps_id_while_pending_then_rotates(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")
    tools._legacy_search_pending_ids.clear()
    calls: list[str] = []
    outcomes = ["pending", "done", "done"]

    def route_server(method, path, *, body, auth):
        calls.append(body["request_id"])
        outcome = outcomes.pop(0)
        if outcome == "pending":
            return {
                "ok": False,
                "error": {
                    "code": "NOUS_APPROVAL_REQUIRED",
                    "message": "approval required",
                    "details": {"approval_request_id": "apr_legacy"},
                },
            }
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "rank": 1,
                        "title": "Evidence",
                        "url": "https://example.com/",
                        "snippet": "Verified",
                    }
                ]
            },
        }

    monkeypatch.setattr("nous_runtime.api.routes.route_server", route_server)

    pending = tools.handle_web_search({"query": "same query"}, {}, lambda _: ("", 0))
    approved_retry = tools.handle_web_search({"query": "same query"}, {}, lambda _: ("", 0))
    later_run = tools.handle_web_search({"query": "same query"}, {}, lambda _: ("", 0))

    assert pending.status == "awaiting_confirmation"
    assert approved_retry.status == "done"
    assert later_run.status == "done"
    assert calls[0] == calls[1]
    assert calls[2] != calls[1]
    assert tools._legacy_search_pending_ids == {}
# -*- coding: utf-8 -*-
"""API contract and approval-lifecycle tests for research evidence."""

from __future__ import annotations

from nous_runtime.api import routes
from nous_runtime.api.research_routes import RESEARCH_GOVERNANCE, RESEARCH_ROUTES
from nous_runtime.events import EventStream
from nous_runtime.evidence.service import network_run_id, parse_search_results
from nous_runtime.evidence.web_gateway import WebGateway, _TransportResponse
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.gate import ExecutionAuthorizationGate
from nous_runtime.governance.store import GovernanceStore


def test_research_routes_and_governance_contract_are_registered():
    assert ("GET", "/api/v1/research/network/status") in RESEARCH_ROUTES
    assert ("GET", "/api/v1/research/sources") in RESEARCH_ROUTES
    assert ("GET", "/api/v1/research/sources/{source_id}") in RESEARCH_ROUTES
    assert ("POST", "/api/v1/research/search") in RESEARCH_ROUTES
    assert RESEARCH_GOVERNANCE[("POST", "/api/v1/research/search")] == (
        "network.fetch",
        "external_write",
        "irreversible",
    )
    assert RESEARCH_GOVERNANCE[("POST", "/api/v1/research/fetch")] == (
        "network.fetch",
        "external_write",
        "irreversible",
    )


def test_research_fetch_requires_approval_then_records_complete_evidence_chain(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("NOUS_API_TOKEN", "research-test-token")
    monkeypatch.setenv("NOUS_API_SUBJECT", "research-owner")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))

    store = GovernanceStore(tmp_path / "governance")
    broker = ApprovalBroker(store=store)
    gate = ExecutionAuthorizationGate(store=store)
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setattr("nous_runtime.governance.broker.get_broker", lambda: broker)
    monkeypatch.setattr(
        WebGateway,
        "_resolve_public_addresses",
        staticmethod(lambda _host, _port: ["93.184.216.34"]),
    )
    monkeypatch.setattr(
        WebGateway,
        "_open_once",
        lambda self, method, url, headers, body, timeout, max_bytes, resolved_ip: _TransportResponse(
            200,
            {"content-type": "text/html"},
            b"<html><title>Research proof</title><body>verified</body></html>",
        ),
    )

    request = {
        "request_id": "api-research-approval",
        "method": "GET",
        "url": "https://example.com/proof?token=must-not-persist",
        "max_response_bytes": 4096,
    }
    first = routes.route_server(
        "POST",
        "/api/v1/research/fetch",
        body=request,
        auth={"token": "research-test-token", "loopback": True},
    )

    assert first["ok"] is False
    assert first["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    details = first["error"]["details"]
    assert details["approval_request_id"].startswith("apr_")
    assert details["run_id"] == network_run_id(request)

    broker.approve(details["approval_request_id"], approver_id="desktop-confirmation")
    completed = routes.route_server(
        "POST",
        "/api/v1/research/fetch",
        body=request,
        auth={"token": "research-test-token", "loopback": True},
    )

    assert completed["ok"] is True, completed
    result = completed["data"]
    assert result["source_id"]
    assert result["snapshot_id"]
    assert result["snapshot_artifact_id"]
    assert result["run_id"] == details["run_id"]
    assert "must-not-persist" not in result["url"]
    assert "must-not-persist" not in result["final_url"]

    event_types = [
        event.event_type
        for event in EventStream(str(tmp_path)).load_events(details["run_id"])
    ]
    for expected in (
        "network.requested",
        "network.approval_required",
        "network.approved",
        "network.connected",
        "network.response_received",
        "network.snapshot_created",
        "artifact.created",
        "network.completed",
        "run.completed",
    ):
        assert expected in event_types

    listed = routes.route_server(
        "GET",
        "/api/v1/research/sources",
        auth={"token": "research-test-token", "loopback": True},
    )
    assert listed["ok"] is True
    assert listed["data"]["total"] == 1
    assert listed["data"]["sources"][0]["source_id"] == result["source_id"]

    secret = b"must-not-persist"
    leaked_paths = [
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
        if path.is_file() and secret in path.read_bytes()
    ]
    assert leaked_paths == []


def test_research_source_detail_is_not_fabricated(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))

    missing = routes.route("GET", "/api/v1/research/sources/src_missing")

    assert missing["ok"] is False
    assert missing["error"]["code"] == "NOUS_NOT_FOUND"

def test_search_parser_decodes_redirects_deduplicates_and_preserves_snippets():
    content = """
    <html><body>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Example <b>A</b></a>
      <div class="result__snippet">First <em>verified</em> snippet.</div>
      <a class="result__a" href="https://example.com/a">Duplicate</a>
      <div class="result__snippet">Duplicate snippet.</div>
      <a class="result__a" href="javascript:alert(1)">Unsafe</a>
      <a class="result__a" href="https://example.org/b">Example B</a>
      <a class="result__snippet">Second snippet.</a>
    </body></html>
    """

    results = parse_search_results(content, limit=10)

    assert results == [
        {
            "rank": 1,
            "url": "https://example.com/a",
            "title": "Example A",
            "snippet": "First verified snippet.",
        },
        {
            "rank": 2,
            "url": "https://example.org/b",
            "title": "Example B",
            "snippet": "Second snippet.",
        },
    ]


def test_research_search_uses_same_approval_and_returns_structured_citation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("NOUS_API_TOKEN", "search-test-token")
    monkeypatch.setenv("NOUS_API_SUBJECT", "search-owner")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))

    store = GovernanceStore(tmp_path / "governance")
    broker = ApprovalBroker(store=store)
    gate = ExecutionAuthorizationGate(store=store)
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setattr("nous_runtime.governance.broker.get_broker", lambda: broker)
    monkeypatch.setattr(
        WebGateway,
        "_resolve_public_addresses",
        staticmethod(lambda _host, _port: ["52.142.124.215"]),
    )

    search_html = b"""
    <html><title>Bing Search</title><body><ol>
      <li class="b_algo"><h2><a href="https://example.com/proof">Verified <strong>proof</strong></a></h2>
      <div class="b_caption"><p>Evidence-ready <em>result</em>.</p></div></li>
    </ol></body></html>
    """

    def open_search(self, method, url, headers, body, timeout, max_bytes, resolved_ip):
        assert method == "GET"
        assert url == "https://www.bing.com/search?q=governed+evidence"
        assert headers["Accept-Language"].startswith("zh-CN")
        assert body == b""
        return _TransportResponse(200, {"content-type": "text/html"}, search_html)

    monkeypatch.setattr(WebGateway, "_open_once", open_search)
    request = {
        "request_id": "api-search-approval",
        "query": "governed evidence",
        "max_results": 5,
    }

    first = routes.route_server(
        "POST",
        "/api/v1/research/search",
        body=request,
        auth={"token": "search-test-token", "loopback": True},
    )
    assert first["ok"] is False
    assert first["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    details = first["error"]["details"]

    broker.approve(details["approval_request_id"], approver_id="desktop-confirmation")
    completed = routes.route_server(
        "POST",
        "/api/v1/research/search",
        body=request,
        auth={"token": "search-test-token", "loopback": True},
    )

    assert completed["ok"] is True, completed
    result = completed["data"]
    assert result["results"] == [
        {
            "rank": 1,
            "url": "https://example.com/proof",
            "title": "Verified proof",
            "snippet": "Evidence-ready result.",
        }
    ]
    evidence = result["search_evidence"]
    citation = evidence["citation"]
    assert citation["source_id"] == evidence["source_id"]
    assert citation["content_hash"] == evidence["content_hash"]
    assert citation["snapshot_artifact_id"] == evidence["snapshot_artifact_id"]
    assert citation["url"] == "https://www.bing.com/search?q=%3Credacted%3E"
    assert citation["retrieved_at"]
    assert "retrieved" in citation["formatted"]

    source_detail = routes.route_server(
        "GET",
        "/api/v1/research/sources/" + evidence["source_id"],
        auth={"token": "search-test-token", "loopback": True},
    )
    assert source_detail["data"]["citation"] == citation

    serialized_events = "\n".join(
        str(event.payload)
        for event in EventStream(str(tmp_path)).load_events(details["run_id"])
    )
    assert "governed evidence" not in serialized_events
    assert "q=governed" not in serialized_events

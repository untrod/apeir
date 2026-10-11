"""Task views must preserve authoritative evidence and its scope."""

import pytest

from nous_runtime.api.task_center_routes import (
    handle_task_artifacts,
    handle_task_timeline,
    handle_task_verification,
)
from nous_runtime.events import EventStream, RunEvent


def test_timeline_preserves_persisted_payload_and_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    stream = EventStream(str(tmp_path))
    stream.create_run("run_evidence", task_id="task_evidence")
    emitted = stream.emit(
        RunEvent(
            run_id="run_evidence",
            task_id="task_evidence",
            event_type="artifact.created",
            actor="runtime",
            payload={"artifact_id": "artifact_original", "integrity": "MATCH"},
        )
    )
    events = handle_task_timeline("run_evidence")["data"]["events"]
    event = next(item for item in events if item["event_type"] == emitted.event_type)
    assert event["data"] == emitted.payload
    assert event["event_id"] == emitted.event_id
    assert event["run_id"] == emitted.run_id
    assert handle_task_timeline("task_evidence")["data"]["events"] == events
    assert handle_task_timeline()["data"]["events"] == events


def test_evaluation_pass_is_not_effect_verification(tmp_path, monkeypatch):
    from nous_runtime.evaluation.history import EvaluationHistory
    from nous_runtime.evaluation.models import EvaluationRecord

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    history = EvaluationHistory(tmp_path)
    assert history.save(
        EvaluationRecord(
            target_type="task", target_id="task_score", status="pass", composite_score=1
        )
    )
    result = handle_task_verification("task_score")["data"]
    assert result["evaluation"]["passed"] is True
    assert result["verified"] is False
    assert result["evaluation"]["score"] == 1
    assert result["verdict"] == "UNKNOWN"
    assert result["committed"] is False


def test_task_artifacts_use_registered_metadata(tmp_path, monkeypatch):
    from nous_runtime.artifact import Artifact, ArtifactRegistry

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    artifact = Artifact(name="result.txt", type="file", metadata={"task_id": "task_1"})
    ArtifactRegistry(tmp_path / ".nous" / "artifacts.jsonl").register(artifact)
    artifacts = handle_task_artifacts("task_1")["data"]["artifacts"]
    assert artifacts[0]["id"] == artifact.id
    assert handle_task_artifacts("task_other")["data"]["artifacts"] == []


def test_public_task_route_preserves_durable_work_and_legacy_pagination(
    tmp_path, monkeypatch
):
    from nous_runtime.api.routes import route_server
    from nous_runtime.task import cli
    from nous_runtime.work import WorkHarness

    class NoKernelTasks:
        def list(self, state=None):
            return []

    monkeypatch.setattr(cli, "get_task_manager", lambda: NoKernelTasks())
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.work.view")
    harness = WorkHarness(tmp_path)
    first = harness.create("Review the first file")
    second = harness.create("Review the second file")
    auth = {"headers": {"Authorization": "Bearer fake.work.view"}}
    response = route_server("GET", "/api/v1/tasks", params={"page_size": 1}, auth=auth)
    assert response["ok"], response
    data = response["data"]
    assert data["total"] == data["pagination"]["total"] == 2
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_kind"] == "work"
    assert data["pagination"]["has_next"] is True
    other = route_server(
        "GET", "/api/v1/tasks", params={"page": 2, "page_size": 1}, auth=auth
    )["data"]
    assert {data["tasks"][0]["task_id"], other["tasks"][0]["task_id"]} == {
        first.run_id,
        second.run_id,
    }


def test_cas_artifact_lookup_is_authenticated_and_checks_bytes(tmp_path, monkeypatch):
    from nous_runtime.api.routes import handle_global_search, route_server
    from nous_runtime.artifact import ContentAddressedArtifactStore

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.evidence.service")
    store = ContentAddressedArtifactStore(tmp_path / ".nous" / "relay" / "artifacts")
    stored = store.store_bytes(
        b"original output",
        artifact_type="file",
        name="wiring-evidence-result.txt",
        metadata={"work_id": "work_1"},
    )
    digest = stored["artifact"]["digest"]
    params = {"artifact_id": digest}
    denied = route_server("GET", "/api/v1/artifacts", params=params)
    assert denied["error"]["code"] == "NOUS_UNAUTHENTICATED"
    auth = {"headers": {"Authorization": "Bearer " + "fake.evidence.service"}}
    original = route_server("GET", "/api/v1/artifacts", params=params, auth=auth)
    assert original["data"]["integrity"] == "MATCH"
    assert original["data"]["effect_verification_performed"] is False
    search = handle_global_search("wiring-evidence-result", scope="artifacts")
    assert digest in {item["id"] for item in search["data"]["results"]}
    assert handle_task_artifacts("work_1")["data"]["artifacts"][0]["digest"] == digest
    store.resolve(digest).write_bytes(b"tampered output")
    mismatch = route_server("GET", "/api/v1/artifacts", params=params, auth=auth)
    assert mismatch["data"]["integrity"] == "MISMATCH"
    assert mismatch["data"]["effect_verification_performed"] is False
    absent = route_server(
        "GET",
        "/api/v1/artifacts",
        params={"artifact_id": "sha256:" + "b" * 64},
        auth=auth,
    )
    assert absent["error"]["code"] == "NOUS_NOT_FOUND"


def test_unavailable_store_does_not_report_verified_or_empty_success(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    relay = tmp_path / ".nous" / "relay"
    relay.mkdir(parents=True)
    (relay / "distributed-works.json").write_text("{broken")
    result = handle_task_verification("work_unknown")
    assert result["ok"] is False
    assert result["error"]["code"] == "TASK_VERIFICATION_ERROR"


@pytest.mark.integration
def test_http_reads_original_evidence_after_lost_response_recovery(
    tmp_path, monkeypatch
):
    import json
    import threading
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
    from nous_runtime.governance.cli import _build_context
    from nous_runtime.reality.preview import run_verified_demo

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.evidence.http")
    demo = run_verified_demo(
        tmp_path, scenario="lost-response", approval_context=_build_context()
    )
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"

        def read(path):
            request = Request(
                base + path, headers={"Authorization": "Bearer fake.evidence.http"}
            )
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
            assert result["ok"], result
            return result["data"]

        work_id = demo["work"]["work_id"]
        verification = read(f"/api/v1/tasks/{work_id}/verification")
        assert verification["effect_verification"] == demo["effect_verification"]
        assert verification["committed"] is True
        artifacts = read(f"/api/v1/tasks/{work_id}/artifacts")["artifacts"]
        assert artifacts
        for artifact in artifacts:
            digest = artifact["digest"]
            details = read("/api/v1/artifacts?" + urlencode({"artifact_id": digest}))
            assert details["integrity"] == "MATCH"
            assert details["effect_verification_performed"] is False
        assert demo["effect_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.integration
@pytest.mark.parametrize(
    "scenario,verdict,verified",
    [
        ("match", "MATCH", True),
        ("mismatch", "MISMATCH", False),
        ("unknown", "UNKNOWN", False),
        ("lost-response", "MATCH", True),
        ("restart", "MATCH", True),
        ("deny", "UNKNOWN", False),
    ],
)
def test_task_verification_reads_original_reality_evidence(
    tmp_path, monkeypatch, scenario, verdict, verified
):
    from nous_runtime.governance.cli import _build_context
    from nous_runtime.reality.preview import run_verified_demo

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    demo = run_verified_demo(
        tmp_path, scenario=scenario, approval_context=_build_context()
    )
    result = handle_task_verification(demo["work"]["work_id"])["data"]
    assert result["verdict"] == verdict
    assert result["verified"] is verified
    assert result["committed"] is verified
    assert result["effect_verification"] == demo["effect_verification"]
    assert demo["effect_count"] == (0 if scenario == "deny" else 1)

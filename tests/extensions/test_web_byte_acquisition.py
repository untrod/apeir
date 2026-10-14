"""Acquisition-only responses retain untrusted bytes without Research disclosure."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from nous_runtime.artifact import ArtifactManager, ArtifactRegistry
from nous_runtime.events import EventStream
from nous_runtime.evidence import SnapshotStore, SourceRegistry
from nous_runtime.evidence.web_gateway import WebGateway, WebRequest

FAKE_SECRET = "apeir.test.only.transient.byte.secret"


@pytest.mark.parametrize(
    "content_type", ["application/json", "text/html", "application/zip", FAKE_SECRET]
)
def test_configured_evidence_stores_do_not_publish_acquisition_body(
    tmp_path, content_type
):
    if content_type == "application/zip":
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("SKILL.md", FAKE_SECRET)
        body = output.getvalue()
    elif content_type == "application/json":
        body = json.dumps({"title": FAKE_SECRET}).encode()
    else:
        body = f"<title>{FAKE_SECRET}</title><p>untrusted instructions</p>".encode()
    snapshots = SnapshotStore(tmp_path / "snapshots")
    sources = SourceRegistry(tmp_path / "sources.json")
    artifacts = ArtifactManager(ArtifactRegistry(tmp_path / "artifacts.jsonl"))
    events = EventStream(str(tmp_path))
    gateway = WebGateway(
        snapshot_store=snapshots,
        source_registry=sources,
        artifact_manager=artifacts,
        event_stream=events,
        resolver=lambda *_: ["8.8.8.8"],
        transport=lambda **_: SimpleNamespace(
            status_code=200,
            headers={"content-type": content_type, "etag": FAKE_SECRET},
            body=body,
        ),
    )
    result = gateway.fetch_bytes(
        WebRequest(
            url="https://catalog.example.test/package", run_id="byte-acquisition"
        )
    )
    assert result.response.ok and result.body == body
    assert result.acquisition_only and result.content_trust == "untrusted"
    assert (
        result.response.content == "" and result.response.injection_scan_result is None
    )
    assert (
        not result.response.source_id
        and not result.response.snapshot_id
        and not result.response.snapshot_artifact_id
    )
    assert sources.count() == 0 and snapshots.list() == [] and artifacts.list() == []
    metadata = json.dumps(result.to_dict())
    recorded = json.dumps(
        [event.to_dict() for event in events.load_events(result.response.run_id)]
    )
    assert FAKE_SECRET not in metadata and FAKE_SECRET not in recorded
    assert "body" not in result.to_dict() and result.response.response_headers == {}
    assert not {"network.snapshot_created", "artifact.created"} & {
        event.event_type for event in events.load_events(result.response.run_id)
    }
    assert all(
        FAKE_SECRET.encode() not in path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )


def test_text_fetch_still_publishes_original_research_evidence_after_byte_fetch(
    tmp_path,
):
    snapshots = SnapshotStore(tmp_path / "snapshots")
    sources = SourceRegistry(tmp_path / "sources.json")
    artifacts = ArtifactManager(ArtifactRegistry(tmp_path / "artifacts.jsonl"))
    body = b"<title>Public fixture title</title><p>public fixture content</p>"
    gateway = WebGateway(
        snapshot_store=snapshots,
        source_registry=sources,
        artifact_manager=artifacts,
        resolver=lambda *_: ["8.8.8.8"],
        transport=lambda **_: SimpleNamespace(
            status_code=200, headers={"content-type": "text/html"}, body=body
        ),
    )
    acquired = gateway.fetch_bytes(
        WebRequest(url="https://catalog.example.test/public")
    )
    assert acquired.body == body and sources.count() == 0
    response = gateway.fetch(WebRequest(url="https://catalog.example.test/public"))
    assert response.ok and "public fixture content" in response.content
    assert response.source_id and response.snapshot_id and response.snapshot_artifact_id
    assert (
        sources.count() == 1
        and len(snapshots.list()) == 1
        and len(artifacts.list()) == 1
    )
    snapshot = snapshots.list()[0]
    assert Path(snapshot.storage_path).read_bytes() == body


def test_byte_acquisition_keeps_cancellation_before_transport():
    calls = []
    gateway = WebGateway(
        resolver=lambda *_: ["8.8.8.8"], transport=lambda **kw: calls.append(kw)
    )
    result = gateway.fetch_bytes(
        WebRequest(
            url="https://catalog.example.test/package", cancel_check=lambda: True
        )
    )
    assert result.response.error_code == "NETWORK_CANCELLED"
    assert result.body == b"" and calls == []

from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest

from nous_runtime.api import routes
from nous_runtime.documents import DocumentIR, DocumentRuntime, DocumentValidationError
from nous_runtime.documents.verification import DocumentVerificationError, verify_docx, verify_pdf
from nous_runtime.events import EventStream


def _ir(title: str = "Nous Professional Document") -> dict:
    return {
        "title": title,
        "subtitle": "A render-verified P17 artifact",
        "author": "Nous Runtime",
        "blocks": [
            {"kind": "heading", "level": 1, "text": "Executive summary"},
            {"kind": "paragraph", "text": "Document IR produces governed professional artifacts."},
            {"kind": "bullet_list", "items": ["Bounded input", "Atomic output", "Structural verification"]},
            {"kind": "table", "rows": [["Format", "State"], ["DOCX", "verified"], ["PDF", "verified"]]},
            {"kind": "code", "language": "python", "text": "print('Nous')"},
            {"kind": "citation", "text": "Nous internal evidence", "source_id": "src_test"},
        ],
    }


def test_document_ir_rejects_unbounded_or_malformed_content():
    with pytest.raises(DocumentValidationError, match="blocks"):
        DocumentIR.from_mapping({"title": "Empty", "blocks": []}, new_identity=True)
    with pytest.raises(DocumentValidationError, match="heading level"):
        DocumentIR.from_mapping({"title": "Bad", "blocks": [{"kind": "heading", "level": 9, "text": "Bad"}]}, new_identity=True)
    with pytest.raises(DocumentValidationError, match="same number"):
        DocumentIR.from_mapping({"title": "Bad", "blocks": [{"kind": "table", "rows": [["a"], ["b", "c"]]}]}, new_identity=True)


def test_document_create_persists_digest_artifact_and_event_chain(tmp_path):
    runtime = DocumentRuntime(tmp_path)
    created = runtime.create(_ir())
    reconstructed = DocumentRuntime(tmp_path).get(created["document_id"])

    assert reconstructed["sha256"] == created["sha256"]
    assert created["artifact_id"].startswith("artifact_")
    events = EventStream(str(tmp_path)).load_events(created["run_id"])
    assert [event.event_type for event in events] == [
        "run.created", "command.proposed", "run.started", "document.created", "artifact.created", "run.completed",
    ]


def test_document_render_reopens_verifies_registers_and_survives_restart(tmp_path):
    runtime = DocumentRuntime(tmp_path)
    created = runtime.create(_ir())
    result = DocumentRuntime(tmp_path).render(created["document_id"], ["docx", "pdf"])

    assert result["verified"] is True
    assert {item["format"] for item in result["outputs"]} == {"docx", "pdf"}
    for output in result["outputs"]:
        assert (tmp_path / output["location"]).is_file()
        assert output["artifact_id"].startswith("artifact_")
        assert output["checks"]
    events = EventStream(str(tmp_path)).load_events(result["run_id"])
    assert [event.event_type for event in events].count("document.verified") == 2
    assert events[-1].event_type == "run.completed"


def test_document_ir_tamper_fails_closed(tmp_path):
    runtime = DocumentRuntime(tmp_path)
    created = runtime.create(_ir())
    path = tmp_path / ".nous" / "documents" / f"{created['document_id']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["title"] = "Tampered"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(DocumentValidationError, match="digest mismatch"):
        DocumentRuntime(tmp_path).get(created["document_id"])


def test_docx_verifier_rejects_external_relationship_and_traversal(tmp_path):
    document = DocumentIR.from_mapping(_ir(), new_identity=True)
    external = tmp_path / "external.docx"
    relationships = b'''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="x" Target="https://example.test" TargetMode="External"/></Relationships>'''
    with zipfile.ZipFile(external, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/styles.xml", "<styles/>")
        archive.writestr("word/document.xml", f"<document>{document.title}</document>")
        archive.writestr("word/_rels/document.xml.rels", relationships)
    with pytest.raises(DocumentVerificationError, match="external relationship"):
        verify_docx(external, document)

    traversal = tmp_path / "traversal.docx"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", "bad")
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/styles.xml", "<styles/>")
        archive.writestr("word/document.xml", f"<document>{document.title}</document>")
    with pytest.raises(DocumentVerificationError, match="unsafe ZIP path"):
        verify_docx(traversal, document)


def test_pdf_verifier_rejects_active_content(tmp_path):
    runtime = DocumentRuntime(tmp_path)
    created = runtime.create(_ir())
    result = runtime.render(created["document_id"], ["pdf"])
    source = tmp_path / result["outputs"][0]["location"]
    malicious = tmp_path / "active.pdf"
    data = source.read_bytes().replace(b"%%EOF", b"/JavaScript /JS (bad)\n%%EOF")
    malicious.write_bytes(data)

    document = DocumentIR.from_mapping(runtime.get(created["document_id"]))
    with pytest.raises(DocumentVerificationError, match="active content"):
        verify_pdf(malicious, document)


def test_failed_render_never_publishes_unverified_output(tmp_path, monkeypatch):
    runtime = DocumentRuntime(tmp_path)
    created = runtime.create(_ir("Fail closed"))

    def invalid_pdf(_document, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"not a pdf")

    monkeypatch.setattr("nous_runtime.documents.service.render_pdf", invalid_pdf)
    with pytest.raises(DocumentVerificationError):
        runtime.render(created["document_id"], ["pdf"])

    assert not list((tmp_path / "artifacts" / "documents").glob("*.pdf"))
    assert not list((tmp_path / "artifacts" / "documents").glob(".*.pdf"))
    failed = [run for run in EventStream(str(tmp_path)).list_runs() if run.task_id.startswith("document.render")][0]
    events = EventStream(str(tmp_path)).load_events(failed.run_id)
    assert [event.event_type for event in events][-2:] == ["document.failed", "run.failed"]

def test_document_routes_are_governed_before_handler(monkeypatch, tmp_path):
    captured = {}

    class Gate:
        def evaluate(self, proposal, context):
            captured["proposal"] = proposal
            return SimpleNamespace(
                action_mode="ASK_APPROVAL", rule_class="USER_APPROVABLE",
                reason_code="APPROVAL_REQUIRED", reason_message="Approval required",
                decision_id="decision-document",
            )

    monkeypatch.setenv("NOUS_API_TOKEN", "secret")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: Gate())

    response = routes.route_server(
        "POST", "/api/v1/documents", body=_ir(),
        auth={"token": "secret", "loopback": True},
    )

    assert response["error"]["code"] == "NOUS_APPROVAL_REQUIRED"
    assert captured["proposal"].capability_id == "document.create"
    assert captured["proposal"].side_effect_class == "local_write"
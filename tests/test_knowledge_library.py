from __future__ import annotations

import pytest

from nous_runtime.knowledge import KnowledgeLibraryService


def test_import_duplicate_modified_and_citation(tmp_path):
    service = KnowledgeLibraryService(tmp_path / "runtime")
    library = service.create("workspace-a", "user-a", "Docs")
    source = tmp_path / "guide.md"
    source.write_text("Nous Runtime provides governed execution and recovery.", encoding="utf-8")
    first = service.import_file(library.library_id, source, workspace_id="workspace-a", owner_id="user-a")
    unchanged = service.import_file(library.library_id, source, workspace_id="workspace-a", owner_id="user-a")
    assert first["status"] == "imported" and unchanged["status"] == "unchanged"
    source.write_text("Nous Runtime provides governed execution, evaluation, and recovery.", encoding="utf-8")
    modified = service.import_file(library.library_id, source, workspace_id="workspace-a", owner_id="user-a")
    assert modified["status"] == "modified"
    results = service.search(library.library_id, "evaluation recovery", workspace_id="workspace-a", owner_id="user-a")
    assert results and results[0].logical_source == "guide.md"
    assert results[0].library_id == library.library_id
    assert results[0].document_id == modified["document_id"]
    assert results[0].chunk_id and results[0].index_generation


def test_identical_content_different_path_is_deduplicated(tmp_path):
    service = KnowledgeLibraryService(tmp_path / "runtime")
    library = service.create("workspace", "user", "Docs")
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("identical public fixture", encoding="utf-8")
    second.write_text("identical public fixture", encoding="utf-8")
    service.import_file(library.library_id, first, workspace_id="workspace", owner_id="user")
    duplicate = service.import_file(library.library_id, second, workspace_id="workspace", owner_id="user")
    assert duplicate["status"] == "duplicate" and duplicate["duplicate_of"]
    assert len(service.search(library.library_id, "identical", workspace_id="workspace", owner_id="user")) == 1


def test_delete_promotes_duplicate_on_rebuild(tmp_path):
    service = KnowledgeLibraryService(tmp_path / "runtime")
    library = service.create("workspace", "user", "Docs")
    for name in ("a.txt", "b.txt"):
        path = tmp_path / name
        path.write_text("shared recovery content", encoding="utf-8")
        service.import_file(library.library_id, path, workspace_id="workspace", owner_id="user")
    assert service.delete_document(library.library_id, "a.txt", workspace_id="workspace", owner_id="user")
    results = service.search(library.library_id, "recovery", workspace_id="workspace", owner_id="user")
    assert results and results[0].logical_source == "b.txt"


def test_library_and_workspace_isolation_fail_closed(tmp_path):
    service = KnowledgeLibraryService(tmp_path / "runtime")
    library = service.create("workspace-a", "user-a", "Private")
    source = tmp_path / "private.txt"
    source.write_text("private workspace fact", encoding="utf-8")
    service.import_file(library.library_id, source, workspace_id="workspace-a", owner_id="user-a")
    with pytest.raises(PermissionError):
        service.search(library.library_id, "private", workspace_id="workspace-b", owner_id="user-a")
    with pytest.raises(PermissionError):
        service.search(library.library_id, "private", workspace_id="workspace-a", owner_id="user-b")


def test_rebuild_recovers_missing_generation_and_uses_no_embedding_provider(tmp_path):
    service = KnowledgeLibraryService(tmp_path / "runtime")
    library = service.create("workspace", "user", "Docs")
    source = tmp_path / "rebuild.txt"
    source.write_text("rebuild index recovery", encoding="utf-8")
    imported = service.import_file(library.library_id, source, workspace_id="workspace", owner_id="user")
    service.backend.clear_generation(imported["generation"])
    assert service.search(library.library_id, "recovery", workspace_id="workspace", owner_id="user") == []
    generation = service.rebuild(library.library_id, workspace_id="workspace", owner_id="user")
    results = service.search(library.library_id, "recovery", workspace_id="workspace", owner_id="user")
    assert results and results[0].index_generation == generation


def test_export_import_round_trip(tmp_path):
    service = KnowledgeLibraryService(tmp_path / "runtime")
    library = service.create("workspace", "user", "Docs")
    source = tmp_path / "export.md"
    source.write_text("portable knowledge content", encoding="utf-8")
    service.import_file(library.library_id, source, workspace_id="workspace", owner_id="user")
    exported = service.export(library.library_id, workspace_id="workspace", owner_id="user")
    restored = service.import_export(exported, workspace_id="workspace-2", owner_id="user-2")
    results = service.search(restored.library_id, "portable", workspace_id="workspace-2", owner_id="user-2")
    assert results and results[0].logical_source == "export.md"
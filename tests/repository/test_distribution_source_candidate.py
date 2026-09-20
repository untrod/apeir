from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prepare_distribution_candidate import create_candidate


def test_candidate_excludes_private_generated_and_repository_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "candidate"
    (source / "nous_runtime").mkdir(parents=True)
    (source / "docs" / "archive").mkdir(parents=True)
    (source / "intelligence" / "manifests").mkdir(parents=True)
    (source / ".git").mkdir()
    (source / "logs").mkdir()
    (source / "README.md").write_text("APEIR\n", encoding="utf-8")
    (source / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    (source / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    (source / "nous_runtime" / "runtime.py").write_text("pass\n", encoding="utf-8")
    (source / "nous_runtime" / "state.db").write_bytes(b"db")
    (source / "docs" / "archive" / "gate.md").write_text("old\n", encoding="utf-8")
    (source / ".git" / "config").write_text("private\n", encoding="utf-8")
    (source / "logs" / "runtime.log").write_text("private\n", encoding="utf-8")
    (source / "workspace.json").write_text(
        '{"artifact_directory":"C:/Users/example/private"}\n', encoding="utf-8"
    )
    (source / "intelligence" / "manifests" / "store.json").write_text(
        '{"host":"private-host","pid":123}\n', encoding="utf-8"
    )

    manifest = create_candidate(source, destination)

    paths = {str(item["path"]) for item in manifest}
    assert paths == {".env.example", "README.md", "nous_runtime/runtime.py"}
    assert not (destination / ".git").exists()
    assert not (destination / ".env").exists()
    assert not (destination / "nous_runtime" / "state.db").exists()
    assert not (destination / "workspace.json").exists()
    assert not (destination / "intelligence" / "manifests" / "store.json").exists()


def test_candidate_never_overwrites_an_existing_review(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "candidate"
    source.mkdir()
    destination.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        create_candidate(source, destination)

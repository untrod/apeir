from pathlib import Path

from scripts import markdown_link_check


def test_local_link_targets_are_checked(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "guide.md"
    target.parent.mkdir()
    target.write_text("# Guide\n", encoding="utf-8")
    source = tmp_path / "README.md"
    source.write_text("[guide](docs/guide.md)\n[missing](docs/missing.md)\n", encoding="utf-8")

    findings = markdown_link_check.check_file(source, tmp_path)

    assert len(findings) == 1
    assert "missing local target" in findings[0]


def test_external_anchor_and_fenced_links_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text(
        "[web](https://example.com)\n[section](#section)\n```text\n[old](missing.md)\n```\n",
        encoding="utf-8",
    )

    assert markdown_link_check.check_file(source, tmp_path) == []


def test_repository_check_excludes_historical_archive(tmp_path: Path) -> None:
    archive = tmp_path / "docs" / "archive"
    archive.mkdir(parents=True)
    (archive / "old.md").write_text("[missing](gone.md)\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Current\n", encoding="utf-8")

    count, findings = markdown_link_check.check_repository(tmp_path)

    assert count == 1
    assert findings == []

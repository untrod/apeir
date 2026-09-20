"""Test public document boundaries and private-data exclusions."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PRIVATE_DOC_PATTERNS = [
    re.compile(r"F:\\Nous_Public", re.IGNORECASE),
    re.compile(r"F:\\Agent_play", re.IGNORECASE),
    re.compile(r"Co-authored-by:\s*(?:Claude|Codex|AI|ChatGPT)", re.IGNORECASE),
    re.compile(r"Generated\s+by\s+(?:Claude|Codex)", re.IGNORECASE),
]

PUBLIC_DOC_DIRS = [
    "docs/architecture", "docs/specs", "docs/development", "docs/user",
    "docs/security", "docs/protocol", "docs/release", "docs/rfc",
    "spec/", "README.md", "CHANGELOG.md", "ROADMAP.md", "CONTRIBUTING.md",
    "SECURITY.md", "CODE_OF_CONDUCT.md", "MAINTAINERS.md",
]


def is_public_doc(filepath: Path) -> bool:
    """Determine if a document is in the public documentation tree."""
    rel = str(filepath.relative_to(REPO_ROOT)).replace("\\", "/")
    return any(rel.startswith(d) for d in PUBLIC_DOC_DIRS)


def collect_public_docs() -> list[Path]:
    """Collect all markdown files in public documentation directories."""
    docs = []
    for pattern in PUBLIC_DOC_DIRS:
        path = REPO_ROOT / pattern
        if path.is_file() and path.suffix == ".md":
            docs.append(path)
        elif path.is_dir():
            docs.extend(path.rglob("*.md"))
    return sorted(set(docs))


@pytest.mark.parametrize("docpath", collect_public_docs())
def test_public_doc_no_private_data(docpath: Path):
    """Public documentation must not contain private paths or AI attribution."""
    try:
        content = docpath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return  # Skip unreadable files

    for pattern in PRIVATE_DOC_PATTERNS:
        match = pattern.search(content)
        assert not match, (
            f"Public document {docpath.relative_to(REPO_ROOT)} contains private data: "
            f"'{match.group()}'"
        )


def test_no_ai_process_files_in_docs():
    """Docs directory should not contain AI process/execution reports."""
    ai_process_indicators = [
        "task book", "execution report", "claude code executed",
        "automated task completed", "AI progress report",
    ]
    docs_dir = REPO_ROOT / "docs"
    for md_file in docs_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            continue
        for indicator in ai_process_indicators:
            assert indicator not in content, (
                f"Document {md_file.relative_to(REPO_ROOT)} appears to be an AI process file "
                f"(contains '{indicator}') and should be moved to .audit/"
            )

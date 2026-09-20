from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_nous_runtime_legacy_imports_are_isolated_to_compat():
    findings: list[str] = []
    for path in (REPO_ROOT / "nous_runtime").rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[:2] == ("nous_runtime", "compat"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "remote_terminal.nous_core" in line:
                findings.append(f"{rel}:{lineno}: {line.strip()}")

    assert findings == []


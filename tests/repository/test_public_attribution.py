"""Test public attribution hygiene — no AI author identities in commits.

Part of the RC9 repository hygiene suite.
"""

import subprocess

import pytest

AI_IDENTITY_PATTERNS = [
    "claude", "codex", "chatgpt", "openai", "anthropic bot",
    "ai assistant", "ai agent", "noreply@anthropic", "noreply@openai",
]

# Historical commits are immutable release evidence.  New commits after this
# repository-hygiene baseline must use human contributor identities only.
ATTRIBUTION_BASELINE = "7c8afa6"


def get_git_log() -> list[dict]:
    """Get all commits with author, committer, and trailers."""
    result = subprocess.run(
        [
            "git",
            "log",
            f"{ATTRIBUTION_BASELINE}..HEAD",
            "--format=%H|%an|%ae|%cn|%ce|%s||%b",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    commits = []
    for entry in result.stdout.split("\n||\n"):
        if "|" not in entry:
            continue
        parts = entry.split("|", 5)
        if len(parts) >= 6:
            commits.append({
                "sha": parts[0],
                "author": parts[1],
                "author_email": parts[2],
                "committer": parts[3],
                "committer_email": parts[4],
                "subject": parts[5].split("\n")[0] if parts[5] else "",
                "body": parts[5] if parts[5] else "",
            })
    return commits


@pytest.mark.parametrize("pattern", AI_IDENTITY_PATTERNS)
def test_no_ai_author_identities(pattern: str):
    """No commit should have an AI author or committer identity."""
    commits = get_git_log()
    for c in commits:
        author_field = f"{c['author']} <{c['author_email']}>".lower()
        committer_field = f"{c['committer']} <{c['committer_email']}>".lower()
        assert pattern not in author_field, (
            f"Commit {c['sha'][:8]} has AI author identity matching '{pattern}': "
            f"{c['author']} <{c['author_email']}>"
        )
        assert pattern not in committer_field, (
            f"Commit {c['sha'][:8]} has AI committer identity matching '{pattern}': "
            f"{c['committer']} <{c['committer_email']}>"
        )


def test_no_ai_co_authored_by():
    """No commit should have an AI Co-authored-by trailer."""
    commits = get_git_log()
    for c in commits:
        for line in c["body"].lower().split("\n"):
            if "co-authored-by:" in line:
                for pattern in AI_IDENTITY_PATTERNS:
                    assert pattern not in line, (
                        f"Commit {c['sha'][:8]} has AI co-author: {line.strip()}"
                    )

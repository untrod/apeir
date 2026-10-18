"""Selection is conservative; critical changes never fall into a docs gate."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.test_scope import classify, comparison_base


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["nous_runtime/governance/gate.py"],
        ["nous_runtime/kernel/runtime.py"],
        ["tests/governance/test_operation_core.py"],
        [".github/workflows/core-ci.yml"],
        ["sdk/provider/python/nous_provider/runtime.py"],
        ["pyproject.toml"],
        ["unknown.md"],
        ["examples/hello_skill/verified-device-review/SKILL.md"],
        ["examples/unknown/README.md"],
        ["docs/script.py"],
        ["docs/../nous_runtime/node_runtime/service.py"],
        ["/docs/foo.md"],
        ["docs\\foo.md"],
        ["README.md", "nous_runtime/reality/execution.py"],
    ],
)
def test_critical_unknown_and_mixed_changes_require_full(paths):
    assert classify(paths, event="pull_request") == "full"


def test_docs_only_is_narrow_and_non_pr_events_force_full():
    paths = [
        "README.md",
        "ROADMAP.md",
        "docs/architecture/DISTRIBUTION.md",
        "examples/README.md",
        "examples/hello_runtime/README.md",
    ]
    assert classify(paths, event="pull_request") == "documentation"
    for event in ("push", "workflow_dispatch", "release", "unknown"):
        assert classify(paths, event=event) == "full"


def test_renamed_critical_file_is_not_hidden(tmp_path):
    repo = tmp_path / "git"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True)

    git("init")
    git("config", "user.name", "Preview test")
    git("config", "user.email", "test@example.invalid")
    (repo / "runtime.py").write_text("dangerous changes must be tested\n")
    git("add", ".")
    git("commit", "-m", "base")
    (repo / "docs").mkdir()
    git("mv", "runtime.py", "docs/runtime.md")
    git("commit", "-m", "rename")
    script = Path(__file__).resolve().parents[2] / "scripts/ci/test_scope.py"
    result = subprocess.run(
        [sys.executable, str(script), "--base", "HEAD^", "--event", "pull_request"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "full"


def test_manual_formatting_covers_earlier_branch_commits(tmp_path, monkeypatch):
    repo = tmp_path / "git"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], text=True
        ).strip()

    git("init", "-q")
    git("config", "user.name", "Preview test")
    git("config", "user.email", "test@example.invalid")
    source = repo / "runtime.py"
    source.write_text("value = 1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    original = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", original)
    source.write_text("value = 2\n")
    git("commit", "-qam", "implementation")
    (repo / "README.md").write_text("documentation follows implementation\n")
    git("add", ".")
    git("commit", "-qm", "docs")
    monkeypatch.chdir(repo)
    for supplied in ("", "0" * 40):
        base = comparison_base(supplied)
        assert base == original
        assert "runtime.py" in git("diff", "--name-only", base, "HEAD").splitlines()
    assert "runtime.py" not in git("diff", "--name-only", "HEAD^", "HEAD")
    assert comparison_base("HEAD^") == "HEAD^"
    git("update-ref", "-d", "refs/remotes/origin/main")
    with pytest.raises(subprocess.CalledProcessError):
        comparison_base()


def test_comparison_base_rejects_git_options():
    with pytest.raises(ValueError, match="explicit Git revisions"):
        comparison_base("--help")

"""Selection is conservative; critical changes never fall into a docs gate."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.test_scope import classify


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

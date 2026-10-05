"""Test branch naming compliance for public repository.

Part of the RC9 repository hygiene suite.
"""

import subprocess
import sys

import pytest

FORBIDDEN_PREFIXES = [
    "codex/",
    "claude/",
    "gpt/",
    "ai/",
    "agent/",
    "auto-generated/",
]


def get_branches() -> list[str]:
    """Get all local and remote branch names."""
    result = subprocess.run(
        ["git", "branch", "-a"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    branches = []
    for line in result.stdout.strip().split("\n"):
        branch = line.strip().lstrip("*").strip()
        if branch and "->" not in branch:
            # Extract short name (remove remotes/origin/)
            short = branch.replace("remotes/origin/", "")
            branches.append(short)
    return branches


@pytest.mark.parametrize("branch", get_branches())
def test_branch_naming_compliance(branch: str):
    """No branch should use forbidden AI-tool prefixes."""
    for prefix in FORBIDDEN_PREFIXES:
        assert not branch.startswith(prefix), (
            f"Branch '{branch}' uses forbidden prefix '{prefix}'. "
            f"Rename to use allowed prefixes: feature/, fix/, refactor/, "
            f"docs/, test/, release/, kernel/, platform/, provider/, research/, archive/"
        )


if __name__ == "__main__":
    branches = get_branches()
    violations = [
        b for b in branches if any(b.startswith(p) for p in FORBIDDEN_PREFIXES)
    ]
    if violations:
        print(f"FAIL: {len(violations)} branches with forbidden prefixes:")
        for v in violations:
            print(f"  - {v}")
        sys.exit(1)
    print("PASS: All branch names are compliant.")


def _metadata_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Maintainer",
            "-c",
            "user.email=maintainer@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return repo


def test_metadata_audit_accepts_detached_github_pr_checkout(tmp_path):
    from scripts.git_metadata_audit import check_branches

    repo = _metadata_repo(tmp_path)
    for ref in [
        "refs/remotes/pull/42/merge",
        "refs/remotes/pull/42/head",
        "refs/remotes/origin/main",
    ]:
        subprocess.run(["git", "-C", str(repo), "update-ref", ref, "HEAD"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/main",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "--detach"],
        check=True,
        capture_output=True,
    )
    assert check_branches(repo) == []


@pytest.mark.parametrize(
    "ref,issue",
    [
        ("refs/heads/pull/42/merge", "non_standard_prefix"),
        ("refs/remotes/origin/codex/authority", "forbidden_prefix"),
        ("refs/remotes/upstream/ai/authority", "forbidden_prefix"),
        ("refs/remotes/pull/not-number/merge", "non_standard_prefix"),
        ("refs/remotes/pull/42/authority", "non_standard_prefix"),
        ("refs/heads/main-shadow", "non_standard_prefix"),
    ],
)
def test_metadata_audit_rejects_disguised_or_forbidden_branches(tmp_path, ref, issue):
    from scripts.git_metadata_audit import check_branches

    repo = _metadata_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "update-ref", ref, "HEAD"], check=True)
    findings = check_branches(repo)
    assert len(findings) == 1
    assert findings[0]["branch"] == ref
    assert findings[0]["issue"] == issue


def test_metadata_audit_accepts_hardware_and_named_remote_work(tmp_path):
    from scripts.git_metadata_audit import check_branches

    repo = _metadata_repo(tmp_path)
    for ref in [
        "refs/heads/hardware/m5-real-acceptance",
        "refs/remotes/upstream/feature/m4-interoperability",
    ]:
        subprocess.run(["git", "-C", str(repo), "update-ref", ref, "HEAD"], check=True)
    assert check_branches(repo) == []


def test_metadata_audit_does_not_hide_symbolic_contributor_branch(tmp_path):
    from scripts.git_metadata_audit import check_branches

    repo = _metadata_repo(tmp_path)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "symbolic-ref",
            "refs/heads/ai/authority",
            "refs/heads/main",
        ],
        check=True,
    )
    findings = check_branches(repo)
    assert len(findings) == 1
    assert findings[0]["issue"] == "forbidden_prefix"


def test_metadata_audit_git_command_failure_cannot_report_success(tmp_path):
    from scripts.git_metadata_audit import run_git

    repo = _metadata_repo(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        run_git(repo, "not-a-git-command")

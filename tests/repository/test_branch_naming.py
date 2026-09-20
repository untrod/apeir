"""Test branch naming compliance for public repository.

Part of the RC9 repository hygiene suite.
"""

import subprocess
import sys

import pytest

FORBIDDEN_PREFIXES = [
    "claude/", "gpt/", "ai/", "agent/", "auto-generated/",
]


def get_branches() -> list[str]:
    """Get all local and remote branch names."""
    result = subprocess.run(
        ["git", "branch", "-a"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
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
    violations = [b for b in branches if any(b.startswith(p) for p in FORBIDDEN_PREFIXES)]
    if violations:
        print(f"FAIL: {len(violations)} branches with forbidden prefixes:")
        for v in violations:
            print(f"  - {v}")
        sys.exit(1)
    print("PASS: All branch names are compliant.")

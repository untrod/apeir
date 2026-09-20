#!/usr/bin/env python3
"""Git metadata audit — checks author/committer identity and branch naming.

Part of the RC9 repository hygiene suite.
Run: python scripts/git_metadata_audit.py [--repo PATH]

Checks:
  1. Branch naming compliance (no codex/, claude/, gpt/, ai/, agent/, auto-generated/ prefixes)
  2. Author/committer identity consistency
  3. AI bot identities in git history
  4. Co-authored-by trailer hygiene
"""

import argparse
import subprocess
import sys
from pathlib import Path

FORBIDDEN_BRANCH_PREFIXES = [
    "claude/", "gpt/", "ai/", "agent/", "auto-generated/",
]

ALLOWED_BRANCH_PREFIXES = [
    "feature/", "fix/", "refactor/", "docs/", "test/", "release/",
    "kernel/", "platform/", "provider/", "research/", "archive/",
    "codex/",
    "main", "master", "develop",
]

AI_BOT_PATTERNS = [
    "claude", "codex", "chatgpt", "gpt", "openai bot", "anthropic bot",
    "noreply@anthropic", "noreply@openai", "ai assistant", "ai agent",
]

SUSPICIOUS_EMAILS = [
    "bot@", "ai@", "temp@", "test@",
]


def run_git(repo: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def check_branches(repo: Path) -> list[dict]:
    """Check all branches for naming compliance."""
    violations = []
    branches = run_git(repo, "branch", "-a").split("\n")
    for branch_line in branches:
        # Clean up the branch name format
        branch = branch_line.strip().lstrip("*").strip()
        if not branch or "->" in branch:
            continue
        # Extract short name
        short = branch.replace("remotes/origin/", "")

        is_compliant = any(
            short == prefix.rstrip("/") or short.startswith(prefix)
            for prefix in ALLOWED_BRANCH_PREFIXES
        )

        is_forbidden = any(
            short.startswith(prefix) for prefix in FORBIDDEN_BRANCH_PREFIXES
        )

        if is_forbidden:
            violations.append({
                "branch": branch,
                "short": short,
                "issue": "forbidden_prefix",
                "recommendation": f"Rename to follow allowed prefixes: {', '.join(ALLOWED_BRANCH_PREFIXES[:6])}",
            })
        elif not is_compliant:
            violations.append({
                "branch": branch,
                "short": short,
                "issue": "non_standard_prefix",
                "recommendation": "Review and rename if needed",
            })

    return violations


def check_authors(repo: Path) -> list[dict]:
    """Check git log for AI bot identities and suspicious emails."""
    violations = []
    log = run_git(repo, "log", "--all", "--format=%H|%an|%ae|%cn|%ce|%s")

    for line in log.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue

        sha, author, author_email, committer, committer_email, subject = parts

        # Check author name
        for pattern in AI_BOT_PATTERNS:
            if pattern in author.lower():
                violations.append({
                    "sha": sha[:8],
                    "field": "author",
                    "value": author,
                    "issue": f"Potential AI bot identity: matches '{pattern}'",
                })
                break

        # Check committer name
        for pattern in AI_BOT_PATTERNS:
            if pattern in committer.lower():
                violations.append({
                    "sha": sha[:8],
                    "field": "committer",
                    "value": committer,
                    "issue": f"Potential AI bot identity: matches '{pattern}'",
                })
                break

        # Check emails
        for email_pattern in SUSPICIOUS_EMAILS:
            if email_pattern in author_email.lower():
                violations.append({
                    "sha": sha[:8],
                    "field": "author_email",
                    "value": author_email,
                    "issue": f"Suspicious email pattern: '{email_pattern}'",
                })
            if email_pattern in committer_email.lower():
                violations.append({
                    "sha": sha[:8],
                    "field": "committer_email",
                    "value": committer_email,
                    "issue": f"Suspicious email pattern: '{email_pattern}'",
                })

    return violations


def check_co_authored(repo: Path) -> list[dict]:
    """Check for AI Co-authored-by trailers."""
    violations = []
    log = run_git(repo, "log", "--all", "--format=%H|%B")

    for entry in log.split("\n\n"):
        if "|" not in entry:
            continue
        sha, body = entry.split("|", 1)

        for line in body.split("\n"):
            line_lower = line.strip().lower()
            if "co-authored-by:" in line_lower:
                for pattern in AI_BOT_PATTERNS:
                    if pattern in line_lower:
                        violations.append({
                            "sha": sha[:8],
                            "field": "co-authored-by",
                            "value": line.strip(),
                            "issue": f"AI co-author trailer matches '{pattern}'",
                        })
                        break

    return violations


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Audit git metadata for public release readiness")
    parser.add_argument("--repo", default=".", help="Path to git repository")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repository")
        return 2

    branch_violations = check_branches(repo)
    author_violations = check_authors(repo)
    coauthor_violations = check_co_authored(repo)

    all_violations = branch_violations + author_violations + coauthor_violations

    if args.json:
        import json
        print(json.dumps({
            "branches": branch_violations,
            "authors": author_violations,
            "co_authors": coauthor_violations,
        }, indent=2, ensure_ascii=False))
    else:
        if not all_violations:
            print("PASS: Git metadata is clean for public release.")
            return 0

        print(f"Found {len(all_violations)} git metadata issues:\n")

        if branch_violations:
            print(f"--- Branch Naming Violations ({len(branch_violations)}) ---")
            for v in branch_violations:
                print(f"  {v['branch']}: {v['issue']}")
                print(f"    → {v['recommendation']}")

        if author_violations:
            print(f"\n--- Author/Committer Issues ({len(author_violations)}) ---")
            for v in author_violations:
                print(f"  {v['sha']} {v['field']}={v['value']}: {v['issue']}")

        if coauthor_violations:
            print(f"\n--- Co-authored-by Issues ({len(coauthor_violations)}) ---")
            for v in coauthor_violations:
                print(f"  {v['sha']}: {v['value']}")

        return 1


if __name__ == "__main__":
    sys.exit(main())

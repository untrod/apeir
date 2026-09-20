#!/usr/bin/env python3
"""Open-source security scanner for APEIR Distribution.

Scans the repository for high-risk patterns: API keys, tokens, passwords,
private keys, personal paths, and private network addresses.

Usage:
    python scripts/security_scan.py          # scan repo, exit 1 if high-risk found
    python scripts/security_scan.py --json   # machine-readable output
    python scripts/security_scan.py --quiet  # only print findings

Exit codes:
    0 — clean (no high-risk findings)
    1 — high-risk findings detected
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Repository root
REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories to exclude
EXCLUDE_DIRS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".audit",
    ".local-archive",
    ".ruff_cache",
    ".mypy_cache",
    ".claude",
    ".agents",
    ".idea",
    ".apeir",
    ".nous",
    "Nous_Release_Test2",
    "htmlcov",
    "artifacts",
    "backups",
    "server_backup",
    "data",
    "sessions",
    "learn_docs",
    "vector_data",
    "target",
    ".gradle",
    ".kotlin",
    "tmp",
    "temp",
}

# File extensions to skip (binaries, large artifacts)
SKIP_EXTENSIONS: set[str] = {
    ".pyc", ".pyo", ".pyd",
    ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".wav", ".mp3", ".mp4", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".db", ".sqlite", ".sqlite3",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".apk", ".aab",
    ".obj", ".o", ".lib",
    ".lock",
    ".log",
}

# Allowlist: files or patterns known safe
# (file_path_relative, line_substring) pairs that are false positives
ALLOWLIST: set[tuple[str, str]] = set()

# Files that are explicitly allowed to contain "sensitive-seeming" patterns
# because they are security documentation, test files, or this scanner itself
ALLOWLIST_FILES: set[str] = {
    "scripts/security_scan.py",           # this file
    "tests/test_open_source_hygiene.py",  # hygiene tests
    "SECURITY.md",                        # security policy
}


def _is_excluded(rel_path: str) -> bool:
    """Check if a relative path should be excluded from scanning."""
    parts = Path(rel_path).parts
    for part in parts:
        if part in EXCLUDE_DIRS or part.startswith(".pytest"):
            return True
    ext = Path(rel_path).suffix.lower()
    if ext in SKIP_EXTENSIONS:
        return True
    return False


def _is_allowlisted(rel_path: str, line: str) -> bool:
    """Check if a specific finding is allowlisted."""
    # Normalize path separators for cross-platform comparison
    normalized = rel_path.replace("\\", "/")
    if normalized in ALLOWLIST_FILES:
        return True
    if _is_test_source(rel_path) and "security-scan: fixture" in line:
        return True
    if (rel_path, line.strip()) in ALLOWLIST:
        return True
    return False


def _is_test_source(rel_path: str) -> bool:
    """Return whether *rel_path* is a conventional test fixture source."""
    path = Path(rel_path)
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return bool(
        parts.intersection({"test", "tests", "__tests__"})
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


# Pattern definitions

# High-risk: real credential patterns
HIGH_RISK_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    # API key prefixes
    ("sk- key prefix", "HIGH", re.compile(r'sk-[a-zA-Z0-9]{20,}', re.IGNORECASE)),
    ("GitHub PAT", "HIGH", re.compile(r'ghp_[a-zA-Z0-9]{36}')),
    ("GitHub PAT (new)", "HIGH", re.compile(r'github_pat_[a-zA-Z0-9_]{20,}')),
    ("AWS access key", "HIGH", re.compile(r'AKIA[0-9A-Z]{16}')),
    ("GCP API key", "HIGH", re.compile(r'AIza[0-9A-Za-z\-_]{35}')),
    # Private keys
    ("PEM private key", "HIGH", re.compile(r'-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----')),
    # Generic assignments with "obviously real" values
    ("Hardcoded password", "HIGH", re.compile(r'(password|passwd|pwd)\s*[:=]\s*["\'](?!\s*$)(?!example)(?!test)(?!changeme)(?!placeholder)(?!your_)(?!YOUR_)[^"\']+["\']', re.IGNORECASE)),
]

# Medium-risk: patterns that need review
MEDIUM_RISK_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    # Sensitive field assignments with non-placeholder values
    ("api_key assignment", "MEDIUM", re.compile(r'(?<![A-Za-z0-9_"\'])\b(api[_-]?key|apikey)\b\s*[:=]\s*["\'](?!\s*$)(?!example)(?!test)(?!your_)(?!sk-)(?!\$)(?!{)[^"\']+["\']', re.IGNORECASE)),
    ("token assignment", "MEDIUM", re.compile(r'(?<![A-Za-z0-9_"\'])\b(access[_-]?token|refresh[_-]?token|auth[_-]?token)\b\s*[:=]\s*["\'](?!\s*$)(?!example)(?!test)(?!your_)(?!\$)(?!{)[^"\']+["\']', re.IGNORECASE)),
    ("secret assignment", "MEDIUM", re.compile(r'(?<![A-Za-z0-9_"\'])\b(secret|client[_-]?secret)\b\s*[:=]\s*["\'](?!\s*$)(?!example)(?!test)(?!your_)(?!\$)(?!{)[^"\']+["\']', re.IGNORECASE)),
    ("authorization header", "MEDIUM", re.compile(r'(?<![A-Za-z0-9_])\bAuthorization\b\s*[:=]\s*["\'](?:Bearer|Basic)\s+(?![\$<{])[^"\']+["\']', re.IGNORECASE)),
    ("bearer token", "MEDIUM", re.compile(r'bearer\s+[a-zA-Z0-9_\-\.]{20,}', re.IGNORECASE)),
    ("private_key assignment", "MEDIUM", re.compile(r'private[_-]?key\s*[:=]\s*["\'](?!\s*$)(?!example)(?!your_)(?!YOUR_)(?!\$)(?!{)[^"\']+["\']', re.IGNORECASE)),
]

# Personal path patterns
PATH_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("Windows absolute path (F:)", "HIGH", re.compile(r'(?<![A-Za-z0-9_])F:[/\\]Agent_play', re.IGNORECASE)),
    ("Windows absolute path (D:)", "HIGH", re.compile(r'(?<![A-Za-z0-9_])D:[/\\]', re.IGNORECASE)),
    ("Windows Users path", "MEDIUM", re.compile(r'C:\\Users\\[^\\]+', re.IGNORECASE)),
    ("Unix home path", "MEDIUM", re.compile(r'/home/[^/\s"\'<]+', re.IGNORECASE)),
    ("macOS Users path", "MEDIUM", re.compile(r'/Users/[^/\s"\'<]+', re.IGNORECASE)),
    ("Known test user", "HIGH", re.compile(r'Nous_Test_User', re.IGNORECASE)),
]

# Private network patterns
NETWORK_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("Private IP 192.168.x.x", "MEDIUM", re.compile(r'192\.168\.\d{1,3}\.\d{1,3}')),
    ("Private IP 10.x.x.x", "MEDIUM", re.compile(r'10\.\d{1,3}\.\d{1,3}\.\d{1,3}')),
    ("Private IP 172.16-31.x.x", "MEDIUM", re.compile(r'172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}')),
]


def scan_file(file_path: Path) -> list[dict[str, Any]]:
    """Scan a single file and return findings."""
    findings: list[dict[str, Any]] = []
    rel_path = str(file_path.relative_to(REPO_ROOT))

    if _is_excluded(rel_path):
        return findings

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return findings

    lines = content.split("\n")

    all_patterns = HIGH_RISK_PATTERNS + MEDIUM_RISK_PATTERNS + PATH_PATTERNS + NETWORK_PATTERNS
    path_pattern_names = {name for name, _severity, _pattern in PATH_PATTERNS}

    for line_num, line in enumerate(lines, start=1):
        for name, severity, pattern in all_patterns:
            if pattern.search(line):
                # Absolute paths are legitimate test data in portability tests.
                # Credential patterns remain active for test sources.
                if name in path_pattern_names and _is_test_source(rel_path):
                    continue
                if _is_allowlisted(rel_path, line):
                    continue
                findings.append({
                    "file": rel_path,
                    "line": line_num,
                    # Never echo a matching source line. A security scanner may
                    # itself become a credential-disclosure path in terminals,
                    # CI logs, or archived JSON evidence.
                    "content": "[redacted]",
                    "pattern": name,
                    "severity": severity,
                })

    return findings


def scan_repository() -> dict[str, Any]:
    """Scan the entire repository and return results."""
    all_findings: list[dict[str, Any]] = []
    files_scanned = 0

    for root, dirs, files in os.walk(REPO_ROOT):
        # Filter excluded directories in-place
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for filename in files:
            file_path = Path(root) / filename
            rel = str(file_path.relative_to(REPO_ROOT))
            if _is_excluded(rel):
                continue
            files_scanned += 1
            findings = scan_file(file_path)
            all_findings.extend(findings)

    # Categorize
    high = [f for f in all_findings if f["severity"] == "HIGH"]
    medium = [f for f in all_findings if f["severity"] == "MEDIUM"]

    return {
        "files_scanned": files_scanned,
        "total_findings": len(all_findings),
        "high_risk": len(high),
        "medium_risk": len(medium),
        "findings": all_findings,
    }


def format_finding(f: dict[str, Any]) -> str:
    """Format a single finding for display."""
    return f"[{f['severity']}] {f['pattern']}: {f['file']}:{f['line']}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="APEIR Distribution security scanner")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--quiet", action="store_true", help="Only print findings, no summary")
    args = parser.parse_args()

    results = scan_repository()

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if results["findings"]:
            for f in results["findings"]:
                print(format_finding(f))
        if not args.quiet:
            print("\n-- Scan Summary --")
            print(f"  Files scanned : {results['files_scanned']}")
            print(f"  Total findings: {results['total_findings']}")
            print(f"  HIGH risk     : {results['high_risk']}")
            print(f"  MEDIUM risk   : {results['medium_risk']}")

    # Exit 1 if high-risk findings exist
    if results["high_risk"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

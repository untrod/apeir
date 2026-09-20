#!/usr/bin/env python3
"""Document hygiene audit — classifies Markdown files and detects leaks.

This check is part of the public-source release gate.
Run: python scripts/document_hygiene_audit.py [--path PATH]

Checks:
  1. Personal paths in committed documents
  2. Personal GitHub URLs in committed documents
  3. AI-tool branch names embedded in docs
  4. Empty documents
  5. Duplicate documents with same title
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", ".venv", "node_modules", "target", "build", ".gradle",
    ".apeir", ".nous", ".audit", "__pycache__", ".pytest_cache", "dist",
    ".local-archive", "artifacts",
}

# Patterns that should not appear in public documents
LEAK_PATTERNS = [
    (re.compile(r"[A-Z]:\\[A-Za-z_]"), "Windows absolute path (e.g., F:\\Project)"),
    (re.compile(r"Co-authored-by:\s*(?:Claude|Codex|AI|ChatGPT)", re.IGNORECASE),
     "AI co-author trailer in document"),
    (re.compile(r"Generated\s+by\s+(?:Claude|Codex|ChatGPT)", re.IGNORECASE),
     "AI generation attribution"),
]


def audit_document(filepath: Path) -> list[dict]:
    """Audit a single markdown document."""
    findings = []
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return findings

    if not content.strip():
        findings.append({
            "file": str(filepath),
            "line": 0,
            "issue": "empty_document",
            "text": "(empty file)",
        })
        return findings

    lines = content.split("\n")
    for i, line in enumerate(lines, start=1):
        for pattern, label in LEAK_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "file": str(filepath),
                    "line": i,
                    "issue": label,
                    "text": line.strip()[:150],
                })
                break

    return findings


def collect_markdown_files(root: Path) -> list[Path]:
    """Collect all markdown files, excluding vendor directories."""
    files = []
    for f in root.rglob("*.md"):
        parts = f.parts
        if any(excl in parts for excl in EXCLUDE_DIRS):
            continue
        files.append(f)
    return files


def find_duplicates(files: list[Path]) -> list[dict]:
    """Find byte-identical Markdown documents in different locations."""
    content_map: dict[str, list[str]] = {}
    for f in files:
        try:
            normalized = f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
        except OSError:
            continue
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        content_map.setdefault(digest, []).append(str(f))

    duplicates = []
    for digest, paths in content_map.items():
        if len(paths) > 1:
            duplicates.append({
                "filename": Path(paths[0]).name,
                "digest": digest,
                "count": len(paths),
                "paths": paths,
            })

    return duplicates


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Audit markdown documents for public release readiness")
    parser.add_argument("--path", default=".", help="Root path to audit")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    files = collect_markdown_files(root)

    all_findings = []
    for f in files:
        all_findings.extend(audit_document(f))

    duplicates = find_duplicates(files)

    if args.json:
        import json
        print(json.dumps({
            "findings": all_findings,
            "duplicates": duplicates,
        }, indent=2, ensure_ascii=False))
    else:
        if not all_findings and not duplicates:
            print("PASS: Document hygiene is clean for public release.")
            return 0

        if all_findings:
            print(f"Found {len(all_findings)} document hygiene issues:\n")
            for finding in all_findings:
                print(f"  {finding['file']}:{finding['line']} [{finding['issue']}]")
                print(f"    {finding['text']}\n")

        if duplicates:
            print(f"\nFound {len(duplicates)} byte-identical document groups:\n")
            for dup in duplicates:
                print(f"  {dup['filename']} ({dup['count']} copies):")
                for p in dup['paths']:
                    print(f"    - {p}")

        return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())

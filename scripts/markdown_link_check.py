#!/usr/bin/env python3
"""Validate local links in current APEIR Distribution Markdown files."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {
    ".apeir",
    ".audit",
    ".git",
    ".nous",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "node_modules",
    "target",
}
ARCHIVE_ROOT = Path("docs/archive")
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")


def _markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, names in os.walk(root):
        directories[:] = [name for name in directories if name not in EXCLUDE_DIRS]
        current_path = Path(current)
        try:
            relative = current_path.relative_to(root)
        except ValueError:
            continue
        if relative == ARCHIVE_ROOT or ARCHIVE_ROOT in relative.parents:
            directories[:] = []
            continue
        files.extend(current_path / name for name in names if name.lower().endswith(".md"))
    return sorted(files)


def _target_text(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1:value.index(">")]
    return value.split(maxsplit=1)[0]


def _has_exact_case(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        try:
            names = {child.name for child in current.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        current /= part
    return True


def check_file(path: Path, root: Path = REPO_ROOT) -> list[str]:
    findings: list[str] = []
    in_fence = False
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in LINK_PATTERN.finditer(line):
            target = unquote(_target_text(match.group(1)))
            if not target or target.startswith("#"):
                continue
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith(("mailto:", "//")):
                continue
            local_text = parsed.path.replace("/", os.sep)
            if not local_text or Path(local_text).is_absolute():
                continue
            resolved = (path.parent / local_text).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                findings.append(f"{path.relative_to(root)}:{line_number}: link escapes repository: {target}")
                continue
            if not resolved.exists():
                findings.append(f"{path.relative_to(root)}:{line_number}: missing local target: {target}")
            elif not _has_exact_case(resolved, root.resolve()):
                findings.append(f"{path.relative_to(root)}:{line_number}: path case mismatch: {target}")
    return findings


def check_repository(root: Path = REPO_ROOT) -> tuple[int, list[str]]:
    files = _markdown_files(root.resolve())
    findings = [finding for path in files for finding in check_file(path, root.resolve())]
    return len(files), findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=str(REPO_ROOT))
    args = parser.parse_args()
    count, findings = check_repository(Path(args.path))
    for finding in findings:
        print(finding)
    if findings:
        print(f"FAIL: {len(findings)} broken local links across {count} current Markdown files.")
        return 1
    print(f"PASS: {count} current Markdown files have valid local link targets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

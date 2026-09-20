#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Propagate the canonical version to all project manifests.

Reads `nous_runtime/_version.py` as the single source of truth and
updates every manifest file that carries an independent version string:
pyproject.toml, package.json, Cargo.toml, tauri.conf.json, etc.

Usage:
    python tools/freeze_version.py           # dry-run (show diffs)
    python tools/freeze_version.py --apply   # write changes
    python tools/freeze_version.py --check   # exit 1 if any mismatch
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Read canonical version

def _read_canonical() -> str:
    version_py = ROOT / "nous_runtime" / "_version.py"
    content = version_py.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not m:
        sys.exit(f"ERROR: cannot parse __version__ from {version_py}")
    return m.group(1)


CANONICAL = _read_canonical()

# Manifest descriptors

# Each entry: (path, getter, setter)
# getter reads current version; setter writes new version
MANIFESTS: list[dict] = []


def _register_json(path: str, *keys: str):
    """Register a JSON manifest where version is at nested keys."""
    full = ROOT / path

    def getter():
        if not full.exists():
            return None
        data = json.loads(full.read_text(encoding="utf-8"))
        for k in keys[:-1]:
            data = data.get(k, {})
        return data.get(keys[-1])

    def setter():
        if not full.exists():
            print(f"  SKIP (not found): {path}")
            return
        data = json.loads(full.read_text(encoding="utf-8"))
        target = data
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        old = target.get(keys[-1])
        target[keys[-1]] = CANONICAL
        full.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  UPDATE {path}: {old} → {CANONICAL}")

    MANIFESTS.append({"path": path, "getter": getter, "setter": setter})


def _register_regex(path: str, pattern: str, replacement_tmpl: str):
    """Register a file where version is matched by regex."""
    full = ROOT / path

    def getter():
        if not full.exists():
            return None
        content = full.read_text(encoding="utf-8")
        m = re.search(pattern, content)
        return m.group(1) if m else None

    def setter():
        if not full.exists():
            print(f"  SKIP (not found): {path}")
            return
        content = full.read_text(encoding="utf-8")
        old = getter()
        new_content = re.sub(pattern, replacement_tmpl.format(version=CANONICAL), content, count=1)
        full.write_text(new_content, encoding="utf-8")
        print(f"  UPDATE {path}: {old} → {CANONICAL}")

    MANIFESTS.append({"path": path, "getter": getter, "setter": setter})


# Register all manifests

# Python package
_register_regex(
    "pyproject.toml",
    r'^version\s*=\s*"([^"]+)"',
    'version = "{version}"',
)

# Desktop app
_register_json("desktop/package.json", "version")
_register_regex(
    "desktop/src-tauri/Cargo.toml",
    r'^version\s*=\s*"([^"]+)"',
    'version = "{version}"',
)
_register_json("desktop/src-tauri/tauri.conf.json", "package", "version")

# VS Code extension
_register_json("ide/vscode/package.json", "version")

# TypeScript SDK
_register_json("nous_runtime/sdk/package.json", "version")

# API server version header
_register_regex(
    "nous_runtime/api/server.py",
    r'server_version\s*=\s*"([^"]+)"',
    'server_version = "NousRuntimeAPI/1.0"',
)

# SDK client version defaults (TypeScript)
_register_regex(
    "nous_runtime/sdk/client.ts",
    r'version:\s*"([^"]+)"',
    'version: "{version}"',
)

# SDK client version defaults (Python)
_register_regex(
    "nous_runtime/sdk/client.py",
    r'DEFAULT_VERSION\s*=\s*"([^"]+)"',
    'DEFAULT_VERSION = "{version}"',
)


# Commands

def cmd_check() -> int:
    """Check all manifests match canonical. Exit 1 on mismatch."""
    mismatches = 0
    for m in MANIFESTS:
        current = m["getter"]()
        if current is None:
            print(f"  MISSING: {m['path']}")
            mismatches += 1
        elif current != CANONICAL:
            print(f"  MISMATCH: {m['path']}: {current} ≠ {CANONICAL}")
            mismatches += 1
        else:
            print(f"  OK: {m['path']}: {current}")
    if mismatches:
        print(f"\n{mismatches} manifest(s) out of sync with canonical version {CANONICAL}")
        return 1
    print(f"\nAll manifests in sync with canonical version {CANONICAL}")
    return 0


def cmd_apply() -> int:
    """Write canonical version to all manifests."""
    print(f"Propagating canonical version {CANONICAL} to all manifests...\n")
    for m in MANIFESTS:
        m["setter"]()
    print("\nDone. Run `python tools/freeze_version.py --check` to verify.")
    return 0


def cmd_dry_run() -> int:
    """Show what would change without writing."""
    print(f"Dry-run: canonical version = {CANONICAL}\n")
    mismatches = 0
    for m in MANIFESTS:
        current = m["getter"]()
        if current is None:
            print(f"  MISSING: {m['path']} — would be set to {CANONICAL}")
            mismatches += 1
        elif current != CANONICAL:
            print(f"  DIFF: {m['path']}: {current} → {CANONICAL}")
            mismatches += 1
        else:
            print(f"  OK: {m['path']}: {current}")
    if mismatches:
        print(f"\n{mismatches} manifest(s) would be updated. Run with --apply to write.")
    else:
        print("\nAll manifests already in sync.")
    return 0


# Main

def main():
    if "--check" in sys.argv:
        sys.exit(cmd_check())
    elif "--apply" in sys.argv:
        sys.exit(cmd_apply())
    else:
        sys.exit(cmd_dry_run())


if __name__ == "__main__":
    main()

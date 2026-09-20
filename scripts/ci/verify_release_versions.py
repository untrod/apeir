"""Verify that every release-facing manifest has the same APEIR version."""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

EXPECTED = "0.1.0-rc1"
ROOT = Path(__file__).resolve().parents[2]


def load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


versions = {
    "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
    "desktop/package.json": load_json("desktop/package.json")["version"],
    "desktop/package-lock.json": load_json("desktop/package-lock.json")["version"],
    "desktop/src-tauri/Cargo.toml": tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))["package"]["version"],
    "desktop/src-tauri/tauri.conf.json": load_json("desktop/src-tauri/tauri.conf.json")["version"],
    "nous_runtime/sdk/package.json": load_json("nous_runtime/sdk/package.json")["version"],
    "ide/vscode/package.json": load_json("ide/vscode/package.json")["version"],
}

source = (ROOT / "nous_runtime/_version.py").read_text(encoding="utf-8")
match = re.search(r'^__version__\s*=\s*"([^"]+)"', source, re.MULTILINE)
if not match:
    raise SystemExit("nous_runtime/_version.py does not define __version__")
versions["nous_runtime/_version.py"] = match.group(1)

mismatches = {path: version for path, version in versions.items() if version != EXPECTED}
if mismatches:
    detail = ", ".join(f"{path}={version}" for path, version in mismatches.items())
    raise SystemExit(f"release version mismatch: {detail}")

print(f"Release version consistency: {EXPECTED} ({len(versions)} manifests)")

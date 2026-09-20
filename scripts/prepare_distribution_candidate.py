#!/usr/bin/env python3
"""Create a reviewable APEIR Distribution public-source candidate.

The candidate is copied from the current working tree, not from Git history.
Local state, build output, release evidence, databases, credentials, and old
repository metadata are excluded by construction. The destination must not
already exist, so a previous review can never be overwritten silently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT_FILES = {
    ".env.example", ".gitattributes", ".gitignore", "CHANGELOG.md",
    "CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "Dockerfile", "LICENSE",
    "MAINTAINERS.md", "MANIFEST.in", "NOTICE", "README.md",
    "README.zh-CN.md", "ROADMAP.md", "SECURITY.md", "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    "config.example.json", "deploy.sh", "docker-compose.yml", "install.sh",
    "nous-sidecar.spec", "pyproject.toml", "runtime-components.lock.json",
}

SOURCE_DIRECTORIES = {
    ".github", "benchmarks", "compat", "config", "conformance", "deploy", "desktop",
    "docs", "examples", "hello_pack", "ide", "integrations", "intelligence",
    "micro", "nous_runtime", "nous_workspace", "packs", "remote_terminal",
    "RemoteTerminal", "research", "runtime", "scripts", "sdk", "spec",
    "tasks", "templates", "tests", "tools",
}

EXCLUDED_PARTS = {
    ".agents", ".apeir", ".audit", ".claude", ".codex", ".git", ".gradle",
    ".idea", ".kotlin", ".mypy_cache", ".nous", ".pytest_cache",
    ".ruff_cache", ".venv", "__pycache__", "artifacts", "backups", "build",
    "cache", "checkpoints", "conversations", "data", "dist", "evidence",
    "exports", "htmlcov", "logs", "node_modules", "reports", "server_backup",
    "sessions", "target", "temp", "tmp", "venv",
}

EXCLUDED_PREFIXES = {
    "benchmarks/rc5", "benchmarks/rc9", "benchmarks/rc10",
    "desktop/src-tauri/gen", "docs/archive", "docs/audits",
    "docs/release/evidence", "intelligence/manifests/store.json",
}

EXCLUDED_SUFFIXES = {
    ".7z", ".aab", ".apk", ".bak", ".bin", ".db", ".dll", ".doc",
    ".docx", ".exe", ".gz", ".img", ".lib", ".log", ".obj", ".o",
    ".pdf", ".pem", ".pfx", ".pyd", ".pyc", ".pyo", ".sqlite",
    ".sqlite3", ".tar", ".wav", ".xlsx", ".zip",
}

EXCLUDED_NAMES = {
    "RC3-ARM64-ARTIFACT.json", "SHA256SUMS-arm64.txt", "local.properties",
    "workspace.json",
}


def _excluded(relative: str) -> bool:
    path = Path(relative)
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return True
    if path.name in EXCLUDED_NAMES:
        return True
    if path.name.startswith(".env") and path.name != ".env.example":
        return True
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in EXCLUDED_PREFIXES
    )


def _selected(relative: str) -> bool:
    path = Path(relative)
    if len(path.parts) == 1:
        return path.name in ROOT_FILES
    return path.parts[0] in SOURCE_DIRECTORIES


def create_candidate(source: Path, destination: Path) -> list[dict[str, object]]:
    if destination.exists():
        raise FileExistsError(
            f"destination already exists; choose a new review directory: {destination}"
        )
    destination.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        relative = source_file.relative_to(source).as_posix()
        if not _selected(relative) or _excluded(relative):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target)
        manifest.append({
            "path": relative,
            "size_bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    manifest = create_candidate(source, destination)
    payload = {
        "schema_version": 1,
        "product": "APEIR Distribution",
        "source": str(source),
        "destination": str(destination),
        "file_count": len(manifest),
        "total_bytes": sum(int(item["size_bytes"]) for item in manifest),
        "files": manifest,
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({key: payload[key] for key in ("file_count", "total_bytes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

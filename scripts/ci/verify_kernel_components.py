"""Verify native kernel components against the repository component lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path
from typing import Any


def _load_lock(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported runtime component lock schema")
    component = data.get("components", {}).get("nous-kernel")
    if not isinstance(component, dict):
        raise ValueError("nous-kernel is missing from the component lock")
    if not component.get("revision") or not component.get("artifacts"):
        raise ValueError("nous-kernel revision or artifacts are missing")
    return component


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _pe_machine(path: Path) -> str:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"{path.name} is not a PE executable")
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError(f"{path.name} has an invalid PE header")
        machine = struct.unpack("<H", stream.read(2))[0]
    return f"0x{machine:04X}"


def _git_revision(kernel_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=kernel_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify(
    repo_root: Path, lock_path: Path, kernel_root: Path | None
) -> list[dict[str, Any]]:
    component = _load_lock(lock_path)
    expected_revision = str(component["revision"])
    if kernel_root is not None:
        actual_revision = _git_revision(kernel_root)
        if actual_revision != expected_revision:
            raise ValueError(
                f"kernel revision mismatch: expected {expected_revision}, got {actual_revision}"
            )

    results: list[dict[str, Any]] = []
    for artifact in component["artifacts"]:
        relative = Path(str(artifact["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe component path: {relative}")
        path = repo_root / relative
        if not path.is_file():
            raise FileNotFoundError(
                f"locked kernel component is missing: {relative}. "
                "Stage it from the pinned nous-kernel source before building Desktop."
            )
        actual_hash = _sha256(path)
        expected_hash = str(artifact["sha256"]).upper()
        if actual_hash != expected_hash:
            raise ValueError(
                f"hash mismatch for {relative}: expected {expected_hash}, got {actual_hash}"
            )
        actual_machine = _pe_machine(path)
        expected_machine = str(artifact["pe_machine"]).upper().replace("0X", "0x")
        if actual_machine != expected_machine:
            raise ValueError(
                f"architecture mismatch for {relative}: "
                f"expected {expected_machine}, got {actual_machine}"
            )
        results.append(
            {
                "name": artifact["name"],
                "path": relative.as_posix(),
                "sha256": actual_hash,
                "pe_machine": actual_machine,
            }
        )
    return results


def report_rebuild(
    lock_path: Path, kernel_root: Path, candidate_root: Path
) -> dict[str, Any]:
    """Inspect rebuilt bytes without staging, running, or relocking components."""
    component = _load_lock(lock_path)
    expected_revision = str(component["revision"])
    actual_revision = _git_revision(kernel_root)
    tracked_changes = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=kernel_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    errors: list[str] = []
    if actual_revision != expected_revision:
        errors.append("kernel revision mismatch")
    if tracked_changes:
        errors.append("kernel tracked source is modified")
    results = []
    for artifact in component["artifacts"]:
        name = str(artifact["name"])
        if re.fullmatch(r"[A-Za-z0-9_-]+", name) is None:
            raise ValueError("unsafe component executable name")
        path = candidate_root / f"{name}.exe"
        item: dict[str, Any] = {
            "name": name,
            "expected_sha256": str(artifact["sha256"]).upper(),
            "expected_pe_machine": str(artifact["pe_machine"])
            .upper()
            .replace("0X", "0x"),
            "sha256": None,
            "pe_machine": None,
            "errors": [],
        }
        if not path.is_file() or path.is_symlink():
            item["errors"].append("candidate executable is missing or is a symlink")
        else:
            item["sha256"] = _sha256(path)
            if item["sha256"] != item["expected_sha256"]:
                item["errors"].append("hash mismatch")
            try:
                item["pe_machine"] = _pe_machine(path)
                if item["pe_machine"] != item["expected_pe_machine"]:
                    item["errors"].append("architecture mismatch")
            except (ValueError, OSError, struct.error):
                item["errors"].append("invalid PE executable")
        errors.extend(f"{name}: {error}" for error in item["errors"])
        results.append(item)
    return {
        "status": "BLOCKED" if errors else "MATCH",
        "purpose": "locked Kernel rebuild diagnostic; not release qualification",
        "lock_sha256": _sha256(lock_path),
        "expected_revision": expected_revision,
        "actual_revision": actual_revision,
        "tracked_source_clean": not bool(tracked_changes),
        "target": component.get("target"),
        "declared_protocol": component.get("protocol"),
        "declared_nki_versions": component.get("nki_versions"),
        "runtime_nki_validation": "NOT_RUN",
        "installation_acceptance": "NOT_RUN",
        "artifacts": results,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--kernel-root", type=Path)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    lock_path = (args.lock or repo_root / "runtime-components.lock.json").resolve()
    kernel_root = args.kernel_root.resolve() if args.kernel_root else None
    if args.candidate_root is not None:
        if kernel_root is None or args.report is None:
            parser.error("--candidate-root requires --kernel-root and --report")
        report_path = args.report.resolve()
        if report_path == lock_path or report_path.is_relative_to(kernel_root):
            parser.error(
                "diagnostic report must not modify the lock or Kernel checkout"
            )
        report = report_rebuild(lock_path, kernel_root, args.candidate_root.resolve())
        output = json.dumps(report, indent=2) + "\n"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(output, encoding="utf-8")
        print(output, end="")
        return 2 if report["status"] == "BLOCKED" else 0
    if args.report is not None:
        parser.error("--report requires --candidate-root")
    results = verify(repo_root, lock_path, kernel_root)
    print(json.dumps({"status": "ok", "artifacts": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

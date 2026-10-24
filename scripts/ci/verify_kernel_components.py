"""Verify native kernel components against the repository component lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile
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


def admit_artifact(
    archive: Path,
    archive_sha256: str,
    output: Path,
    lock_path: Path,
    source_revision: str,
    kernel_root: Path | None = None,
) -> dict[str, Any]:
    """Admit one reviewed CI ZIP through the same native hash/PE verifier.

    Archive metadata is evidence, never a replacement for the maintained lock.
    No bytes are published to output until all files and original smoke records
    pass. This function neither changes the lock nor executes an input file.
    """
    if re.fullmatch(r"[0-9a-fA-F]{64}", archive_sha256) is None:
        raise ValueError("reviewed artifact SHA-256 is required")
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("reviewed producer source revision is required")
    if archive.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("native artifact ZIP exceeds size limit")
    if _sha256(archive) != archive_sha256.upper():
        raise ValueError("native artifact ZIP digest mismatch")
    if output.exists() or output.is_symlink():
        raise ValueError("artifact output must not replace an existing directory")
    component = _load_lock(lock_path)
    if component.get("target") != "x86_64-pc-windows-msvc":
        raise ValueError("reviewed ZIP admission currently supports Windows x64 only")
    native_paths = {str(item["path"]) for item in component["artifacts"]}
    for relative in native_paths:
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or "\\" in relative
            or ":" in relative
        ):
            raise ValueError("unsafe locked component path")
    binary_paths = native_paths | {"nous-runtime.exe"}
    allowed = binary_paths | {
        "candidate-manifest.json",
        "original-lock-report.json",
        "build-environment.json",
        "python-dependencies.txt",
        "native-smoke.json",
        "nki-initial.json",
        "nki-recovery.json",
        "nousd-x86_64-pc-windows-msvc-dependencies.txt",
        "nous-provider-worker-x86_64-pc-windows-msvc-dependencies.txt",
        "nous-runtime-dependencies.txt",
        "SHA256SUMS.txt",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="native-admission-", dir=output.parent
    ) as temporary:
        staged = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if (
                len(entries) > 24
                or sum(x.file_size for x in entries) > 512 * 1024 * 1024
            ):
                raise ValueError("native artifact exceeds extraction limits")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("duplicate native artifact entry")
            for entry in entries:
                if (
                    entry.filename not in allowed
                    or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16)
                ):
                    raise ValueError(
                        "unexpected, encrypted or symbolic native artifact entry"
                    )
                if entry.filename not in binary_paths and entry.file_size > 1024 * 1024:
                    raise ValueError("native artifact metadata exceeds size limit")
                destination = staged / entry.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        # Reuse the one canonical component verifier before trusting metadata.
        results = verify(staged, lock_path, kernel_root)
        checksums = {}
        for line in (
            (staged / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines()
        ):
            match = re.fullmatch(r"([0-9A-Fa-f]{64})  (.+)", line)
            if not match or match[2] in checksums:
                raise ValueError("invalid native artifact checksum manifest")
            checksums[match[2]] = match[1].upper()
        if set(checksums) != set(names) - {"SHA256SUMS.txt"}:
            raise ValueError("native artifact checksum coverage is incomplete")
        for relative, expected in checksums.items():
            if _sha256(staged / relative) != expected:
                raise ValueError("native artifact member digest mismatch")

        def document(name):
            path = staged / name
            if path.stat().st_size > 1024 * 1024:
                raise ValueError("native artifact metadata exceeds size limit")
            return json.loads(path.read_text(encoding="utf-8-sig"))

        manifest = document("candidate-manifest.json")
        if (
            manifest.get("kernel_revision") != component["revision"]
            or manifest.get("distribution_revision") != source_revision
            or manifest.get("github_repository") != "untrod/apeir"
            or manifest.get("source_build") != "PASS"
            or manifest.get("native_smoke") != "success"
        ):
            raise ValueError(
                "native artifact provenance or compatibility is unqualified"
            )
        files = manifest["files"]
        if (
            len(files) != len(binary_paths)
            or {item["path"] for item in files} != binary_paths
        ):
            raise ValueError("native artifact binary inventory is inconsistent")
        for item in files:
            if _sha256(staged / item["path"]) != str(item["sha256"]).upper():
                raise ValueError("native artifact binary digest mismatch")
        smoke = document("native-smoke.json")
        if smoke.get("target") != component["target"]:
            raise ValueError("native smoke target does not match the lock")
        for field in (
            "kernel_ready",
            "authenticated_status",
            "provider_worker_health",
            "invalid_nki_runtime_start_rejected",
            "invalid_http_sessions_rejected",
            "token_owner_only_dacl",
            "process_tree_closed",
            "kernel_process_tree_closed",
            "final_runtime_process_closed",
            "restarted_authenticated_status",
        ):
            if smoke.get(field) is not True:
                raise ValueError("native sidecar compatibility evidence is incomplete")
        nki, recovery = document("nki-initial.json"), document("nki-recovery.json")
        if (
            nki.get("status") != "PASS"
            or recovery.get("status") != "PASS"
            or recovery.get("recovery_query_only") is not True
            or recovery.get("model_operation_submissions") != 0
            or recovery.get("original_workload_id") != nki.get("original_workload_id")
            or recovery.get("original_profile_sha256")
            != nki.get("original_profile_sha256")
            or not re.fullmatch(
                r"native-smoke-denied-model-[0-9a-f]{32}",
                str(nki.get("original_workload_id")),
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(nki.get("original_profile_sha256"))
            )
            or not set(component.get("nki_versions", [])).issubset(
                nki.get("request_versions_exercised", [])
            )
        ):
            raise ValueError("native original-workload recovery evidence is incomplete")
        staged.replace(output)
    return {
        "status": "ok",
        "archive_sha256": archive_sha256.upper(),
        "producer_revision": source_revision,
        "artifacts": results,
        "installation_acceptance": "NOT_RUN",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--kernel-root", type=Path)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--artifact-zip", type=Path)
    parser.add_argument("--artifact-sha256")
    parser.add_argument("--artifact-source-revision")
    parser.add_argument("--artifact-output", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    lock_path = (args.lock or repo_root / "runtime-components.lock.json").resolve()
    kernel_root = args.kernel_root.resolve() if args.kernel_root else None
    if args.artifact_zip is not None:
        if (
            not args.artifact_sha256
            or not args.artifact_source_revision
            or args.artifact_output is None
            or args.candidate_root is not None
            or args.report is not None
        ):
            parser.error(
                "--artifact-zip requires digest, source revision and new output; diagnostic modes cannot be combined"
            )
        admitted = admit_artifact(
            args.artifact_zip,
            args.artifact_sha256,
            args.artifact_output,
            lock_path,
            args.artifact_source_revision,
            kernel_root,
        )
        print(json.dumps(admitted, indent=2))
        return 0
    if args.artifact_sha256 or args.artifact_source_revision or args.artifact_output:
        parser.error("artifact admission options require --artifact-zip")
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

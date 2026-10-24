from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.ci.verify_kernel_components import (
    admit_artifact,
    main,
    report_rebuild,
    verify,
)


def _write_pe(path: Path, machine: int = 0xAA64) -> None:
    data = bytearray(256)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, machine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_lock(path: Path, artifact: Path, digest: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": {
                    "nous-kernel": {
                        "revision": "abc123",
                        "target": "aarch64-pc-windows-msvc",
                        "artifacts": [
                            {
                                "name": "nousd",
                                "path": artifact.as_posix(),
                                "sha256": digest,
                                "pe_machine": "0xAA64",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def native_bundle(tmp_path):
    """Synthetic PE admission contracts, never native execution qualification."""
    binary = tmp_path / "fixture.exe"
    _write_pe(binary, machine=0x8664)
    content = binary.read_bytes()
    native_paths = [
        f"desktop/src-tauri/binaries/{name}-x86_64-pc-windows-msvc.exe"
        for name in ("nousd", "nous-provider-worker")
    ]
    lock = tmp_path / "lock.json"
    _write_lock(lock, Path(native_paths[0]), hashlib.sha256(content).hexdigest())
    document = json.loads(lock.read_text())
    component = document["components"]["nous-kernel"]
    component.update(target="x86_64-pc-windows-msvc", nki_versions=[1, 2, 3])
    component["artifacts"][0]["pe_machine"] = "0x8664"
    component["artifacts"].append(
        {
            **component["artifacts"][0],
            "name": "nous-provider-worker",
            "path": native_paths[1],
        }
    )
    lock.write_text(json.dumps(document))
    files = {path: content for path in native_paths + ["nous-runtime.exe"]}
    manifest = {
        "kernel_revision": "abc123",
        "distribution_revision": "1" * 40,
        "github_repository": "untrod/apeir",
        "source_build": "PASS",
        "native_smoke": "success",
        "files": [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in files.items()
        ],
    }
    smoke = {
        key: True
        for key in (
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
        )
    }
    smoke["target"] = "x86_64-pc-windows-msvc"
    nki = {
        "status": "PASS",
        "original_workload_id": "native-smoke-denied-model-" + "2" * 32,
        "original_profile_sha256": "3" * 64,
        "request_versions_exercised": [1, 2, 3],
    }
    recovery = {**nki, "recovery_query_only": True, "model_operation_submissions": 0}
    files.update(
        {
            name: json.dumps(value).encode()
            for name, value in {
                "candidate-manifest.json": manifest,
                "native-smoke.json": smoke,
                "nki-initial.json": nki,
                "nki-recovery.json": recovery,
            }.items()
        }
    )

    def bundle(fault=None):
        entries = dict(files)
        if fault == "path":
            entries["../escaped.exe"] = b"not admitted"
        elif fault == "missing-worker":
            entries.pop(native_paths[1])
        elif fault == "tamper-worker":
            entries[native_paths[1]] += b"changed"
        elif fault == "false-smoke":
            invalid = {**smoke, "token_owner_only_dacl": False}
            entries["native-smoke.json"] = json.dumps(invalid).encode()
        elif fault == "producer":
            entries["candidate-manifest.json"] = json.dumps(
                {**manifest, "distribution_revision": "4" * 40}
            ).encode()
        entries["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {path}\n"
            for path, data in entries.items()
        ).encode()
        archive = tmp_path / "native.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for path, data in entries.items():
                if fault == "symlink" and path == "nous-runtime.exe":
                    info = zipfile.ZipInfo(path)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    zipped.writestr(info, data)
                else:
                    zipped.writestr(path, data)
        if fault == "bomb":
            data = bytearray(archive.read_bytes())
            central = data.index(b"PK\x01\x02")
            struct.pack_into("<I", data, central + 24, 513 * 1024 * 1024)
            archive.write_bytes(data)
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest()

    return lock, tmp_path / "admitted", bundle, files


def test_reviewed_archive_uses_real_lock_admission_and_does_not_replace_output(
    native_bundle,
):
    lock, output, bundle, files = native_bundle
    archive, digest = bundle()
    result = admit_artifact(archive, digest, output, lock, "1" * 40)
    assert result["status"] == "ok"
    assert result["installation_acceptance"] == "NOT_RUN"
    assert all((output / path).read_bytes() == data for path, data in files.items())
    with pytest.raises(ValueError, match="existing directory"):
        admit_artifact(archive, digest, output, lock, "1" * 40)
    assert all((output / path).read_bytes() == data for path, data in files.items())


@pytest.mark.parametrize(
    "fault",
    [
        "path",
        "symlink",
        "bomb",
        "missing-worker",
        "tamper-worker",
        "false-smoke",
        "producer",
        "outer-sha",
    ],
)
def test_bad_archive_never_publishes_any_native_input(native_bundle, fault):
    lock, output, bundle, _ = native_bundle
    original_lock = lock.read_bytes()
    archive, digest = bundle(fault)
    with pytest.raises((ValueError, FileNotFoundError)):
        admit_artifact(
            archive,
            "0" * 64 if fault == "outer-sha" else digest,
            output,
            lock,
            "1" * 40,
        )
    assert not output.exists()
    assert lock.read_bytes() == original_lock
    assert not list(output.parent.glob("native-admission-*"))


def test_smoke_manifest_cannot_approve_hashes_outside_component_lock(native_bundle):
    lock, output, bundle, _ = native_bundle
    archive, digest = bundle()
    document = json.loads(lock.read_text())
    document["components"]["nous-kernel"]["artifacts"][0]["sha256"] = "0" * 64
    lock.write_text(json.dumps(document))
    original = lock.read_bytes()
    with pytest.raises(ValueError, match="hash mismatch"):
        admit_artifact(archive, digest, output, lock, "1" * 40)
    assert lock.read_bytes() == original and not output.exists()


def test_component_lock_verifies_hash_and_architecture(tmp_path: Path) -> None:
    relative = Path("desktop/bin/nousd.exe")
    artifact = tmp_path / relative
    _write_pe(artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, relative, digest)

    result = verify(tmp_path, lock, None)

    assert result[0]["name"] == "nousd"
    assert result[0]["pe_machine"] == "0xAA64"


def test_component_lock_rejects_modified_binary(tmp_path: Path) -> None:
    relative = Path("desktop/bin/nousd.exe")
    artifact = tmp_path / relative
    _write_pe(artifact)
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, relative, "0" * 64)

    with pytest.raises(ValueError, match="hash mismatch"):
        verify(tmp_path, lock, None)


def test_component_lock_rejects_path_escape(tmp_path: Path) -> None:
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, Path("../nousd.exe"), "0" * 64)

    with pytest.raises(ValueError, match="unsafe component path"):
        verify(tmp_path, lock, None)


@pytest.mark.parametrize(
    ("target", "expected_machine"),
    [
        ("x86_64-pc-windows-msvc", "0x8664"),
        ("aarch64-pc-windows-msvc", "0xAA64"),
    ],
)
def test_locked_64bit_component_rejects_32bit_pe_with_matching_hash(
    tmp_path: Path, target: str, expected_machine: str
) -> None:
    relative = Path("desktop/bin/nousd.exe")
    artifact = tmp_path / relative
    _write_pe(artifact, machine=0x014C)
    original = artifact.read_bytes()
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, relative, hashlib.sha256(original).hexdigest())
    data = json.loads(lock.read_text())
    data["components"]["nous-kernel"]["target"] = target
    data["components"]["nous-kernel"]["artifacts"][0]["pe_machine"] = expected_machine
    lock.write_text(json.dumps(data), encoding="utf-8")
    original_lock = lock.read_bytes()

    # Digest admission succeeds, so rejection must come from the real PE
    # architecture boundary, not an unrelated missing file or hash mismatch.
    with pytest.raises(ValueError, match="architecture mismatch"):
        verify(tmp_path, lock, None)

    assert artifact.read_bytes() == original
    assert lock.read_bytes() == original_lock


@pytest.fixture
def rebuilt_candidate(tmp_path: Path) -> tuple[Path, Path, Path]:
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=kernel, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Contract Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=kernel,
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=kernel, text=True
    ).strip()
    candidates = kernel / "target" / "release"
    artifact = candidates / "nousd.exe"
    _write_pe(artifact)
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(
        lock,
        Path("desktop/bin/nousd.exe"),
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    data = json.loads(lock.read_text())
    data["components"]["nous-kernel"]["revision"] = revision
    # Both locked components must be inspected, even when the first is invalid.
    second = dict(data["components"]["nous-kernel"]["artifacts"][0])
    second.update(name="nous-provider-worker", path="desktop/bin/worker.exe")
    data["components"]["nous-kernel"]["artifacts"].append(second)
    _write_pe(candidates / "nous-provider-worker.exe")
    lock.write_text(json.dumps(data), encoding="utf-8")
    return lock, kernel, candidates


def test_rebuild_report_requires_both_actual_hashes_and_architectures(
    rebuilt_candidate,
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    report = report_rebuild(lock, kernel, candidates)
    assert report["status"] == "MATCH"
    assert report["tracked_source_clean"] is True
    assert report["installation_acceptance"] == "NOT_RUN"
    assert report["runtime_nki_validation"] == "NOT_RUN"
    assert len(report["artifacts"]) == 2
    assert all(
        item["sha256"] == item["expected_sha256"] for item in report["artifacts"]
    )
    assert all(item["pe_machine"] == "0xAA64" for item in report["artifacts"])


@pytest.mark.parametrize(
    "fault", ["hash", "architecture", "invalid_pe", "missing", "revision", "source"]
)
def test_rebuild_report_fails_closed_and_keeps_original_lock(
    rebuilt_candidate, fault
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    original_lock = lock.read_bytes()
    path = candidates / "nousd.exe"
    if fault == "hash":
        path.write_bytes(path.read_bytes() + b"modified")
    elif fault == "architecture":
        data = bytearray(path.read_bytes())
        struct.pack_into("<H", data, 132, 0x8664)
        path.write_bytes(data)
    elif fault == "invalid_pe":
        path.write_bytes(b"not a Windows executable")
    elif fault == "missing":
        path.unlink()
    elif fault == "revision":
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-qm",
                "another revision",
            ],
            cwd=kernel,
            check=True,
        )
    else:
        tracked = kernel / "source.txt"
        tracked.write_text("original", encoding="utf-8")
        subprocess.run(["git", "add", "source.txt"], cwd=kernel, check=True)
    report = report_rebuild(lock, kernel, candidates)
    assert report["status"] == "BLOCKED"
    assert report["errors"]
    assert len(report["artifacts"]) == 2
    assert report["artifacts"][1]["errors"] == []
    assert lock.read_bytes() == original_lock


def test_rebuild_cli_writes_blocked_evidence_and_returns_nonzero(
    rebuilt_candidate, monkeypatch, tmp_path
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    (candidates / "nousd.exe").unlink()
    output = tmp_path / "evidence" / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            "--lock",
            str(lock),
            "--kernel-root",
            str(kernel),
            "--candidate-root",
            str(candidates),
            "--report",
            str(output),
        ],
    )
    assert main() == 2
    assert json.loads(output.read_text())["status"] == "BLOCKED"
    assert not (tmp_path / "desktop").exists()


def test_rebuild_cli_cannot_overwrite_component_lock(
    rebuilt_candidate, monkeypatch
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    original = lock.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            "--lock",
            str(lock),
            "--kernel-root",
            str(kernel),
            "--candidate-root",
            str(candidates),
            "--report",
            str(lock),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert lock.read_bytes() == original

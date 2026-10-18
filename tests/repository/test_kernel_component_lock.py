from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.verify_kernel_components import main, report_rebuild, verify


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

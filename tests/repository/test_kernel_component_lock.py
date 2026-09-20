from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from scripts.ci.verify_kernel_components import verify


def _write_pe(path: Path, machine: int = 0xAA64) -> None:
    data = bytearray(256)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, machine)
    path.parent.mkdir(parents=True)
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

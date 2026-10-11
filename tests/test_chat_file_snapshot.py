"""File input evidence must describe the same bounded bytes as the model sees."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime


def test_read_content_and_digest_stay_bound_during_a_concurrent_edit(
    tmp_path, monkeypatch
):
    target = tmp_path / "source.txt"
    before = b"original public input\n"
    after = b"new public input\n"
    target.write_bytes(before)
    original_open = Path.open
    reads = []

    class ReplacedAfterRead:
        def __init__(self, stream, mode):
            self.stream, self.mode = stream, mode

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            result = self.stream.read(size)
            reads.append(self.mode)
            with original_open(target, "wb") as writer:
                writer.write(after)
            return result

    def replace_after_read(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == target and "r" in mode:
            return ReplacedAfterRead(stream, mode)
        return stream

    monkeypatch.setattr(Path, "open", replace_after_read)
    result = WorkspaceToolRuntime(tmp_path).execute("read_file", {"path": target.name})
    assert result["ok"]
    assert result["content"] == "original public input"
    assert result["sha256"] == hashlib.sha256(before).hexdigest()
    assert target.read_bytes() == after
    # Inspect the tool reads before the independent assertion's read above.
    assert reads[:-1] == ["rb"]


def test_read_refuses_file_growth_after_the_size_precheck(tmp_path, monkeypatch):
    target = tmp_path / "source.txt"
    target.write_bytes(b"small input")
    original_open = Path.open
    grown = False

    def grow_before_read(path, mode="r", *args, **kwargs):
        nonlocal grown
        if path == target and "r" in mode and not grown:
            grown = True
            with original_open(target, "wb") as writer:
                writer.write(b"x" * (256 * 1024 + 1))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_before_read)
    result = WorkspaceToolRuntime(tmp_path).execute("read_file", {"path": target.name})
    assert grown
    assert result["ok"] is False
    assert "256 KiB" in result["error"]
    assert "content" not in result and "sha256" not in result


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_line_selection_preserves_the_original_utf8_byte_digest(tmp_path, newline):
    raw = (
        newline.join(["first".encode(), "第二行".encode(), "third".encode()]) + newline
    )
    (tmp_path / "source.txt").write_bytes(raw)
    result = WorkspaceToolRuntime(tmp_path).execute(
        "read_file", {"path": "source.txt", "start_line": 2, "end_line": 2}
    )
    assert result["ok"] and result["content"] == "第二行"
    assert result["start_line"] == result["end_line"] == 2
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()


def test_read_refuses_non_utf8_without_successful_input_evidence(tmp_path):
    (tmp_path / "source.txt").write_bytes(b"\xff\xfe")
    result = WorkspaceToolRuntime(tmp_path).execute("read_file", {"path": "source.txt"})
    assert result["ok"] is False
    assert "content" not in result and "sha256" not in result

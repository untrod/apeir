"""File input evidence must describe the same bounded bytes as the model sees."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
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
    from nous_runtime.chat import agent_tools

    original_reader = agent_tools.read_workspace_bytes
    original_open = Path.open
    reads = []
    tool_active = True

    def replace_after_acquisition(*args, **kwargs):
        # The real descriptor reader has finished its no-follow, link, bound and
        # stability checks. An ordinary later edit cannot change acquired bytes.
        captured = original_reader(*args, **kwargs)
        reads.append(captured)
        with original_open(target, "wb") as writer:
            writer.write(after)
        return captured

    def forbid_reopen(path, mode="r", *args, **kwargs):
        if tool_active and path == target and "r" in mode:
            raise AssertionError(
                "The tool must hash its captured bytes, not reopen a path"
            )
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(agent_tools, "read_workspace_bytes", replace_after_acquisition)
    monkeypatch.setattr(Path, "open", forbid_reopen)
    result = WorkspaceToolRuntime(tmp_path).execute("read_file", {"path": target.name})
    tool_active = False
    assert result["ok"]
    assert result["content"] == "original public input"
    assert result["sha256"] == hashlib.sha256(before).hexdigest()
    assert target.read_bytes() == after
    assert reads == [before]


def test_read_refuses_file_growth_after_the_size_precheck(tmp_path, monkeypatch):
    from nous_runtime.workspace import isolation

    target = tmp_path / "source.txt"
    target.write_bytes(b"small input")
    original_descriptor = isolation._workspace_read_descriptor
    grown = False
    admissions = []

    @contextmanager
    def grow_before_read(workspace, relative):
        nonlocal grown
        admissions.append(relative)
        if relative == Path(target.name) and not grown:
            grown = True
            target.write_bytes(b"x" * (256 * 1024 + 1))
        # Mutation precedes the actual open, including Windows' no-write-share
        # handle; the real opened-file fstat must reject the new oversized inode.
        with original_descriptor(workspace, relative) as descriptor:
            yield descriptor

    monkeypatch.setattr(isolation, "_workspace_read_descriptor", grow_before_read)
    result = WorkspaceToolRuntime(tmp_path).execute("read_file", {"path": target.name})
    assert grown
    assert admissions == [Path(target.name)]
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

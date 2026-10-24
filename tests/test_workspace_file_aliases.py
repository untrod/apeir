"""Ordinary workspace paths cannot alias private or external inode content."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PureWindowsPath

import pytest

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.workspace.isolation import normalize_workspace_path
from nous_runtime.workspace.isolation import read_workspace_bytes
from nous_runtime.workspace.proposals import WorkspaceProposalService
from nous_runtime.workspace.workbench import DeveloperWorkbench, WorkbenchError


def _require_symlinks(tmp_path):
    if os.name != "nt":
        return
    probe = tmp_path / "symlink-capability-probe"
    try:
        probe.symlink_to(tmp_path, target_is_directory=True)
    except PermissionError:
        pytest.skip("Windows account cannot create test-owned symlinks")
    else:
        probe.unlink()


@pytest.mark.parametrize("origin", [".nous", ".git", "outside"])
def test_ordinary_surfaces_refuse_linked_source_before_publication(tmp_path, origin):
    root = tmp_path / "workspace"
    root.mkdir()
    source = (
        tmp_path / "external.txt"
        if origin == "outside"
        else root / origin / "protected.txt"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b"OWNED_BENIGN_PRIVATE_BOUNDARY_MARKER\n"
    source.write_bytes(content)
    alias = root / "notes.txt"
    os.link(source, alias)
    assert source.stat().st_nlink == alias.stat().st_nlink == 2
    digest = hashlib.sha256(content).hexdigest()
    workbench = DeveloperWorkbench(root)
    chat = WorkspaceToolRuntime(str(root))
    gate = ExecutionAuthorizationGate(store=GovernanceStore(root / ".nous"))
    proposals = WorkspaceProposalService(root, gate=gate)

    with pytest.raises(WorkbenchError, match="single-link"):
        workbench.read_file(alias.name)
    assert workbench.list_files()["files"] == []
    assert workbench.search("OWNED_BENIGN")["matches"] == []
    result = chat.execute("read_file", {"path": alias.name})
    assert result["ok"] is False
    assert "OWNED_BENIGN" not in str(result)
    assert chat.execute("search_workspace", {"query": "OWNED_BENIGN"})["matches"] == []
    assert chat._read_versions == {}
    with pytest.raises(WorkbenchError, match="single-link"):
        workbench.preview_write(alias.name, "replacement\n", expected_sha256=digest)
    with pytest.raises(WorkbenchError, match="single-link"):
        proposals.prepare(
            [
                {
                    "path": alias.name,
                    "content": "replacement\n",
                    "expected_sha256": digest,
                }
            ],
            subject_id="fixture-agent",
        )
    assert proposals.artifacts.list() == []
    assert proposals.list()["proposals"] == []
    assert source.read_bytes() == alias.read_bytes() == content


def test_protected_single_link_and_legacy_explicit_scope_remain_compatible(tmp_path):
    source = tmp_path / "ordinary.txt"
    source.write_text("ordinary\n")
    assert (
        normalize_workspace_path(str(tmp_path), source.name, protect_runtime_state=True)
        == source
    )
    alias = tmp_path / "legacy.txt"
    os.link(source, alias)
    assert normalize_workspace_path(str(tmp_path), alias.name) == alias
    assert alias.read_text() == "ordinary\n"


@pytest.mark.parametrize("surface", ["workbench", "agent", "proposal"])
@pytest.mark.parametrize("replacement", ["symlink", "ancestor", "hardlink"])
def test_read_revalidates_opened_file_after_path_admission(
    tmp_path, monkeypatch, surface, replacement
):
    if replacement != "hardlink":
        _require_symlinks(tmp_path)
    root = tmp_path / "workspace"
    directory = root / "sources"
    directory.mkdir(parents=True)
    ordinary = directory / "notes.txt"
    ordinary.write_text("ordinary\n")
    protected = root / ".nous" / "private-owned-marker.txt"
    protected.parent.mkdir()
    marker = b"OWNED_BENIGN_PRIVATE_RACE_MARKER\n"
    protected.write_bytes(marker)
    # Pin an already admitted relative target, then make the concurrent change
    # before the actual byte reader. No private content or privileged process is
    # needed to reproduce this path-validation/open race.
    if surface == "workbench":
        reader = DeveloperWorkbench(root)
        name = "_resolve"

        def read():
            return reader.read_file("sources/notes.txt")
    elif surface == "agent":
        reader = WorkspaceToolRuntime(str(root))
        name = "_path"

        def read():
            return reader.execute("read_file", {"path": "sources/notes.txt"})
    else:
        gate = ExecutionAuthorizationGate(store=GovernanceStore(root / ".nous"))
        proposals = WorkspaceProposalService(root, gate=gate)
        reader = proposals.workbench
        name = "_write_target"

        def read():
            return proposals._observe("sources/notes.txt")

    original = getattr(reader, name)
    switched = False

    def switch_after_admission(*args, **kwargs):
        nonlocal switched
        target = original(*args, **kwargs)
        if not switched:
            switched = True
            if replacement == "ancestor":
                directory.rename(root / "sources-original")
                directory.symlink_to(protected.parent, target_is_directory=True)
                protected.rename(protected.parent / "notes.txt")
            else:
                ordinary.unlink()
                if replacement == "symlink":
                    ordinary.symlink_to(protected)
                else:
                    os.link(protected, ordinary)
        return target

    monkeypatch.setattr(reader, name, switch_after_admission)
    try:
        result = read()
    except (OSError, ValueError):
        result = None
    assert switched
    assert result is None or (isinstance(result, dict) and result.get("ok") is False), (
        result
    )
    assert marker.decode().strip() not in str(result)


@pytest.mark.parametrize("replacement", ["leaf", "ancestor", "root", "hardlink"])
def test_descriptor_open_refuses_changes_after_its_own_admission(
    tmp_path, monkeypatch, replacement
):
    from contextlib import contextmanager
    from nous_runtime.workspace import isolation

    if replacement != "hardlink":
        _require_symlinks(tmp_path)

    root = tmp_path / "workspace"
    directory = root / "sources"
    directory.mkdir(parents=True)
    target = directory / "notes.txt"
    target.write_text("ordinary\n")
    outside = tmp_path / "outside"
    (outside / "sources").mkdir(parents=True)
    marker = b"OWNED_BENIGN_DESCRIPTOR_BOUNDARY_MARKER\n"
    (outside / "notes.txt").write_bytes(marker)
    (outside / "sources" / "notes.txt").write_bytes(marker)
    original = isolation._workspace_read_descriptor

    @contextmanager
    def interrupt(workspace, relative):
        if replacement == "leaf":
            target.unlink()
            target.symlink_to(outside / "notes.txt")
        elif replacement == "ancestor":
            directory.rename(root / "sources-original")
            directory.symlink_to(outside, target_is_directory=True)
        elif replacement == "root":
            root.rename(tmp_path / "workspace-original")
            root.symlink_to(outside, target_is_directory=True)
        else:
            target.unlink()
            os.link(outside / "notes.txt", target)
        with original(workspace, relative) as descriptor:
            yield descriptor

    monkeypatch.setattr(isolation, "_workspace_read_descriptor", interrupt)
    with pytest.raises((OSError, ValueError)):
        read_workspace_bytes(root, "sources/notes.txt", max_bytes=128)


def test_changed_root_does_not_redefine_workspace_authority(tmp_path):
    _require_symlinks(tmp_path)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("ordinary\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("OWNED_BENIGN_DIFFERENT_ROOT\n")
    root.rename(tmp_path / "original")
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError, match="root has changed"):
        read_workspace_bytes(root, "notes.txt", max_bytes=128)


def test_safe_read_preserves_empty_and_internal_alias_compatibility(tmp_path):
    _require_symlinks(tmp_path)
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert read_workspace_bytes(tmp_path, "empty.txt", max_bytes=1) == b""
    (tmp_path / "alias.txt").symlink_to(empty)
    assert read_workspace_bytes(tmp_path, "alias.txt", max_bytes=1) == b""
    with pytest.raises(OSError):
        read_workspace_bytes(
            tmp_path, "alias.txt", max_bytes=1, follow_internal_links=False
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor cleanup contract")
@pytest.mark.parametrize("fail_open", [False, True])
def test_descriptor_read_closes_every_owned_handle(tmp_path, monkeypatch, fail_open):
    from nous_runtime.workspace import isolation

    (tmp_path / "notes.txt").write_text("ordinary\n")
    original_open, original_close = os.open, os.close
    owned = set()

    def tracked_open(path, *args, **kwargs):
        if fail_open and str(path) == "notes.txt":
            raise PermissionError("owned simulated open rejection")
        descriptor = original_open(path, *args, **kwargs)
        owned.add(descriptor)
        return descriptor

    def tracked_close(descriptor):
        owned.remove(descriptor)
        return original_close(descriptor)

    monkeypatch.setattr(isolation.os, "open", tracked_open)
    monkeypatch.setattr(isolation.os, "close", tracked_close)
    if fail_open:
        with pytest.raises(PermissionError):
            read_workspace_bytes(tmp_path, "notes.txt", max_bytes=128)
    else:
        assert (
            read_workspace_bytes(tmp_path, "notes.txt", max_bytes=128) == b"ordinary\n"
        )
    assert owned == set()


@pytest.mark.skipif(
    os.name == "nt", reason="Windows reader excludes concurrent writers"
)
def test_safe_read_rejects_file_changed_during_read(tmp_path, monkeypatch):
    from nous_runtime.workspace import isolation

    source = tmp_path / "notes.txt"
    source.write_bytes(b"ordinary\n")
    original = os.read
    changed = False

    def change_after_read(*args):
        nonlocal changed
        data = original(*args)
        if data and not changed:
            changed = True
            with source.open("ab") as stream:
                stream.write(b"owned concurrent edit\n")
        return data

    monkeypatch.setattr(isolation.os, "read", change_after_read)
    with pytest.raises(PermissionError, match="changed during"):
        read_workspace_bytes(tmp_path, "notes.txt", max_bytes=128)
    assert changed


@pytest.mark.skipif(os.name == "nt", reason="POSIX missing descriptor API contract")
def test_safe_read_has_no_pathname_only_fallback(tmp_path, monkeypatch):
    from nous_runtime.workspace import isolation

    (tmp_path / "notes.txt").write_text("ordinary\n")
    monkeypatch.setattr(isolation, "_POSIX_SAFE_OPEN_AVAILABLE", False)
    with pytest.raises(PermissionError, match="unavailable"):
        read_workspace_bytes(tmp_path, "notes.txt", max_bytes=128)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows read sharing contract")
def test_windows_read_pins_ancestors_and_excludes_mutation(tmp_path):
    from nous_runtime.workspace.isolation import _workspace_read_descriptor

    root = tmp_path.resolve() / "workspace"
    root.mkdir()
    source = root / "notes.txt"
    source.write_bytes(b"ordinary\n")
    with _workspace_read_descriptor(root, Path("notes.txt")) as descriptor:
        assert os.read(descriptor, 128) == b"ordinary\n"
        with pytest.raises(PermissionError):
            source.write_bytes(b"must not replace held bytes")
        with pytest.raises(PermissionError):
            root.rename(tmp_path / "moved-workspace")
    assert read_workspace_bytes(root, source, max_bytes=128) == b"ordinary\n"
    root.rename(tmp_path / "moved-workspace")


@pytest.mark.parametrize("content,minimum", [(b"too large", 0), (b"", 1)])
def test_read_limit_error_classifies_opened_file_byte_bounds(
    tmp_path, content, minimum
):
    from nous_runtime.workspace.isolation import WorkspaceReadLimitError

    (tmp_path / "notes.txt").write_bytes(content)
    with pytest.raises(WorkspaceReadLimitError):
        read_workspace_bytes(tmp_path, "notes.txt", max_bytes=4, minimum_bytes=minimum)


def test_read_limit_error_does_not_disguise_file_type_rejection(tmp_path):
    from nous_runtime.workspace.isolation import WorkspaceReadLimitError

    (tmp_path / "directory").mkdir()
    with pytest.raises(PermissionError) as error:
        read_workspace_bytes(tmp_path, "directory", max_bytes=128)
    assert not isinstance(error.value, WorkspaceReadLimitError)


@pytest.mark.skipif(
    os.name == "nt", reason="Windows reader excludes concurrent writers"
)
def test_read_limit_error_classifies_growth_after_opened_size_check(
    tmp_path, monkeypatch
):
    from nous_runtime.workspace import isolation

    source = tmp_path / "notes.txt"
    source.write_bytes(b"small")
    original = os.read
    grown = False

    def grow_before_actual_read(*args):
        nonlocal grown
        if not grown:
            grown = True
            source.write_bytes(b"x" * 129)
        return original(*args)

    monkeypatch.setattr(isolation.os, "read", grow_before_actual_read)
    with pytest.raises(isolation.WorkspaceReadLimitError):
        read_workspace_bytes(tmp_path, "notes.txt", max_bytes=128)
    assert grown


@pytest.mark.parametrize(
    "name",
    [
        "notes.txt:owned-stream",
        "notes.txt::$DATA",
        ".nous::$INDEX_ALLOCATION/private.txt",
        ".git::$INDEX_ALLOCATION/config",
        ".nous./private.txt",
        ".git /config",
        "sources./notes.txt",
        "notes.txt.",
        "notes.txt ",
    ],
)
def test_windows_name_rejection_precedes_native_file_api(name, monkeypatch):
    from types import SimpleNamespace
    from nous_runtime.workspace import isolation
    from nous_runtime.workspace.isolation import (
        _validate_windows_file_components,
        _windows_read_descriptor,
    )

    relative = PureWindowsPath(name)
    with pytest.raises(PermissionError, match="not ordinary workspace data"):
        _validate_windows_file_components(relative)
    # This also runs on POSIX: denial must precede msvcrt import/CreateFileW.
    with pytest.raises(PermissionError, match="not ordinary workspace data"):
        with _windows_read_descriptor(PureWindowsPath("C:/workspace"), relative):
            pytest.fail("An ambiguous Windows name reached a native file reader")

    class UnresolvedWindowsPath(PureWindowsPath):
        def resolve(self):
            raise AssertionError("Raw ambiguous names must be refused before resolve")

    with monkeypatch.context() as patch:
        patch.setattr(isolation, "Path", UnresolvedWindowsPath)
        patch.setattr(isolation, "os", SimpleNamespace(name="nt"))
        with pytest.raises(PermissionError, match="not ordinary workspace data"):
            normalize_workspace_path("C:/workspace", name, protect_runtime_state=True)


@pytest.mark.parametrize(
    "name",
    [
        "source.py",
        "sources/notes.txt",
        "C:/workspace/source.py",
        "//server/share/workspace/source.py",
        ".",
        "..",
        "sources/../notes.txt",
    ],
)
def test_windows_name_guard_preserves_anchors_and_existing_traversal_policy(name):
    from nous_runtime.workspace.isolation import _validate_windows_file_components

    # Accepting a component spelling is not path admission. Existing root and
    # traversal checks still decide whether these paths can actually be read.
    _validate_windows_file_components(PureWindowsPath(name))


@pytest.mark.skipif(os.name == "nt", reason="POSIX ordinary filename compatibility")
@pytest.mark.parametrize("name", ["notes:version.txt", "notes.txt.", "notes.txt "])
def test_windows_name_guard_does_not_change_posix_file_names(tmp_path, name):
    content = b"ordinary POSIX filename\n"
    (tmp_path / name).write_bytes(content)
    assert read_workspace_bytes(tmp_path, name, max_bytes=128) == content


@pytest.mark.skipif(os.name != "nt", reason="Real Windows alternate-stream contract")
@pytest.mark.parametrize("suffix", [":owned-stream", "::$DATA"])
def test_windows_ordinary_reader_refuses_real_owned_alternate_stream(tmp_path, suffix):
    from nous_runtime.workspace.isolation import _windows_read_descriptor

    root = tmp_path.resolve()
    source = root / "notes.txt"
    ordinary = b"owned ordinary source\n"
    source.write_bytes(ordinary)
    stream = Path(str(source) + suffix)
    marker = b"OWNED_BENIGN_WINDOWS_STREAM_MARKER\n"
    if suffix == ":owned-stream":
        stream.write_bytes(marker)
    else:
        marker = ordinary
    assert stream.read_bytes() == marker
    with pytest.raises(PermissionError, match="not ordinary workspace data"):
        normalize_workspace_path(str(root), stream.name, protect_runtime_state=True)
    with pytest.raises(PermissionError, match="not ordinary workspace data"):
        read_workspace_bytes(root, stream.name, max_bytes=128)
    with pytest.raises(PermissionError, match="not ordinary workspace data"):
        with _windows_read_descriptor(root, Path(stream.name)):
            pytest.fail("An alternate stream reached the native ordinary file reader")
    # Legacy explicit scope remains a distinct compatibility contract.
    assert normalize_workspace_path(str(root), stream.name).read_bytes() == marker
    assert read_workspace_bytes(root, source.name, max_bytes=128) == ordinary

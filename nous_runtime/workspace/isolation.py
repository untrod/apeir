"""Workspace path isolation helpers."""

from __future__ import annotations

import stat
import os
from contextlib import contextmanager
from pathlib import Path

_POSIX_SAFE_OPEN_AVAILABLE = (
    os.open in os.supports_dir_fd
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
)


class WorkspaceHardLinkError(PermissionError):
    """An ordinary workspace path aliases another regular-file name."""


class WorkspaceFileChangedError(PermissionError):
    """The opened inode changed while its bytes were being read."""


class WorkspaceReadLimitError(PermissionError):
    """An ordinary opened file exceeds the caller's allowed byte bounds."""


def _validate_windows_file_components(path):
    """Exclude stream syntax and ambiguous ordinary Win32 component names."""
    for component in path.parts:
        if component == path.anchor or component in {".", ".."}:
            continue
        if ":" in component or component.endswith((".", " ")):
            raise PermissionError(
                "Windows streams and ambiguous names are not ordinary workspace data."
            )


@contextmanager
def _workspace_read_descriptor(workspace: Path, relative: Path):
    """Pin directories and refuse link replacement at the actual open boundary."""
    if os.name == "nt":
        with _windows_read_descriptor(workspace, relative) as descriptor:
            yield descriptor
        return
    if not _POSIX_SAFE_OPEN_AVAILABLE:
        raise PermissionError("Safe workspace file reads are unavailable.")
    descriptors = []
    try:
        directory = os.open(
            workspace.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        descriptors.append(directory)
        for part in (*workspace.parts[1:], *relative.parts[:-1]):
            directory = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            descriptors.append(directory)
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        descriptors.append(descriptor)
        yield descriptor
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def _windows_read_descriptor(workspace: Path, relative: Path):
    """Windows equivalent: pin ancestors against rename and reject reparse points.

    No FILE_SHARE_DELETE on held ancestors prevents junction/symlink replacement
    while the next component is opened. The leaf also refuses concurrent writes.
    An unavailable API or incompatible existing writer denies the read; there is
    no pathname-only fallback.
    """
    _validate_windows_file_components(workspace)
    _validate_windows_file_components(relative)
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL

    class FileInformation(ctypes.Structure):
        _fields_ = (
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("modified", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        )

    information = kernel.GetFileInformationByHandle
    information.argtypes = (wintypes.HANDLE, ctypes.POINTER(FileInformation))
    information.restype = wintypes.BOOL
    handles = []
    descriptor = None
    try:
        current = Path(workspace.anchor)
        directories = [current]
        for part in (*workspace.parts[1:], *relative.parts[:-1]):
            current = current / part
            directories.append(current)
        for path, is_directory in (
            *((directory, True) for directory in directories),
            (workspace / relative, False),
        ):
            handle = create(
                str(path),
                0x80 if is_directory else 0x80000000,  # attributes / GENERIC_READ
                0x3 if is_directory else 0x1,  # share READ|WRITE / READ, no DELETE
                None,
                3,  # OPEN_EXISTING
                0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = FileInformation()
            if not information(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or bool(info.attributes & 0x10) != is_directory:
                raise PermissionError(
                    "Workspace reparse points are not ordinary files."
                )
            if not is_directory:
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                handles.pop()  # The CRT descriptor now owns this leaf handle.
        yield descriptor
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for handle in reversed(handles):
            close(handle)


def read_workspace_bytes(
    workspace_path: str | Path,
    candidate_path: str | Path,
    *,
    max_bytes: int,
    minimum_bytes: int = 0,
    follow_internal_links: bool = True,
    on_read=None,
) -> bytes:
    """Read bounded ordinary bytes from the admitted inode, never a reopened name.

    This is filesystem admission only: it supplies neither read authority nor
    permission to transfer content to a Provider. Those stay with the caller's
    existing Governance and Context owners.
    """
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
        or isinstance(minimum_bytes, bool)
        or not isinstance(minimum_bytes, int)
        or not 0 <= minimum_bytes <= max_bytes
    ):
        raise ValueError("A valid workspace read byte bound is required.")
    # Callers hold their canonical workspace identity. Resolving that identity
    # anew after a replacement would silently admit an entirely different root.
    workspace = Path(os.path.abspath(workspace_path))
    if workspace.resolve() != workspace:
        raise PermissionError("The admitted workspace root has changed.")
    admitted = normalize_workspace_path(
        str(workspace), str(candidate_path), protect_runtime_state=True
    )
    candidate = Path(candidate_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    relative = (admitted if follow_internal_links else candidate).relative_to(workspace)
    if ".." in relative.parts:
        raise PermissionError("Workspace file traversal is not admitted.")
    if not relative.parts:
        raise PermissionError("An ordinary workspace file is required.")
    with _workspace_read_descriptor(workspace, relative) as descriptor:
        before = os.fstat(descriptor)
        if before.st_nlink != 1:
            raise WorkspaceHardLinkError(
                "Ordinary workspace data requires single-link files."
            )
        if not stat.S_ISREG(before.st_mode):
            raise PermissionError("An ordinary workspace file is required.")
        if not minimum_bytes <= before.st_size <= max_bytes:
            raise WorkspaceReadLimitError("Workspace file byte bound is not admitted.")
        data = bytearray()
        while chunk := os.read(descriptor, min(8192, max_bytes + 1 - len(data))):
            if on_read is not None:
                on_read()
            data.extend(chunk)
            if len(data) > max_bytes:
                raise WorkspaceReadLimitError(
                    "Workspace file exceeds its read byte bound."
                )
        after = os.fstat(descriptor)
        if after.st_nlink != 1:
            raise WorkspaceHardLinkError(
                "Ordinary workspace data requires single-link files."
            )
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(data) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in fields
        ):
            raise WorkspaceFileChangedError(
                "Workspace file changed during its bounded read."
            )
        return bytes(data)


def normalize_workspace_path(
    workspace_path: str,
    candidate_path: str,
    *,
    protect_runtime_state: bool = False,
) -> Path:
    workspace_input = Path(workspace_path)
    candidate = Path(candidate_path)
    if protect_runtime_state and os.name == "nt":
        # Validate raw names before Win32 resolution can erase an alias spelling.
        # The compatibility mode and POSIX filename rules remain unchanged.
        _validate_windows_file_components(workspace_input)
        _validate_windows_file_components(candidate)
    workspace = workspace_input.resolve()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise PermissionError(f"path escapes workspace: {candidate_path}") from exc
    if protect_runtime_state and any(
        part.casefold() in {".nous", ".git"} for part in relative.parts
    ):
        raise PermissionError("Runtime-private paths are not ordinary workspace data.")
    if protect_runtime_state:
        try:
            info = resolved.stat()
        except FileNotFoundError:
            pass  # Preserve admission of not-yet-created ordinary write targets.
        else:
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise WorkspaceHardLinkError(
                    "Ordinary workspace data requires single-link files."
                )
    return resolved


def is_within_workspace(workspace_path: str, candidate_path: str) -> bool:
    try:
        normalize_workspace_path(workspace_path, candidate_path)
        return True
    except PermissionError:
        return False

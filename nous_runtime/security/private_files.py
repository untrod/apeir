"""Local private-file permissions and static database path admission."""

from __future__ import annotations

import ctypes
import os
import stat
from pathlib import Path
from ctypes import wintypes


def restrict_owner_only_file(path: str | os.PathLike[str], *, subject: str) -> None:
    """Restrict a file to the current OS identity or raise PermissionError."""
    resolved = os.path.abspath(os.fspath(path))
    if os.name != "nt":
        os.chmod(resolved, stat.S_IRUSR | stat.S_IWUSR)
        mode = stat.S_IMODE(os.stat(resolved).st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PermissionError(f"{subject} permissions are too broad: {mode:o}")
        return
    try:
        _set_current_user_only_windows_acl(resolved)
    except OSError as exc:
        raise PermissionError(f"could not restrict the {subject} ACL: {exc}") from exc


def _set_current_user_only_windows_acl(path: str) -> None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    advapi32.SetFileSecurityW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    advapi32.SetFileSecurityW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    token_query = 0x0008
    token_user_class = 1
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    sid_text = wintypes.LPWSTR()
    descriptor = wintypes.LPVOID()
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user_class, None, 0, ctypes.byref(required)
        )
        if not required.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID))[0]
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        sddl = f"D:P(A;;FA;;;{sid_text.value})"
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        dacl_security_information = 0x00000004
        protected_dacl_security_information = 0x80000000
        if not advapi32.SetFileSecurityW(
            path,
            dacl_security_information | protected_dacl_security_information,
            descriptor,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)
        if sid_text:
            kernel32.LocalFree(sid_text)
        kernel32.CloseHandle(token)


def validate_private_database_path(path: str | os.PathLike[str]) -> None:
    """Reject static links and nonregular SQLite state before a connection.

    Validate the state directory and SQLite sidecars without resolving
    links. Missing files remain valid for ordinary first-use creation. This is
    admission of local state paths, not protection against an OS owner swapping
    a path after validation, nor a replacement for owner-only ACLs.
    """
    target = Path(os.path.abspath(os.fspath(path)))
    try:
        parent_info = target.parent.lstat()
    except FileNotFoundError:
        parent_info = None
    if parent_info is not None and (
        stat.S_ISLNK(parent_info.st_mode)
        or getattr(parent_info, "st_file_attributes", 0) & 0x400
        or not stat.S_ISDIR(parent_info.st_mode)
    ):
        raise PermissionError("private state must use an unlinked directory")
    for candidate in (
        target,
        *(Path(str(target) + suffix) for suffix in ("-wal", "-shm", "-journal")),
    ):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink > 1
        ):
            raise PermissionError("private database must use unlinked regular files")

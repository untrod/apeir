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
        # Set both ownership and the protected DACL.  A DACL alone is not an
        # owner-only contract when an elevated token creates a group-owned
        # file; the policy reader checks the same current-user owner below.
        sddl = f"O:{sid_text.value}D:P(A;;FA;;;{sid_text.value})"
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        owner_security_information = 0x00000001
        dacl_security_information = 0x00000004
        protected_dacl_security_information = 0x80000000
        if not advapi32.SetFileSecurityW(
            path,
            owner_security_information
            | dacl_security_information
            | protected_dacl_security_information,
            descriptor,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)
        if sid_text:
            kernel32.LocalFree(sid_text)
        kernel32.CloseHandle(token)


def _windows_owner_acl_is_current_user_only(descriptor: int) -> bool:
    """Verify the owner and protected DACL on the already-open file handle.

    This checks the handle whose bytes will be consumed.  It intentionally
    accepts exactly one explicit allow ACE for the current user.  Broader,
    inherited, null, malformed, or group-owned ACLs fail closed.
    """
    if os.name != "nt":
        raise OSError("Windows ACL verification is unavailable on this host")
    import msvcrt

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))

    class SidAndAttributes(ctypes.Structure):
        _fields_ = (("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD))

    class TokenUser(ctypes.Structure):
        _fields_ = (("user", SidAndAttributes),)

    class AclSizeInformation(ctypes.Structure):
        _fields_ = (
            ("ace_count", wintypes.DWORD),
            ("acl_bytes_in_use", wintypes.DWORD),
            ("acl_bytes_free", wintypes.DWORD),
        )

    class AceHeader(ctypes.Structure):
        _fields_ = (
            ("ace_type", ctypes.c_ubyte),
            ("ace_flags", ctypes.c_ubyte),
            ("ace_size", wintypes.WORD),
        )

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = (
            ("header", AceHeader),
            ("mask", wintypes.DWORD),
            ("sid_start", wintypes.DWORD),
        )

    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSecurityInfo.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    )
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_int,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.IsValidAcl.argtypes = (wintypes.LPVOID,)
    advapi32.IsValidAcl.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    )
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.IsValidSid.argtypes = (wintypes.LPVOID,)
    advapi32.IsValidSid.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = (wintypes.LPVOID,)
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.EqualSid.argtypes = (wintypes.LPVOID, wintypes.LPVOID)
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL

    token = wintypes.HANDLE()
    security_descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise ctypes.WinError(ctypes.get_last_error())
        token_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, 1, token_buffer, required, ctypes.byref(required)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        current_sid = ctypes.cast(
            token_buffer, ctypes.POINTER(TokenUser)
        ).contents.user.sid
        result = advapi32.GetSecurityInfo(
            handle,
            1,  # SE_FILE_OBJECT
            0x00000001 | 0x00000004,  # OWNER and DACL security information
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(security_descriptor),
        )
        if result:
            raise ctypes.WinError(result)
        if (
            not owner
            or not dacl
            or not advapi32.IsValidSid(owner)
            or not advapi32.EqualSid(owner, current_sid)
        ):
            return False
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if (
            not advapi32.GetSecurityDescriptorControl(
                security_descriptor, ctypes.byref(control), ctypes.byref(revision)
            )
            or not control.value & 0x1000
        ):  # SE_DACL_PROTECTED
            return False
        details = AclSizeInformation()
        if (
            not advapi32.IsValidAcl(dacl)
            or not advapi32.GetAclInformation(
                dacl, ctypes.byref(details), ctypes.sizeof(details), 2
            )
            or details.ace_count != 1
        ):
            return False
        ace_pointer = wintypes.LPVOID()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(AccessAllowedAce)).contents
        if (
            ace.header.ace_type != 0  # ACCESS_ALLOWED_ACE_TYPE
            or ace.header.ace_flags != 0  # no inherited or inherit-only semantics
            or ace.header.ace_size < AccessAllowedAce.sid_start.offset + 8
            or not ace.mask & 0x00000001  # FILE_READ_DATA
            or not ace.mask & 0x00020000  # READ_CONTROL
        ):
            return False
        ace_sid = ctypes.cast(
            ctypes.addressof(ace) + AccessAllowedAce.sid_start.offset,
            wintypes.LPVOID,
        )
        if not advapi32.IsValidSid(ace_sid):
            return False
        sid_length = advapi32.GetLengthSid(ace_sid)
        return bool(
            sid_length
            and AccessAllowedAce.sid_start.offset + sid_length <= ace.header.ace_size
            and advapi32.EqualSid(ace_sid, current_sid)
        )
    finally:
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)
        kernel32.CloseHandle(token)


def read_current_user_only_windows_file(
    path: str | os.PathLike[str],
    *,
    max_bytes: int,
    subject: str,
) -> bytes:
    """Read one bounded Windows file after same-handle owner/DACL admission."""
    if os.name != "nt":
        raise OSError("Windows owner-only file access is unavailable on this host")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("A positive owner-file byte bound is required")
    from nous_runtime.workspace.isolation import (
        WorkspaceFileChangedError,
        WorkspaceHardLinkError,
        WorkspaceReadLimitError,
        _validate_windows_file_components,
        _workspace_read_descriptor,
    )

    supplied = Path(path)
    # GetFullPathNameW (used by Windows abspath) can discard trailing dots or
    # spaces. Check the user's spelling before any Win32 normalization so an
    # ambiguous name cannot become an apparently ordinary admitted file.
    _validate_windows_file_components(supplied)
    if any("~" in component for component in supplied.parts):
        raise PermissionError(
            f"{subject} cannot use an ambiguous Windows short-name component"
        )
    target = Path(os.path.abspath(os.fspath(supplied)))
    try:
        relative = Path(target.name)
        with _workspace_read_descriptor(target.parent, relative) as descriptor:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= max_bytes
                or not _windows_owner_acl_is_current_user_only(descriptor)
            ):
                raise PermissionError(
                    f"{subject} requires a bounded current-user-only file"
                )
            data = bytearray()
            while chunk := os.read(descriptor, min(8192, max_bytes + 1 - len(data))):
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise PermissionError(f"{subject} exceeds its byte bound")
            after = os.fstat(descriptor)
            if (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ) or len(data) != before.st_size:
                raise PermissionError(f"{subject} changed during inspection")
            return bytes(data)
    except (WorkspaceFileChangedError, WorkspaceHardLinkError, WorkspaceReadLimitError):
        raise PermissionError(f"{subject} is not an admitted owner-only file") from None


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

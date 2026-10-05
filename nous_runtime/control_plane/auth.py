# -*- coding: utf-8 -*-
"""
Control Plane Auth — loopback API session authentication.

Generates a random session token at startup for local desktop auth.
The token is written to a file that only the desktop app (Tauri sidecar
process) can read. No token = no API access for mutation endpoints.

Security properties:
- Random per-startup token (not persistent, not predictable)
- Token file permissions: owner-read-only
- Token is not logged and is never persisted in configuration
- Strict CORS: only 127.0.0.1 / ::1
- Token is passed via Authorization: Bearer <token> header
"""

from __future__ import annotations

import getpass
import logging
import os
import secrets
import stat
import tempfile
from typing import Any

from nous_runtime.security.private_files import restrict_owner_only_file

log = logging.getLogger("nous.control_plane.auth")


def session_token_path() -> str:
    """Return the deterministic local path used for the desktop session token."""
    override = os.environ.get("NOUS_SESSION_TOKEN_FILE", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    else:
        root = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(root, "Nous", "runtime-session.token")


def _windows_acl_identity() -> str:
    """Return the current Windows identity accepted by icacls."""
    username = os.environ.get("USERNAME", "").strip() or getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "").strip()
    return f"{domain}\\{username}" if domain else username


def _restrict_token_permissions(path: str) -> None:
    """Restrict a token file to the current OS identity or fail closed."""
    restrict_owner_only_file(path, subject="session token")


def _set_owner_only_windows_acl(path: str) -> None:
    """Compatibility wrapper for the shared owner-only file policy."""
    restrict_owner_only_file(path, subject="session token")


class ControlPlaneAuth:
    """
    Manages the loopback session token for desktop-sidecar auth.

    On startup:
    1. Generate a random 64-hex-char token
    2. Write it to a temp file with restricted permissions
    3. Set NOUS_API_TOKEN env var so the existing auth system works
    4. The Tauri sidecar reads this file to get the token

    On shutdown:
    1. Delete the token file
    2. Clear the env var
    """

    _instance: ControlPlaneAuth | None = None

    def __init__(self):
        self._token: str | None = None
        self._token_file: str | None = None

    @classmethod
    def get(cls) -> ControlPlaneAuth:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def token_file(self) -> str | None:
        return self._token_file

    def generate(self) -> str:
        """Generate a new session token and make it available."""
        candidate = secrets.token_hex(32)  # 64 hex chars, 256 bits entropy
        self._token = candidate
        try:
            self._write_token_file()
        except Exception:
            self._token = None
            os.environ.pop("NOUS_API_TOKEN", None)
            self._cleanup_token_file()
            raise
        os.environ["NOUS_API_TOKEN"] = candidate
        log.info("Control Plane session token generated")
        return candidate

    def revoke(self):
        """Revoke the current token."""
        self._token = None
        os.environ.pop("NOUS_API_TOKEN", None)
        self._cleanup_token_file()
        log.info("Control Plane session token revoked")

    def _write_token_file(self):
        """Atomically write a session token with verified owner-only access."""
        token_path = session_token_path()
        directory = os.path.dirname(token_path)
        os.makedirs(directory, exist_ok=True)
        if os.name != "nt":
            os.chmod(directory, stat.S_IRWXU)

        descriptor = -1
        temporary_path = ""
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".runtime-session.",
                suffix=".tmp",
                dir=directory,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
                descriptor = -1
                token_file.write(self._token or "")
                token_file.flush()
                os.fsync(token_file.fileno())
            _restrict_token_permissions(temporary_path)
            os.replace(temporary_path, token_path)
            temporary_path = ""
            _restrict_token_permissions(token_path)
            self._token_file = token_path
            log.info("Control Plane session token file created")
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
            if os.path.exists(token_path):
                os.unlink(token_path)
            raise

    def _cleanup_token_file(self):
        """Remove the token file."""
        if self._token_file and os.path.exists(self._token_file):
            try:
                os.unlink(self._token_file)
            except OSError:
                pass
        # Keep the last path observable for diagnostics while removing the file.

    def verify(self, token: str) -> bool:
        """Verify a token against the current session token (constant-time)."""
        import hmac

        if not self._token:
            return False
        return hmac.compare_digest(token, self._token)


# CORS Configuration


CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "X-Auth-Token",
    "X-Request-Id",
    "X-Correlation-Id",
    "X-Idempotency-Key",
    "X-Control-Nonce",
]
CORS_MAX_AGE = 3600


def add_cors_headers(
    response_headers: dict[str, str], request_origin: str | None = None
):
    """Add CORS headers to an HTTP response."""
    origin = request_origin or "tauri://localhost"
    # Explicit host-owned deployment configuration, never request-supplied trust.
    import json
    from urllib.parse import urlsplit

    configured_origins = json.loads(os.environ.get("NOUS_CONTROL_ORIGINS", "[]"))
    if not isinstance(configured_origins, list) or any(
        not isinstance(item, str)
        or not item.startswith("https://")
        or "*" in item
        or not urlsplit(item).hostname
        or urlsplit(item).username
        or urlsplit(item).password
        or urlsplit(item).path
        or urlsplit(item).query
        or urlsplit(item).fragment
        for item in configured_origins
    ):
        raise ValueError("Remote console origins must be explicit HTTPS origins")

    # Wildcard entries match a numeric port only. Prefix-only matching would
    # incorrectly allow hosts such as localhost.example.com.
    allowed = False
    for allowed_origin in [*CORS_ALLOWED_ORIGINS, *configured_origins]:
        if allowed_origin.endswith(":*"):
            prefix = allowed_origin[:-1]
            if origin.startswith(prefix) and origin[len(prefix) :].isdigit():
                allowed = True
                break
        elif origin == allowed_origin:
            allowed = True
            break

    if not allowed:
        return  # Don't add CORS headers for disallowed origins

    response_headers["Access-Control-Allow-Origin"] = origin
    response_headers["Access-Control-Allow-Methods"] = ", ".join(CORS_ALLOWED_METHODS)
    response_headers["Access-Control-Allow-Headers"] = ", ".join(CORS_ALLOWED_HEADERS)
    response_headers["Access-Control-Max-Age"] = str(CORS_MAX_AGE)
    response_headers["Access-Control-Allow-Credentials"] = "true"


def handle_cors_preflight() -> dict[str, Any]:
    """Handle CORS preflight (OPTIONS) requests."""
    return {
        "status": 204,
        "headers": {
            "Access-Control-Allow-Methods": ", ".join(CORS_ALLOWED_METHODS),
            "Access-Control-Allow-Headers": ", ".join(CORS_ALLOWED_HEADERS),
            "Access-Control-Max-Age": str(CORS_MAX_AGE),
        },
    }


# Token-based auth integration


def integrate_with_existing_auth():
    """
    Hook into the existing API auth system to use Control Plane tokens.

    This makes the existing _authentication_context() in routes.py
    accept the Control Plane session token in addition to NOUS_API_TOKEN.
    """
    auth = ControlPlaneAuth.get()
    if not auth.token:
        auth.generate()

    # The token is already set as NOUS_API_TOKEN via os.environ,
    # so the existing routes.py auth system will accept it automatically.

    log.info("Control Plane auth integrated with existing API auth")

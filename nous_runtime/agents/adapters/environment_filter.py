# -*- coding: utf-8 -*-
"""EnvironmentFilter — sanitizes environment variables for agent execution."""

from __future__ import annotations

import os
import re

# Sensitive environment variable name patterns
_SENSITIVE_PATTERNS: tuple[str, ...] = (
    r"(?i).*api[_-]?key.*",
    r"(?i).*secret.*",
    r"(?i).*token.*",
    r"(?i).*password.*",
    r"(?i).*credential.*",
    r"(?i).*private[_-]?key.*",
    r"(?i).*auth.*",
    r"(?i).*signing[_-]?key.*",
)

# Always blocked variables
_ALWAYS_BLOCKED: tuple[str, ...] = (
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
)


def _is_sensitive(name: str) -> bool:
    for pattern in _SENSITIVE_PATTERNS:
        if re.match(pattern, name):
            return True
    return False


class EnvironmentFilter:
    """Builds a sanitized environment for agent subprocess execution.

    Requirements:
    - Start from an allowlist (or minimally filtered base)
    - Redact secrets
    - Block user-home and profile variables
    - Allow explicit additions from the descriptor
    """

    def __init__(
        self,
        *,
        allowlist: tuple[str, ...] = (),
        blocklist: tuple[str, ...] = (),
    ):
        self._allowlist: tuple[str, ...] = allowlist
        self._blocklist: tuple[str, ...] = blocklist or _ALWAYS_BLOCKED

    def build_env(self, *, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build a sanitized environment dictionary.

        Strategy:
        1. Start empty (safest default)
        2. Add whitelisted variables from allowlist
        3. Add platform-required variables
        4. Overlay extras from descriptor
        5. Remove anything matching sensitive patterns
        """
        env: dict[str, str] = {}

        # Platform-required variables
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "C:\\Windows")
            env["SYSTEMDRIVE"] = os.environ.get("SYSTEMDRIVE", "C:")
            env["COMSPEC"] = os.environ.get("COMSPEC", "cmd.exe")
            env["PATHEXT"] = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
            env["WINDIR"] = os.environ.get("WINDIR", "C:\\Windows")
        else:
            env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
            env["HOME"] = "/tmp"

        # Allowlist: copy from current environment
        for key in self._allowlist:
            if key in os.environ and key not in self._blocklist:
                if not _is_sensitive(key):
                    env[key] = os.environ[key]

        # Overlay extras
        if extra:
            for key, value in extra.items():
                if key not in self._blocklist and not _is_sensitive(key):
                    env[key] = value

        # LANG and locale
        if "LANG" not in env:
            env["LANG"] = os.environ.get("LANG", "en_US.UTF-8")

        return env

    def redact_value(self, key: str, value: str) -> str:
        """Redact a value if it appears to contain a secret."""
        if _is_sensitive(key):
            return "<REDACTED>"
        return value

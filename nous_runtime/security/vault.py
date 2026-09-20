# -*- coding: utf-8 -*-
"""
Secret Vault for Nous Runtime.

Implements §18.3 of the master plan. Secrets (API keys, tokens, signing keys)
are never:
- Written into normal config
- Written into logs
- Sent to irrelevant nodes
- Entered into model context

Only SecretRef handles are passed around. The Vault encrypts secrets at rest
and provides rotation and revocation support.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.kernel.identity import SecretRef
from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.security.vault")


# Encryption helpers

def _derive_key(master_key: bytes, salt: bytes) -> bytes:
    """Derive an encryption key using HKDF-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", master_key, salt, 100000, dklen=32)


def _encrypt(plaintext: str, master_key: bytes) -> tuple[bytes, bytes, bytes]:
    """Encrypt plaintext with AES-256-GCM. Returns (ciphertext, nonce, salt)."""
    from nous_runtime.security.native_aead import encrypt_aes_gcm

    salt = os.urandom(16)
    key = _derive_key(master_key, salt)
    nonce = os.urandom(12)
    ciphertext = encrypt_aes_gcm(key, nonce, plaintext.encode("utf-8"))
    return ciphertext, nonce, salt


def _decrypt(ciphertext: bytes, nonce: bytes, salt: bytes, master_key: bytes) -> str:
    """Decrypt ciphertext encrypted with _encrypt."""
    from nous_runtime.security.native_aead import decrypt_aes_gcm

    key = _derive_key(master_key, salt)
    return decrypt_aes_gcm(key, nonce, ciphertext).decode("utf-8")


# Vault Entry

@dataclass
class VaultEntry:
    """A single secret stored in the vault."""
    entry_id: str = field(default_factory=lambda: make_id(prefix="secret"))
    path: str = ""                       # e.g., "providers/openai/api_key"
    encrypted_value: bytes = b""
    nonce: bytes = b""
    salt: bytes = b""
    key_id: str = ""                     # Which master key encrypted this
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""                 # user_id
    rotated_at: str | None = None
    expires_at: str | None = None
    revoked: bool = False
    metadata: dict[str, str] = field(default_factory=dict)  # e.g., {"provider": "openai"}


class SecretVault:
    """Encrypted secret storage with access control.

    Secrets are encrypted at rest using AES-256-GCM. The master key is
    derived from an environment variable or filesystem key.
    """

    def __init__(self, db_path: str, master_key: bytes | None = None):
        self._db_path = db_path
        self._lock = threading.RLock()

        # Master key: from env var or generate for development
        if master_key:
            self._master_key = master_key
        else:
            env_key = os.environ.get("NOUS_VAULT_KEY", "")
            if env_key:
                self._master_key = base64.b64decode(env_key)
            else:
                # Development: derive from machine-specific data
                machine_id = hashlib.sha256(
                    (os.environ.get("COMPUTERNAME", "") +
                     os.environ.get("USER", "") +
                     str(os.getpid())).encode()
                ).digest()
                self._master_key = machine_id
                log.warning("Using derived master key — set NOUS_VAULT_KEY for production")

        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with closing(self._get_conn()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vault (
                    entry_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    encrypted_value BLOB NOT NULL,
                    nonce BLOB NOT NULL,
                    salt BLOB NOT NULL,
                    key_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL DEFAULT '',
                    rotated_at TEXT,
                    expires_at TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_path ON vault(path)")
            conn.commit()

    # CRUD

    def put(self, path: str, value: str, created_by: str = "",
            metadata: dict[str, str] | None = None) -> NousResult[SecretRef]:
        """Store a secret. Overwrites if path already exists."""
        with self._lock:
            try:
                ciphertext, nonce, salt = _encrypt(value, self._master_key)
                key_id = hashlib.sha256(self._master_key).hexdigest()[:16]
                entry_id = make_id(prefix="secret")

                with closing(self._get_conn()) as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO vault
                           (entry_id, path, encrypted_value, nonce, salt, key_id,
                            created_at, created_by, metadata)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            entry_id, path, ciphertext, nonce, salt, key_id,
                            datetime.now(timezone.utc).isoformat(),
                            created_by,
                            json.dumps(metadata or {}),
                        ),
                    )
                    conn.commit()

                ref = SecretRef(vault_path=path, key_id=key_id)
                return NousResult.ok(ref)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def get(self, path: str) -> NousResult[str]:
        """Retrieve and decrypt a secret."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    row = conn.execute(
                        "SELECT * FROM vault WHERE path = ? AND revoked = 0",
                        (path,),
                    ).fetchone()
                if row is None:
                    return NousResult.err(
                        ErrorCode.NOT_FOUND,
                        message=f"Secret '{path}' not found",
                    )
                plaintext = _decrypt(
                    row["encrypted_value"], row["nonce"], row["salt"],
                    self._master_key,
                )
                return NousResult.ok(plaintext)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def delete(self, path: str) -> NousResult[None]:
        """Revoke (soft-delete) a secret."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    conn.execute(
                        "UPDATE vault SET revoked = 1 WHERE path = ?",
                        (path,),
                    )
                    conn.commit()
                return NousResult.ok(None)
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def list_paths(self) -> NousResult[list[str]]:
        """List all active secret paths (values NOT returned)."""
        with self._lock:
            try:
                with closing(self._get_conn()) as conn:
                    rows = conn.execute(
                        "SELECT path FROM vault WHERE revoked = 0 ORDER BY path"
                    ).fetchall()
                return NousResult.ok([r["path"] for r in rows])
            except Exception as e:
                return NousResult.err(ErrorCode.INTERNAL, message=str(e))

    def rotate(self, path: str, new_value: str) -> NousResult[SecretRef]:
        """Rotate a secret to a new value."""
        result = self.put(path, new_value,
                          created_by="rotation",
                          metadata={"rotated": "true"})
        if result.ok:
            log.info("Secret rotated: %s", path)
        return result

    def health(self) -> NousResult[dict[str, Any]]:
        """Check vault health (can encrypt/decrypt)."""
        try:
            test_path = "__health_check__"
            test_value = "health_check_" + make_id(prefix="test")
            put_result = self.put(test_path, test_value)
            if not put_result.ok:
                return NousResult.err(ErrorCode.DEGRADED, message="Vault write failed")
            get_result = self.get(test_path)
            if not get_result.ok:
                return NousResult.err(ErrorCode.DEGRADED, message="Vault read failed")
            self.delete(test_path)
            return NousResult.ok({"status": "ok"})
        except Exception as e:
            return NousResult.err(ErrorCode.INTERNAL, message=str(e))

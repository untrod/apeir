"""Authenticated AES-GCM backend with a Windows CNG fallback.

The cryptography package remains the preferred cross-platform implementation.
Windows ARM64 Python distributions do not always have a compatible wheel, so
Nous uses the operating system's BCrypt AES-GCM provider when that optional
package is unavailable.
"""

from __future__ import annotations

import sys

_TAG_BYTES = 16


def encrypt_aes_gcm(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """Return ciphertext with the 16-byte GCM authentication tag appended."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        if sys.platform != "win32":
            raise RuntimeError(
                "AES-GCM requires the cryptography package on this platform"
            ) from None
        return _cng_crypt(key, nonce, plaintext, decrypt=False)
    return AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_aes_gcm(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Verify and decrypt ciphertext produced by :func:`encrypt_aes_gcm`."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        if sys.platform != "win32":
            raise RuntimeError(
                "AES-GCM requires the cryptography package on this platform"
            ) from None
        return _cng_crypt(key, nonce, ciphertext, decrypt=True)
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _cng_crypt(key: bytes, nonce: bytes, data: bytes, *, decrypt: bool) -> bytes:
    """Encrypt/decrypt with the Windows BCrypt AES-GCM provider."""
    import ctypes
    from ctypes import wintypes

    if len(key) not in {16, 24, 32}:
        raise ValueError("AES key must be 128, 192, or 256 bits")
    if not nonce:
        raise ValueError("AES-GCM nonce must not be empty")
    if decrypt and len(data) < _TAG_BYTES:
        raise ValueError("AES-GCM ciphertext is missing its authentication tag")

    uchar_p = ctypes.POINTER(ctypes.c_ubyte)

    class AuthInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.ULONG),
            ("dwInfoVersion", wintypes.ULONG),
            ("pbNonce", uchar_p),
            ("cbNonce", wintypes.ULONG),
            ("pbAuthData", uchar_p),
            ("cbAuthData", wintypes.ULONG),
            ("pbTag", uchar_p),
            ("cbTag", wintypes.ULONG),
            ("pbMacContext", uchar_p),
            ("cbMacContext", wintypes.ULONG),
            ("cbAAD", wintypes.ULONG),
            ("cbData", ctypes.c_ulonglong),
            ("dwFlags", wintypes.ULONG),
        ]

    bcrypt = ctypes.WinDLL("bcrypt", use_last_error=True)
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_wchar_p,
        ctypes.c_wchar_p, wintypes.ULONG,
    ]
    bcrypt.BCryptOpenAlgorithmProvider.restype = ctypes.c_long
    bcrypt.BCryptSetProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, uchar_p,
        wintypes.ULONG, wintypes.ULONG,
    ]
    bcrypt.BCryptSetProperty.restype = ctypes.c_long
    bcrypt.BCryptGenerateSymmetricKey.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), uchar_p,
        wintypes.ULONG, uchar_p, wintypes.ULONG, wintypes.ULONG,
    ]
    bcrypt.BCryptGenerateSymmetricKey.restype = ctypes.c_long
    crypt_function = bcrypt.BCryptDecrypt if decrypt else bcrypt.BCryptEncrypt
    crypt_function.argtypes = [
        ctypes.c_void_p, uchar_p, wintypes.ULONG, ctypes.c_void_p,
        uchar_p, wintypes.ULONG, uchar_p, wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG), wintypes.ULONG,
    ]
    crypt_function.restype = ctypes.c_long
    bcrypt.BCryptDestroyKey.argtypes = [ctypes.c_void_p]
    bcrypt.BCryptDestroyKey.restype = ctypes.c_long
    bcrypt.BCryptCloseAlgorithmProvider.argtypes = [
        ctypes.c_void_p, wintypes.ULONG,
    ]
    bcrypt.BCryptCloseAlgorithmProvider.restype = ctypes.c_long

    def check(status: int, operation: str) -> None:
        if status != 0:
            unsigned = ctypes.c_ulong(status).value
            raise RuntimeError(f"Windows CNG {operation} failed: 0x{unsigned:08X}")

    def buffer(value: bytes):
        return (ctypes.c_ubyte * len(value)).from_buffer_copy(value)

    algorithm = ctypes.c_void_p()
    key_handle = ctypes.c_void_p()
    check(
        bcrypt.BCryptOpenAlgorithmProvider(
            ctypes.byref(algorithm), "AES", None, 0
        ),
        "open AES provider",
    )
    try:
        chaining_mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        check(
            bcrypt.BCryptSetProperty(
                algorithm,
                "ChainingMode",
                ctypes.cast(chaining_mode, uchar_p),
                ctypes.sizeof(chaining_mode),
                0,
            ),
            "set GCM mode",
        )
        key_buffer = buffer(key)
        check(
            bcrypt.BCryptGenerateSymmetricKey(
                algorithm,
                ctypes.byref(key_handle),
                None,
                0,
                key_buffer,
                len(key),
                0,
            ),
            "create key",
        )
        nonce_buffer = buffer(nonce)
        if decrypt:
            payload = data[:-_TAG_BYTES]
            tag_buffer = buffer(data[-_TAG_BYTES:])
        else:
            payload = data
            tag_buffer = (ctypes.c_ubyte * _TAG_BYTES)()
        input_buffer = buffer(payload)
        output_buffer = (ctypes.c_ubyte * len(payload))()
        info = AuthInfo()
        info.cbSize = ctypes.sizeof(AuthInfo)
        info.dwInfoVersion = 1
        info.pbNonce = ctypes.cast(nonce_buffer, uchar_p)
        info.cbNonce = len(nonce)
        info.pbTag = ctypes.cast(tag_buffer, uchar_p)
        info.cbTag = _TAG_BYTES
        output_size = wintypes.ULONG()
        check(
            crypt_function(
                key_handle,
                ctypes.cast(input_buffer, uchar_p),
                len(payload),
                ctypes.byref(info),
                None,
                0,
                ctypes.cast(output_buffer, uchar_p),
                len(payload),
                ctypes.byref(output_size),
                0,
            ),
            "decrypt" if decrypt else "encrypt",
        )
        output = bytes(output_buffer[: output_size.value])
        return output if decrypt else output + bytes(tag_buffer)
    finally:
        if key_handle.value:
            bcrypt.BCryptDestroyKey(key_handle)
        if algorithm.value:
            bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)


__all__ = ["encrypt_aes_gcm", "decrypt_aes_gcm"]
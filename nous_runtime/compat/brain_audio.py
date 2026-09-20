# -*- coding: utf-8 -*-
"""Compatibility shim for brain.py audio functions.

Provides _get_whisper and _get_whisper_cmd without importing brain.py directly.
Once brain.py is fully decomposed, this module can be replaced by native
implementations in nous_runtime/provider/adapters/audio.py.
"""

from __future__ import annotations

import logging

log = logging.getLogger("nous.compat.brain_audio")

_WHISPER_MODEL = None
_WHISPER_CMD_MODEL = None


def _get_whisper():
    """Lazy-load and cache the faster-whisper model (medium)."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL

    # Try the compat path first (brain.py may define these)
    try:
        from remote_terminal.brain import _get_whisper as _orig
        _WHISPER_MODEL = _orig()
        return _WHISPER_MODEL
    except (ImportError, AttributeError):
        pass

    # Fallback: load directly
    try:
        from faster_whisper import WhisperModel
        _WHISPER_MODEL = WhisperModel("medium", device="cpu", compute_type="int8")
        return _WHISPER_MODEL
    except ImportError:
        log.warning("faster-whisper not installed; speech-to-text unavailable")
        raise


def _get_whisper_cmd():
    """Lazy-load the faster-whisper model (base) for command recognition."""
    global _WHISPER_CMD_MODEL
    if _WHISPER_CMD_MODEL is not None:
        return _WHISPER_CMD_MODEL

    try:
        from remote_terminal.brain import _get_whisper_cmd as _orig
        _WHISPER_CMD_MODEL = _orig()
        return _WHISPER_CMD_MODEL
    except (ImportError, AttributeError):
        pass

    try:
        from faster_whisper import WhisperModel
        _WHISPER_CMD_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
        return _WHISPER_CMD_MODEL
    except ImportError:
        log.warning("faster-whisper not installed; speech-to-text unavailable")
        raise

# -*- coding: utf-8 -*-
"""Audio Providers -model.transcribe (whisper), model.tts (edge-tts)."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.audio")


class WhisperProvider(Provider):
    """Provider for speech-to-text via faster-whisper."""

    name = "whisper"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["model.transcribe"]

    def invoke(self, capability_id: str, **params) -> dict:
        audio_path = params.get("audio_path", "")
        try:
            from nous_runtime.compat.brain_audio import _get_whisper, _get_whisper_cmd
            model = _get_whisper_cmd() if params.get("use_base") else _get_whisper()
            segments, _ = model.transcribe(audio_path, language="zh")
            text = " ".join(s.text for s in segments)
            return {"ok": True, "text": text}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        try:
            from nous_runtime.compat.brain_audio import _get_whisper
            _get_whisper()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}


class EdgeTTSProvider(Provider):
    """Provider for text-to-speech via edge-tts."""

    name = "edge_tts"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["model.tts"]

    def invoke(self, capability_id: str, **params) -> dict:
        text = params.get("text", "")
        voice = params.get("voice", "zh-CN-XiaoxiaoNeural")
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                out = f.name
            subprocess.run(
                ["edge-tts", "--voice", voice, "--text", text, "--write-media", out],
                capture_output=True, timeout=30,
            )
            return {"ok": True, "audio_path": out}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        try:
            subprocess.run(["edge-tts", "--help"], capture_output=True, timeout=5)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

# -*- coding: utf-8 -*-
"""
Provider adapters — concrete Provider implementations.

Each adapter wraps an external system (model API, device agent, storage
backend) as a Provider that can be registered with the runtime.

Adapters in this package:
    openai          — LLM reasoning (model.reason, model.code)
    embed           — Text embedding (model.embed)
    audio           — Speech-to-text + text-to-speech (model.transcribe, model.tts)
    chromadb        — Vector search + indexing (rag.search, rag.index)
    device_pc       — PC command execution (device.pc.*)
    device_android  — Phone/watch control (device.phone.*, device.watch.*)
    notification    — Notification dispatch (notification.send)
    web             — Web search + fetch (tool.web_search, tool.web_fetch)
"""

from __future__ import annotations

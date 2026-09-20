# -*- coding: utf-8 -*-
"""hello_pack — A Nous Runtime pack"""

from __future__ import annotations


def register(pack):
    """Called when the pack is installed."""
    from remote_terminal.nous_core.provider import register_adapter
    from .providers import HelloProvider
    register_adapter(HelloProvider())
    pack.registered_providers.append("HelloProvider")

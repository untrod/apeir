# -*- coding: utf-8 -*-
"""Tests for hello_pack providers."""


def test_hello_provider():
    from .src.providers import HelloProvider

    p = HelloProvider()
    caps = p.list_capabilities()
    assert "hello_pack.hello" in caps

    result = p.invoke("hello_pack.hello")
    assert result["ok"] is True
    assert "message" in result

    health = p.health()
    assert health["status"] == "ok"

# -*- coding: utf-8 -*-
"""Provider Router tests."""

from nous_runtime.provider.router import RoutingPreference, route_with_explanation


class TestRouter:
    def test_routing_preference_defaults(self):
        prefs = RoutingPreference()
        assert prefs.speed == "balanced"
        assert prefs.privacy == "balanced"

    def test_routing_preference_privacy(self):
        prefs = RoutingPreference(privacy="high")
        assert prefs.privacy == "high"

    def test_route_nonexistent_capability(self):
        result = route_with_explanation("nonexistent.capability")
        assert result["selected"] is None
        assert result["candidates"] == []

    def test_route_with_explanation(self):
        result = route_with_explanation("model.reason")
        assert "capability_id" in result
        assert "candidates" in result
        # May or may not have a provider depending on test environment

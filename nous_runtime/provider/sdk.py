# -*- coding: utf-8 -*-
"""
Provider SDK — base classes and tools for building new providers.

Implements §10.4 of the master plan. Provides:
- Adapter base class with standard lifecycle
- Manifest schema for provider declaration
- Conformance test suite for validating new providers
- Compatibility levels
- Error normalization
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.kernel.error_codes import ErrorCode, NousResult

log = logging.getLogger("nous.provider.sdk")


# Compatibility Level

class CompatibilityLevel(str, Enum):
    """How compatible a provider is with the Nous unified contract."""
    NATIVE = "native"                # Full Nous contract support
    COMPATIBLE = "compatible"       # OpenAI/Anthropic-compatible, minor gaps
    PARTIAL = "partial"             # Some capabilities missing
    EXPERIMENTAL = "experimental"   # Untested, may break
    LEGACY = "legacy"              # Old adapter, needs migration


# Provider Manifest

@dataclass
class ProviderManifest:
    """Declares what a provider supports and how to use it."""
    provider_id: str = ""
    provider_name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    homepage: str = ""
    compatibility: CompatibilityLevel = CompatibilityLevel.COMPATIBLE

    # Supported capabilities
    capabilities: list[str] = field(default_factory=list)  # model.chat, model.stream, etc.

    # Connection
    endpoint: str = ""
    default_model: str = ""
    models: list[str] = field(default_factory=list)

    # Requirements
    requires_credential: bool = True
    credential_type: str = "api_key"     # api_key | oauth | none
    requires_network: bool = True

    # Limits
    max_context_tokens: int = 8192
    max_output_tokens: int = 4096
    rate_limit_per_minute: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "compatibility": self.compatibility.value,
            "capabilities": self.capabilities,
            "endpoint": self.endpoint,
            "default_model": self.default_model,
            "models": self.models,
            "max_context_tokens": self.max_context_tokens,
            "max_output_tokens": self.max_output_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def load(cls, path: str) -> "ProviderManifest":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# Provider Adapter (ABC)

class ProviderAdapter(ABC):
    """Standard base class for all Nous provider adapters.

    Subclass this to add a new model provider. Does NOT require
    modifying Runtime Core, Task Runtime, or UI (§10.4).

    Required overrides:
        manifest -> ProviderManifest
        invoke(capability_id, **params) -> dict
        health() -> dict
    """

    @property
    @abstractmethod
    def manifest(self) -> ProviderManifest:
        ...

    @abstractmethod
    def invoke(self, capability_id: str, **params) -> dict:
        """Execute a capability. Must return {"ok": True/False, ...}."""
        ...

    @abstractmethod
    def health(self) -> dict:
        """Return {"status": "ok"|"degraded"|"down", ...}."""
        ...

    def stream_invoke(self, capability_id: str, **params):
        """Optional: yield token dicts for streaming."""
        result = self.invoke(capability_id, **params)
        if result.get("ok"):
            text = result.get("text", result.get("content", ""))
            for word in text.split():
                yield {"token": word + " "}
        else:
            yield {"error": result.get("error", "unknown")}

    def validate(self) -> NousResult[list[str]]:
        """Run basic validation on this provider."""
        issues = []
        m = self.manifest

        if not m.provider_id:
            issues.append("provider_id is required")
        if not m.provider_name:
            issues.append("provider_name is required")
        if not m.capabilities:
            issues.append("At least one capability is required")

        # Validate each capability
        for cap in m.capabilities:
            try:
                result = self.invoke(cap, test_mode=True)
                if not isinstance(result, dict):
                    issues.append(f"invoke({cap}) returned non-dict: {type(result)}")
            except Exception as e:
                issues.append(f"invoke({cap}) raised: {e}")

        if issues:
            return NousResult.err(ErrorCode.INVALID_ARGUMENT,
                                  message=f"{len(issues)} validation issues",
                                  details={"issues": issues})
        return NousResult.ok([])


# Conformance Tests

class ConformanceTestSuite:
    """Standard tests to validate a provider implementation.

    Run against any new provider to verify it meets the Nous contract.
    """

    def __init__(self, adapter: ProviderAdapter):
        self._adapter = adapter

    def run_all(self) -> dict[str, bool]:
        """Run all conformance tests. Returns {test_name: passed}."""
        results = {}
        for name in dir(self):
            if name.startswith("test_"):
                try:
                    getattr(self, name)()
                    results[name] = True
                except Exception as e:
                    results[name] = False
                    log.warning("Conformance test %s failed: %s", name, e)
        return results

    def test_manifest_valid(self) -> None:
        m = self._adapter.manifest
        assert m.provider_id, "provider_id required"
        assert m.provider_name, "provider_name required"
        assert m.version, "version required"
        assert len(m.capabilities) > 0, "at least one capability required"

    def test_health_returns_dict(self) -> None:
        h = self._adapter.health()
        assert isinstance(h, dict), "health() must return dict"
        assert "status" in h, "health() must have status"

    def test_invoke_returns_dict(self) -> None:
        for cap in self._adapter.manifest.capabilities[:3]:
            result = self._adapter.invoke(cap, test_mode=True)
            assert isinstance(result, dict), f"invoke({cap}) must return dict"
            assert "ok" in result, f"invoke({cap}) must have 'ok' key"

    def test_manifest_serialization(self) -> None:
        d = self._adapter.manifest.to_dict()
        assert isinstance(d, dict)
        restored = ProviderManifest.from_dict(d)
        assert restored.provider_id == self._adapter.manifest.provider_id

    def test_stream_yields_dicts(self) -> None:
        if "model.stream" in self._adapter.manifest.capabilities:
            gen = self._adapter.stream_invoke("model.stream", test_mode=True,
                                              messages=[{"role": "user", "content": "hi"}],
                                              max_tokens=5)
            items = list(gen)
            if items:
                assert isinstance(items[0], dict), "stream must yield dicts"

    def test_error_response_format(self) -> None:
        """Invoke with invalid capability should return error dict."""
        result = self._adapter.invoke("nonexistent.capability")
        assert isinstance(result, dict)
        assert "ok" in result

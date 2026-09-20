"""
Clean-Room Test 1: Remote Model Provider

This provider registers an OpenAI-compatible remote LLM API as a Nous Engine.
It uses ONLY the public Provider SDK and NKI client — no kernel internals.

To verify this is truly clean-room:
    grep -r "kernel/" provider.py  # Should return nothing
    grep -r "nousd" provider.py    # Only in NKI endpoint context
    grep -r "journal" provider.py  # Should return nothing

Usage:
    # Start nousd first, then:
    python provider.py

Pass criteria:
    - Registers without kernel modification
    - Passes `nous-ctk run --suite provider-sdk --level DISCOVERABLE`
"""

import os
import time
from typing import Optional

# ── ONLY imports from the PUBLIC SDK ──
# These are the ONLY imports a third party needs.
from nous_provider import (
    # Provider interfaces
    DiscoveryProvider,
    ExecutionProvider,
    TelemetryProvider,
    ProviderPackage,
    register_provider,
    # Public types
    Device,
    DeviceSpec,
    DeviceStatus,
    DevicePhase,
    DeviceType,
    DeviceClass,
    ResourceVector,
)


# ── Remote Model Provider Implementation ──


class RemoteModelProvider(DiscoveryProvider, ExecutionProvider, TelemetryProvider):
    """
    An OpenAI-compatible remote LLM provider.

    This demonstrates the minimum a third party needs to implement:
    1. Discovery: describe the remote engine as a "device"
    2. Execution: forward inference requests to the remote API
    3. Telemetry: report basic health
    """

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: str = "",
        model_name: str = "gpt-4o",
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model_name = model_name
        self._device_id = f"dev-remote-{model_name.replace('.', '-')}"
        self._start_time = time.time()

    # ── DiscoveryProvider ──

    def discover(self) -> list[Device]:
        """Register the remote API as a discoverable engine."""
        device = Device(
            device_id=self._device_id,
            spec=DeviceSpec(
                device_type=DeviceType.REMOTE,
                vendor="OpenAI" if "openai" in self.api_base else "Remote",
                model=self.model_name,
                driver_version="HTTP/1.1",
                architecture="cloud-api",
                total_resources=ResourceVector(
                    # Remote API: virtually unlimited from local perspective
                    ram_bytes=0,
                    device_memory_bytes=0,
                ),
                capabilities=("chat", "completion", "streaming", "structured_output"),
                supported_engines=("openai-compatible",),
                supported_dtypes=("bf16", "fp16", "fp32"),
                compute_units=0,
            ),
            status=DeviceStatus(
                phase=DevicePhase.READY,
                available=ResourceVector(),
            ),
            device_class=DeviceClass(vendor="remote", runtime="llm", tier="api"),
            labels={
                "api_base": self.api_base,
                "model": self.model_name,
            },
        )
        return [device]

    def probe(self, device_id: str) -> Optional[Device]:
        """Probe the remote API health."""
        if device_id != self._device_id:
            return None
        # Check if the API is reachable
        import urllib.request
        import json

        try:
            req = urllib.request.Request(
                f"{self.api_base}/models",
                headers={"Authorization": f"Bearer {self.api_key}"}
                if self.api_key
                else {},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                available = any(
                    m.get("id") == self.model_name for m in data.get("data", [])
                )
        except Exception:
            available = False

        devices = self.discover()
        if devices:
            device = devices[0]
            device.status.phase = DevicePhase.READY if available else DevicePhase.FAILED
            device.status.last_health_check = time.time()
            return device
        return None

    # ── ExecutionProvider ──

    def load(self, model_id: str, device_id: str, config: dict) -> bool:
        """Remote APIs don't need explicit model loading."""
        return True

    def infer(self, request: dict) -> dict:
        """Forward inference to the remote API."""
        import urllib.request
        import json

        messages = request.get("messages", [])
        max_tokens = request.get("max_tokens", 1024)
        temperature = request.get("temperature", 0.7)

        body = json.dumps(
            {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        choice = result.get("choices", [{}])[0]
        usage = result.get("usage", {})

        return {
            "content": choice.get("message", {}).get("content", ""),
            "finish_reason": choice.get("finish_reason", "stop"),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "model": result.get("model", self.model_name),
        }

    def unload(self, model_id: str) -> bool:
        return True

    # ── TelemetryProvider ──

    def metrics(self, device_id: str) -> dict:
        return {
            "device_id": device_id,
            "healthy": True,
            "uptime_seconds": time.time() - self._start_time,
            "api_base": self.api_base,
        }


# ── Main: Register with the Nous Kernel ──

if __name__ == "__main__":
    api_base = os.environ.get("NOUS_REMOTE_API_BASE", "https://api.openai.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("NOUS_REMOTE_MODEL", "gpt-4o")

    provider = RemoteModelProvider(api_base=api_base, api_key=api_key, model_name=model)

    package = ProviderPackage(
        name="clean-room-remote-model",
        version="1.0.0-rc7-cleanroom",
        provider_class="engine",
        discovery=provider,
        execution=provider,
        telemetry=provider,
        kernel_min="2.0.0",
        kernel_max="2.99.0",
        os_supported=["any"],
        arch_supported=["any"],
        capabilities=["chat", "completion", "streaming"],
        permissions=["network:outbound"],
        conformance_level="DISCOVERABLE",
    )

    success = register_provider(package)
    if success:
        print("✅ Clean-Room Remote Model Provider registered successfully")
        print(f"   Device ID: {provider._device_id}")
        print(f"   API Base:  {api_base}")
        print(f"   Model:     {model}")
    else:
        print("❌ Registration failed — check nousd is running")

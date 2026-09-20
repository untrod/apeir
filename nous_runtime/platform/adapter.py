# -*- coding: utf-8 -*-
"""Platform Adapter — unified cross-platform interface."""
from __future__ import annotations
import platform as _platform
from dataclasses import dataclass
from typing import Any

@dataclass
class PlatformCapabilities:
    os_name: str = ""
    has_cuda: bool = False
    has_tensorrt: bool = False
    has_gpu: bool = False
    cpu_count: int = 0
    total_ram_gb: float = 0.0
    mode: str = "cpu"  # cpu, gpu, jetson, edge

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name, "has_cuda": self.has_cuda,
            "has_tensorrt": self.has_tensorrt, "has_gpu": self.has_gpu,
            "cpu_count": self.cpu_count, "total_ram_gb": self.total_ram_gb,
            "mode": self.mode,
        }

class PlatformAdapter:
    """Detects platform capabilities and provides optimal settings."""
    def __init__(self):
        self._caps = self._detect()

    def _detect(self) -> PlatformCapabilities:
        caps = PlatformCapabilities(os_name=_platform.system())
        import os
        caps.cpu_count = os.cpu_count() or 1
        try:
            import psutil
            caps.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        except ImportError:
            pass
        # GPU detection
        try:
            import subprocess
            r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
            if r.returncode == 0:
                caps.has_gpu = True
                caps.has_cuda = True
                caps.mode = "gpu"
        except Exception:
            pass
        # Jetson detection
        if caps.os_name == "Linux" and caps.has_gpu:
            try:
                with open("/proc/device-tree/model") as f:
                    if "Jetson" in f.read() or "Tegra" in f.read():
                        caps.has_tensorrt = True
                        caps.mode = "jetson"
            except Exception:
                pass
        # ARM edge
        if _platform.machine().startswith("arm") or _platform.machine().startswith("aarch"):
            if caps.mode == "cpu":
                caps.mode = "edge"
        return caps

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._caps

    @property
    def mode(self) -> str:
        return self._caps.mode

    def gpu_available(self) -> bool:
        return self._caps.has_gpu

    def to_dict(self) -> dict[str, Any]:
        return self._caps.to_dict()

def get_platform_adapter() -> PlatformAdapter:
    return PlatformAdapter()

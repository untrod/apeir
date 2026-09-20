# -*- coding: utf-8 -*-
"""Platform detection for deployment."""
from __future__ import annotations
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

@dataclass
class PlatformInfo:
    os_name: str = ""
    os_version: str = ""
    arch: str = ""
    python_version: str = ""
    has_gpu: bool = False
    gpu_info: str = ""
    has_docker: bool = False
    has_cuda: bool = False
    total_ram_gb: float = 0.0
    disk_free_gb: float = 0.0
    is_root: bool = False
    recommendations: list[str] = None

    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name, "os_version": self.os_version, "arch": self.arch,
            "python": self.python_version, "has_gpu": self.has_gpu,
            "gpu_info": self.gpu_info, "has_docker": self.has_docker,
            "has_cuda": self.has_cuda, "total_ram_gb": self.total_ram_gb,
            "disk_free_gb": self.disk_free_gb, "is_root": self.is_root,
            "recommendations": self.recommendations,
        }

def detect_platform() -> PlatformInfo:
    info = PlatformInfo(
        os_name=platform.system(),
        os_version=platform.version(),
        arch=platform.machine(),
        python_version=sys.version.split()[0],
        is_root=os.geteuid() == 0 if hasattr(os, "geteuid") else False,
    )
    # RAM
    try:
        import psutil
        info.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        info.disk_free_gb = round(psutil.disk_usage("/").free / (1024**3), 1)
    except ImportError:
        pass
    # GPU
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            info.has_gpu = True
            info.gpu_info = result.stdout.strip()
    except Exception:
        pass
    # CUDA
    try:
        result = subprocess.run(["nvcc", "--version"], capture_output=True, timeout=5)
        info.has_cuda = result.returncode == 0
    except Exception:
        pass
    # Docker
    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
        info.has_docker = result.returncode == 0
    except Exception:
        pass
    # Recommendations
    if info.has_gpu and not info.has_cuda:
        info.recommendations.append("GPU detected but CUDA not found — install CUDA toolkit")
    if not info.has_docker:
        info.recommendations.append("Docker not found — recommended for containerized deployment")
    if info.disk_free_gb < 10:
        info.recommendations.append(f"Low disk space: {info.disk_free_gb:.1f}GB free")
    return info

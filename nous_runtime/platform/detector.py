# -*- coding: utf-8 -*-
"""
Platform detector — maps ``platform``, ``os``, and ``sys`` to PlatformInfo.

This is the ONLY module that directly imports ``platform``, ``os.uname``,
and ``sys.maxsize``. All other code must use PlatformService.
"""

from __future__ import annotations

import os as _os
import platform as _platform
import socket as _socket

from nous_runtime.platform.models import (
    ABI,
    Architecture,
    PlatformInfo,
    RuntimeTier,
    WordSize,
)


def detect_platform() -> PlatformInfo:
    """Detect the current platform and return a complete PlatformInfo."""
    machine = _platform.machine()
    arch = Architecture.from_machine(machine)
    abi = ABI.detect()
    word_size = WordSize.detect()
    tier = RuntimeTier.from_arch(arch)

    os_name = _platform.system()
    os_version = _platform.release()
    hostname = _socket.gethostname()

    # CPU info
    cpu_model = _platform.processor() or ""
    cpu_cores = _os.cpu_count() or 1

    # GPU detection (best-effort, non-blocking)
    gpu_model = ""
    gpu_memory_mb = 0
    if os_name == "Linux":
        gpu_model, gpu_memory_mb = _detect_linux_gpu()
    elif os_name == "Windows":
        gpu_model, gpu_memory_mb = _detect_windows_gpu()

    # RAM
    ram_total_mb = 0
    try:
        import psutil
        ram_total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
    except ImportError:
        pass

    # Virtual/container detection
    is_virtual = _detect_virtual()
    is_container = _detect_container()

    return PlatformInfo(
        architecture=arch,
        abi=abi,
        word_size=word_size,
        runtime_tier=tier,
        os_name=os_name,
        os_version=os_version,
        hostname=hostname,
        cpu_model=cpu_model,
        cpu_cores=cpu_cores,
        gpu_model=gpu_model,
        gpu_memory_mb=gpu_memory_mb,
        ram_total_mb=ram_total_mb,
        is_virtual=is_virtual,
        is_container=is_container,
    )


def _detect_linux_gpu() -> tuple[str, int]:
    """Best-effort GPU detection on Linux. Returns (model, memory_mb)."""
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split(",", 1)
            model = parts[0].strip() if parts else ""
            mem_str = parts[1].strip() if len(parts) > 1 else "0"
            mem_mb = int(mem_str.replace("MiB", "").replace("MB", "").strip()) if mem_str else 0
            return model, mem_mb
    except Exception:
        pass

    # Check for Jetson/Tegra
    try:
        with open("/proc/device-tree/model") as f:
            content = f.read()
            if "Jetson" in content or "Tegra" in content:
                return content.strip(), 0
    except Exception:
        pass

    return "", 0


def _detect_windows_gpu() -> tuple[str, int]:
    """Best-effort GPU detection on Windows."""
    try:
        import subprocess
        r = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name,AdapterRAM"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].strip().rsplit("  ", 1)
                model = parts[0].strip() if parts else ""
                mem_bytes = int(parts[-1].strip()) if len(parts) > 1 and parts[-1].strip().isdigit() else 0
                return model, mem_bytes // (1024 * 1024) if mem_bytes else 0
    except Exception:
        pass
    return "", 0


def _detect_virtual() -> bool:
    """Detect if running in a virtual machine."""
    if _platform.system() == "Linux":
        try:
            with open("/sys/class/dmi/id/product_name") as f:
                product = f.read().lower()
                if any(v in product for v in ("virtualbox", "vmware", "kvm", "qemu", "xen")):
                    return True
        except Exception:
            pass
        try:
            with open("/proc/cpuinfo") as f:
                if "hypervisor" in f.read().lower():
                    return True
        except Exception:
            pass
    return False


def _detect_container() -> bool:
    """Detect if running inside a container (Docker, LXC, etc.)."""
    try:
        if _os.path.exists("/.dockerenv"):
            return True
        with open("/proc/1/cgroup") as f:
            content = f.read()
            if "docker" in content or "lxc" in content or "kubepods" in content:
                return True
    except Exception:
        pass
    return False

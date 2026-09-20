# -*- coding: utf-8 -*-
"""
Platform models — canonical Architecture, ABI, WordSize, RuntimeTier definitions.

These enums are the single source of truth for all platform decisions in Nous.
No module may use raw strings like "amd64", "arm64", "aarch64" directly —
they must reference these enums or go through PlatformService.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class Architecture(str, Enum):
    """CPU instruction set architecture — the canonical set Nous supports."""
    AMD64 = "amd64"       # x86_64, Intel/AMD 64-bit
    ARM64 = "arm64"       # aarch64, ARM 64-bit (Tier 1)
    ARMV7 = "armv7"       # ARM 32-bit v7 (Tier 2 Lite)
    ARMV6 = "armv6"       # ARM 32-bit v6 (Tier 2 Lite, Raspberry Pi Zero)
    RISCV64 = "riscv64"   # RISC-V 64-bit (future, not in Tier 1 yet)

    @classmethod
    def from_machine(cls, machine: str) -> Architecture:
        """Map Python ``platform.machine()`` output to Architecture enum."""
        m = machine.lower()
        if m in ("x86_64", "amd64", "x64"):
            return cls.AMD64
        if m in ("aarch64", "arm64", "armv8"):
            return cls.ARM64
        if m.startswith("armv7") or m in ("arm", "arm32"):
            return cls.ARMV7
        if m.startswith("armv6"):
            return cls.ARMV6
        if m in ("riscv64", "riscv"):
            return cls.RISCV64
        raise ValueError(f"Unknown machine architecture: {machine}")

    @property
    def is_arm(self) -> bool:
        return self in (Architecture.ARM64, Architecture.ARMV7, Architecture.ARMV6)

    @property
    def is_64bit(self) -> bool:
        return self in (Architecture.AMD64, Architecture.ARM64, Architecture.RISCV64)

    @property
    def word_size_bits(self) -> int:
        return 64 if self.is_64bit else 32


class ABI(str, Enum):
    """Application Binary Interface."""
    GNU = "gnu"              # Linux glibc
    MUSL = "musl"            # Linux musl (Alpine, some ARM)
    ANDROID = "android"      # Android Bionic
    MSVC = "msvc"            # Windows MSVC
    GNUEABIHF = "gnueabihf"  # ARM hard-float
    GNUEABI = "gnueabi"      # ARM soft-float

    @classmethod
    def detect(cls) -> ABI:
        import platform
        system = platform.system().lower()
        if system == "windows":
            return cls.MSVC
        if system == "linux":
            machine = platform.machine().lower()
            if machine.startswith("arm"):
                try:
                    import subprocess
                    result = subprocess.run(
                        ["readelf", "-A", "/proc/self/exe"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if "Tag_ABI_VFP" in result.stdout:
                        return cls.GNUEABIHF
                except Exception:
                    pass
                return cls.GNUEABI
            try:
                import subprocess
                result = subprocess.run(
                    ["ldd", "--version"], capture_output=True, text=True, timeout=5,
                )
                if "musl" in result.stdout.lower():
                    return cls.MUSL
            except Exception:
                pass
            return cls.GNU
        return cls.GNU


class WordSize(int, Enum):
    """CPU word size in bits."""
    BITS32 = 32
    BITS64 = 64

    @classmethod
    def detect(cls) -> WordSize:
        import sys
        return cls.BITS64 if sys.maxsize > 2**32 else cls.BITS32


class RuntimeTier(str, Enum):
    """
    Runtime capability tier — determines what a node is allowed to run.

    Tier 1 (FULL):
      - All capabilities: Server Primary, desktop UI, local LLM, vector DB,
        full agent runtime, heavy inference, evaluation, experience learning.
      - Architectures: amd64, arm64.

    Tier 2 (LITE):
      - Restricted: identity, secure comms, heartbeat, capability executor,
        device adapters, offline buffer, audit, update.
      - Forbidden: desktop UI, local LLM, vector DB, heavy agent runtime,
        evaluation engine, experience learning.
      - Architectures: armv7, armv6, arm32.
    """
    FULL = "full"
    LITE = "lite"

    @classmethod
    def from_arch(cls, arch: Architecture) -> RuntimeTier:
        if arch in (Architecture.AMD64, Architecture.ARM64):
            return cls.FULL
        if arch in (Architecture.ARMV7, Architecture.ARMV6):
            return cls.LITE
        # riscv64: not yet tier-assigned, default to full for future
        return cls.FULL


# Capability allowlists per tier

# Capabilities ALWAYS allowed on Lite nodes
LITE_NODE_ALWAYS_ALLOWED: FrozenSet[str] = frozenset({
    "identity.attest",
    "identity.rotate_key",
    "connectivity.heartbeat",
    "connectivity.handshake",
    "connectivity.offline_buffer",
    "capability.execute",
    "device.adapter.scan",
    "device.adapter.read",
    "device.adapter.write",
    "audit.log",
    "audit.export",
    "update.check",
    "update.download",
    "update.apply",
    "update.rollback",
    "security.verify_signature",
    "security.tls_terminate",
})

# Capabilities FORBIDDEN on Lite nodes
LITE_NODE_RESTRICTED_CAPABILITIES: FrozenSet[str] = frozenset({
    "model.invoke",
    "model.invoke.local",
    "model.stream",
    "model.load",
    "model.unload",
    "inference.local",
    "inference.llama_cpp",
    "inference.ollama",
    "vector.search",
    "vector.index",
    "vector.embed",
    "chromadb.query",
    "desktop.ui",
    "desktop.render",
    "desktop.notification",
    "agent.runtime",          # Heavy agent runtime
    "agent.planner",
    "agent.evaluator",
    "evaluation.run",
    "evaluation.report",
    "experience.learn",
    "experience.recommend",
    "context.build_large",
    "retrieval.index_large",
    "training.fine_tune",
    "training.lora",
})

# All capabilities (union = no restriction)
ALL_CAPABILITIES: FrozenSet[str] = LITE_NODE_ALWAYS_ALLOWED | LITE_NODE_RESTRICTED_CAPABILITIES


# PlatformInfo dataclass

@dataclass(frozen=True)
class PlatformInfo:
    """Complete platform description used by Node identity, Scheduler, and Evidence."""
    architecture: Architecture
    abi: ABI
    word_size: WordSize
    runtime_tier: RuntimeTier
    os_name: str               # "Linux", "Windows", "Darwin"
    os_version: str            # kernel or build version
    hostname: str
    cpu_model: str = ""
    cpu_cores: int = 0
    gpu_model: str = ""
    gpu_memory_mb: int = 0
    ram_total_mb: int = 0
    is_virtual: bool = False
    is_container: bool = False
    lite_node_id: str = ""     # Only set for Lite nodes in offline buffer mode

    @classmethod
    def create(cls, **overrides: str | int | bool) -> PlatformInfo:
        """Create PlatformInfo by detecting the current platform."""
        from nous_runtime.platform.detector import detect_platform
        info = detect_platform()
        # Apply any overrides
        overrides_dict = {k: v for k, v in overrides.items() if hasattr(info, k)}
        return dataclass.replace(info, **overrides_dict) if overrides_dict else info

    def to_dict(self) -> dict:
        return {
            "architecture": self.architecture.value,
            "abi": self.abi.value,
            "word_size": self.word_size.value,
            "runtime_tier": self.runtime_tier.value,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "hostname": self.hostname,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "gpu_model": self.gpu_model,
            "gpu_memory_mb": self.gpu_memory_mb,
            "ram_total_mb": self.ram_total_mb,
            "is_virtual": self.is_virtual,
            "is_container": self.is_container,
            "lite_node_id": self.lite_node_id,
        }

    def is_compatible_with(self, capability_id: str) -> bool:
        """Check if this platform can execute the given capability."""
        if self.runtime_tier == RuntimeTier.FULL:
            return True
        # Lite tier: only allowed capabilities
        if capability_id in LITE_NODE_RESTRICTED_CAPABILITIES:
            return False
        return capability_id in LITE_NODE_ALWAYS_ALLOWED

    @property
    def platform_tag(self) -> str:
        """Canonical platform tag, e.g. 'linux-amd64-gnu-64-full'."""
        return f"{self.os_name.lower()}-{self.architecture.value}-{self.abi.value}-{self.word_size.value}-{self.runtime_tier.value}"


# Platform-specific capability allowlist (backward compat)

PLATFORM_CAPABILITY_ALLOWLIST: dict[str, FrozenSet[str]] = {
    "amd64": ALL_CAPABILITIES,
    "arm64": ALL_CAPABILITIES,
    "armv7": LITE_NODE_ALWAYS_ALLOWED,
    "armv6": LITE_NODE_ALWAYS_ALLOWED,
}

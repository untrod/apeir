# -*- coding: utf-8 -*-
"""Platform detection unit tests."""

import pytest

from nous_runtime.platform.detector import detect_platform
from nous_runtime.platform.models import (
    Architecture,
    ABI,
    RuntimeTier,
    WordSize,
)


class TestArchitectureMapping:
    """Architecture.from_machine() maps all known machine strings."""

    def test_amd64_variants(self):
        for machine in ("x86_64", "amd64", "x64"):
            arch = Architecture.from_machine(machine)
            assert arch == Architecture.AMD64
            assert arch.is_64bit is True
            assert arch.is_arm is False
            assert arch.word_size_bits == 64

    def test_arm64_variants(self):
        for machine in ("aarch64", "arm64", "armv8"):
            arch = Architecture.from_machine(machine)
            assert arch == Architecture.ARM64
            assert arch.is_64bit is True
            assert arch.is_arm is True
            assert arch.word_size_bits == 64

    def test_armv7_variants(self):
        for machine in ("armv7l", "arm", "arm32"):
            arch = Architecture.from_machine(machine)
            assert arch == Architecture.ARMV7
            assert arch.is_64bit is False
            assert arch.is_arm is True
            assert arch.word_size_bits == 32

    def test_armv6(self):
        arch = Architecture.from_machine("armv6l")
        assert arch == Architecture.ARMV6
        assert arch.is_64bit is False

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown machine architecture"):
            Architecture.from_machine("mips")


class TestRuntimeTier:
    """RuntimeTier assignment from Architecture."""

    def test_full_tier_architectures(self):
        for arch in (Architecture.AMD64, Architecture.ARM64):
            tier = RuntimeTier.from_arch(arch)
            assert tier == RuntimeTier.FULL

    def test_lite_tier_architectures(self):
        for arch in (Architecture.ARMV7, Architecture.ARMV6):
            tier = RuntimeTier.from_arch(arch)
            assert tier == RuntimeTier.LITE


class TestPlatformInfo:
    """PlatformInfo capability compatibility checks."""

    def test_full_tier_allows_all_capabilities(self):
        info = detect_platform()
        # On any CI runner (amd64/arm64), all capabilities should be allowed
        if info.runtime_tier == RuntimeTier.FULL:
            assert info.is_compatible_with("model.invoke") is True
            assert info.is_compatible_with("desktop.ui") is True
            assert info.is_compatible_with("vector.search") is True
            assert info.is_compatible_with("identity.attest") is True

    def test_lite_tier_restricts_capabilities(self):
        from nous_runtime.platform.models import LITE_NODE_RESTRICTED_CAPABILITIES, LITE_NODE_ALWAYS_ALLOWED

        # Simulate a lite platform
        info = detect_platform()
        lite_info = info.__class__(
            architecture=Architecture.ARMV7,
            abi=info.abi,
            word_size=WordSize.BITS32,
            runtime_tier=RuntimeTier.LITE,
            os_name=info.os_name,
            os_version=info.os_version,
            hostname=info.hostname,
        )

        # Restricted capabilities should be rejected
        for cap in list(LITE_NODE_RESTRICTED_CAPABILITIES)[:5]:
            assert lite_info.is_compatible_with(cap) is False, f"{cap} should be restricted"

        # Allowed capabilities should pass
        for cap in list(LITE_NODE_ALWAYS_ALLOWED)[:5]:
            assert lite_info.is_compatible_with(cap) is True, f"{cap} should be allowed"

    def test_platform_tag_format(self):
        info = detect_platform()
        tag = info.platform_tag
        parts = tag.split("-")
        assert len(parts) == 5, f"Expected 5 parts in tag, got: {tag}"
        assert parts[0] in ("linux", "windows", "darwin")
        assert parts[1] in ("amd64", "arm64", "armv7", "armv6", "riscv64")
        assert parts[3] in ("32", "64")


class TestABI:
    """ABI detection."""

    def test_detect_returns_valid_abi(self):
        abi = ABI.detect()
        assert isinstance(abi, ABI)
        assert abi.value in ("gnu", "musl", "msvc", "android", "gnueabihf", "gnueabi")


class TestWordSize:
    """Word size detection."""

    def test_detect_returns_valid_word_size(self):
        ws = WordSize.detect()
        assert isinstance(ws, WordSize)
        assert ws.value in (32, 64)

    def test_word_size_matches_arch(self):
        """Word size should be consistent with architecture bitness."""
        import platform
        machine = platform.machine()
        arch = Architecture.from_machine(machine)
        ws = WordSize.detect()
        assert ws.value == arch.word_size_bits
